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

## The snapshot flush is deferred behind a dirty flag (#476 / ADR-0040)

The in-memory patch is eager — a write publishes the new index immediately, so
every reader sees the change at once. The **snapshot** it derives is not: writing
it is ~16–31 ms of serialize + atomic write, and it is pure rebuildable cache (a
crash before it lands loses nothing the next open's manifest diff cannot
recover). So a structural write patches the memo and registers a **pending
flush** rather than writing then and there; the flush fires at a boundary the app
already reaches — the next `resolve()` (a read is here anyway), `invalidate()`
(flush-if-dirty *before* clearing, so a project switch never strands a write),
and clean shutdown. This is ADR-0040's "dirty-flag" reading, chosen over its
"debounce" reading: no background timer thread, and — per ADR-0043 Amendment 2's
own logic — an idle/close timer is the one trigger a crash does not fire, so it
cannot be what durability rests on. Here nothing durable rests on it anyway.

Each new write **overwrites** the pending flush with its own, so a burst of
structural edits (a chapter delete unlinks 20 scenes, the reference purge then
rewrites every referencing file) coalesces to a single snapshot write at the next
boundary instead of one per file.

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
        # A deferred snapshot write (#476). Set when a write patches the memo,
        # cleared when it flushes. A self-contained thunk — it captures the
        # writer and the index to write — so `invalidate()` and the shutdown
        # hook can fire it without a `ProjectService` in hand. Overwritten by
        # each new write, which is how a burst coalesces to one flush.
        self._pending_flush: Callable[[], None] | None = None

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
            # A read is here anyway — flush a deferred snapshot now so the disk
            # cache tracks the memo. The unlocked pre-check keeps the common
            # clean read (nothing pending) lock-free; a stale read of the flag
            # only ever defers the flush one more `resolve`, never loses it.
            if self._pending_flush is not None:
                self.flush()
            return hit.index
        with self._lock:
            hit = self.peek(root)
            if hit is not None:
                if self._pending_flush is not None:
                    self._flush_locked()
                return hit.index
            # A pending flush here belongs to the *outgoing* current (a miss means
            # a different root, or none): flush it before building so its snapshot
            # is never dropped. In normal flow `invalidate` already did on the
            # scope change; this makes the gate correct even without that. The
            # cold build then writes its own snapshot, so nothing is pending for
            # what we publish.
            self._flush_locked()
            built = build()
            self._current = built
            return built.index

    def apply(
        self,
        root: Path,
        mutate: Callable[[ResolvedIndex], ResolvedIndex | None],
        flush: Callable[[ResolvedIndex], None],
    ) -> None:
        """Run `mutate` against the held index for `root`, under the lock.

        `mutate` returns the new `ResolvedIndex` to publish, or None to leave the
        slot untouched — the change-gate's no-op verdict for a write that changed
        nothing the index holds. On a publish, `flush` is captured as the pending
        snapshot write (#476) rather than run now; it fires at the next boundary.
        If no index is held for `root` (nothing was ever resolved, or the scope
        moved on), there is nothing to maintain and this is a no-op: the next
        `resolve` will build cold.
        """
        with self._lock:
            current = self._current
            if current is None or current.root != root:
                return
            updated = mutate(current)
            if updated is not None:
                self._current = updated
                self._pending_flush = lambda: flush(updated)

    def flush(self) -> None:
        """Write any deferred snapshot now. A no-op when nothing is pending.

        Called from `resolve` (a reader arrived) and the clean-shutdown hook. The
        write runs under the lock — the same footing as the synchronous write it
        replaced — and is best-effort: `_write_index_snapshot` swallows an
        `OSError`, so a read-only cache folder costs the next open its speed and
        nothing else.
        """
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        pending = self._pending_flush
        if pending is not None:
            # Clear first: the write is idempotent, and clearing before running
            # means a write that somehow re-enters cannot loop on its own thunk.
            self._pending_flush = None
            pending()

    def invalidate(self) -> None:
        """Drop the memo. Called on every scope change (`CurrentScope.set`), so a
        re-open of the same project rebuilds rather than serving a stale index.

        Flushes a pending snapshot **before** clearing (#476): a scope switch
        would otherwise strand the outgoing project's deferred write, and the
        incoming project's open does not rebuild it. The flush writes the
        outgoing root's index, which is exactly what the captured thunk holds."""
        with self._lock:
            self._flush_locked()
            self._current = None


# The one process-global memo. Imported by `references.py` (resolve + write
# funnel) and `scope.py` (invalidate on scope change).
node_index_gate = NodeIndexGate()
