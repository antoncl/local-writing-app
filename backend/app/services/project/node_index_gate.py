"""The in-memory node-index memo, held per resolution scope (#392 / ADR-0040).

#306 gave the index a persisted snapshot and #307 turned a stale snapshot into a
work list — but every `_build_node_index` call still went to disk: collect the
layers, sweep the manifest (~20–41 ms of `stat`), load the snapshot, patch or
serve. Nothing made a *repeat* call cheap, so a single request that touches
several index consumers paid that sweep several times, and a prose-only autosave
paid it five times on a six-second timer.

This module is the memo behind the funnel: one built index, held in memory,
keyed by the resolution scope it was built for (the root), invalidated at unit
boundaries. `_build_node_index` becomes `gate.resolve(root, build)` — a warm hit
returns the held index with no disk work at all.

## Concurrency model — immutable index, atomic swap ("model B")

The memo is process-global: each request resolves a throwaway `ProjectService`
(`resolve_current_project`), so the cache cannot live on the instance. Sync
routes run on FastAPI's threadpool, so two requests genuinely interleave — the
same reason `CurrentScope` carries a lock. Rather than guard every read with a
lock, a **published `ResolvedIndex` is immutable and never mutated in place**:

- **reads are lock-free** — reading the one `_current` slot is atomic under the
  GIL, and what it points at is frozen after publication;
- **a write** takes the lock, patches into a **new** `ResolvedIndex`, and swaps
  the slot.

A reader that grabbed the old pointer keeps a consistent (if a beat stale) view
while a writer publishes a newer one — no torn reads, writers serialize, reads
never block. This is ADR-0045's frozen-`WorkScope` principle applied to the
index: a unit resolves its index once and never sees it change under it. The
transient second copy a swap costs is free against ADR-0040's measured memory
headroom (three orders of magnitude).

## Invalidation is keyed to the *open event*, not the root path

`CurrentScope.set` clears the memo on every scope change (`invalidate`). That is
deliberately unconditional — it must fire even when the new scope has the **same
root** as the old one. The scenario it protects (a real one under a
server-style deployment where the browser and the server have separate
lifetimes): a user reverts files from a backup while the app's server keeps
running, then reopens the browser, which re-opens the same project. A memo keyed
by root alone would serve the pre-restore index; clearing on the open event makes
the next resolve rebuild from the restored files. The remaining exposure — an
external edit under a *continuously open* session with no reopen — is ADR-0040's
named, accepted trade, mitigated by a reload.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.models import MetadataSchema
from app.services.project.node_index import IndexLayer, NodeIndex
from app.services.project.node_index_snapshot import Manifest


@dataclass(frozen=True)
class ResolvedIndex:
    """One scope's built index, plus what it was built from — the memo payload.

    Frozen and treated as immutable after publication (see the module docstring):
    readers hold it without a lock. `layers` and `manifest` ride along so the
    write path can patch and re-fingerprint against them without re-walking the
    chain or re-globbing the folders. `schema` rides along too — the change-gate
    needs it to extract a written file's edges, and re-reading the uncached
    layer-chain schema on every save doubles a read the save already did. It is
    coherent by lifetime: a schema-file write invalidates the whole memo (it fans
    out), so a held `schema` is never stale relative to its `index`. `None` means
    the schema failed to load when the index was built (a degraded, edge-less
    index), which the gate treats the same way the cold build did.
    """

    root: Path
    index: NodeIndex
    layers: tuple[IndexLayer, ...]
    manifest: Manifest
    schema: MetadataSchema | None = None


class NodeIndexGate:
    """Process-global, one slot, model B. See the module docstring."""

    def __init__(self) -> None:
        # Re-entrant so a mutate callback that falls back to a full rebuild can
        # call the build path without deadlocking on the lock it already holds.
        self._lock = threading.RLock()
        self._current: ResolvedIndex | None = None

    def peek(self, root: Path) -> ResolvedIndex | None:
        """The held index for `root`, or None. Lock-free — a single attribute
        read is atomic under the GIL, and a published `ResolvedIndex` is frozen
        and never mutated, so the caller holds a consistent view."""
        current = self._current
        if current is not None and current.root == root:
            return current
        return None

    def resolve(self, root: Path, build: Callable[[], ResolvedIndex]) -> NodeIndex:
        """Return the held index for `root`, building and publishing it on a miss.

        The double-check under the lock collapses a stampede: two requests that
        both miss the empty slot don't both rebuild — the second sees the first's
        publication.
        """
        hit = self.peek(root)
        if hit is not None:
            return hit.index
        with self._lock:
            hit = self.peek(root)
            if hit is not None:
                return hit.index
            built = build()
            self._current = built
            return built.index

    def apply(
        self, root: Path, mutate: Callable[[ResolvedIndex], ResolvedIndex | None]
    ) -> None:
        """Run `mutate` against the held index for `root`, under the lock.

        `mutate` returns the new `ResolvedIndex` to publish, or None to leave the
        slot untouched — the change-gate's no-op verdict for a write that changed
        nothing the index holds. If no index is held for `root` (nothing was ever
        resolved, or the scope moved on), there is nothing to maintain and this
        is a no-op: the next `resolve` will build cold.
        """
        with self._lock:
            current = self._current
            if current is None or current.root != root:
                return
            updated = mutate(current)
            if updated is not None:
                self._current = updated

    def invalidate(self) -> None:
        """Drop the memo. Called on every scope change (`CurrentScope.set`), so a
        re-open of the same project rebuilds rather than serving a stale index."""
        with self._lock:
            self._current = None


# The one process-global memo. Imported by `references.py` (resolve + write
# funnel) and `scope.py` (invalidate on scope change).
node_index_gate = NodeIndexGate()
