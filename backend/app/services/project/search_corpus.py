"""ADR-0085 §1: the search corpus — a memory-only, process-global cache of
every prose-bodied node's body, metadata text, and save revision.

Pure state, no service imports — so `node_index_gate.py` can import
`search_corpus` without a circular import back to `project_service.py`.
`SearchCorpusMixin` (`search_corpus_build.py`) builds and reads it;
`NodeIndexGate.invalidate()` drops it and `references.py`'s
`_apply_index_write` patches it — the corpus rides the node index's own
lifecycle rather than keeping one of its own (ADR-0085 §1). Rebuildable from
files at any time; never persisted.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CorpusEntry:
    """One node's find-relevant content: the winner's identity (as the
    resolved index stamps it), its body and metadata text, and the exact
    revision value its own save primitive checks a `base_revision` against.

    `body` is the file's body after the front-matter split, with `\\r\\n`
    normalised to `\\n`. `metadata_values` is the `(label, value)` pairs
    `_iter_metadata_search_values` already derives for display/search — a
    reference field carries its resolved title, not a raw id. `revision` is
    never re-derived: a plain `_revision` hash for a scene, the composite
    revision for an overridable lore/prompt entry — whichever the kind's own
    save compares against.
    """

    id: str
    kind: str
    entry_type: str
    title: str
    path: Path
    layer_id: str
    owned: bool
    body: str
    metadata_values: tuple[tuple[str, str], ...]
    revision: str


class SearchCorpus:
    """Memory-only, process-global, one project at a time (mirrors
    `NodeIndexGate`'s single slot). Rebuildable from files at any time;
    dropped by `NodeIndexGate.invalidate()`; patched by
    `ProjectService._patch_search_corpus` from `_apply_index_write`. Never
    persisted.

    `peek` returns the held dict *object*, not a copy — callers treat it as
    read-only. Every method takes the lock, and every mutation publishes a
    NEW dict rather than editing the held one (`ResolvedIndex`'s
    immutable-after-publication idiom): a search iterating the dict it
    peeked keeps a consistent snapshot while a save patches the corpus from
    the request thread-pool's other worker — no "dictionary changed size
    during iteration".

    `_generation` is what makes a cold build's check-build-publish safe
    without holding the lock across the build itself (hundreds of ms): a
    caller reads the generation before building, and `publish` refuses to
    replace the corpus when a write bumped the generation in the meantime —
    that write's own patch is newer than the read the build started from.
    """

    def __init__(self) -> None:
        self._root: Path | None = None
        self._entries: dict[str, CorpusEntry] = {}
        self._by_path: dict[Path, str] = {}
        self._lock = threading.Lock()
        self._generation = 0

    def peek(self, root: Path) -> dict[str, CorpusEntry] | None:
        """The held corpus for `root`, or None when empty or held for a
        different root — the caller's cue to build cold. Read-only: treat the
        returned dict as belonging to the corpus, never mutate it."""
        with self._lock:
            if self._root == root and self._entries:
                return self._entries
            return None

    def publish(self, root: Path, entries: Iterable[CorpusEntry], *, generation: int) -> bool:
        """Replace the held corpus wholesale with a cold build's result — but
        only when `generation` (read via `generation()` before the build
        started) still matches: a write landing mid-build calls `note_write`,
        which bumps `_generation` and means this build's result is stale
        relative to that write. Returns whether the publish actually
        happened, so the caller knows to retry instead of serving a corpus
        that just silently dropped a concurrent save."""
        with self._lock:
            if self._generation != generation:
                return False
            self._root = root
            self._entries = {entry.id: entry for entry in entries}
            self._by_path = {entry.path: entry.id for entry in self._entries.values()}
            return True

    def upsert(self, root: Path, entry: CorpusEntry) -> None:
        """Patch one node's entry in place. A no-op when the held corpus
        belongs to a different root — a project switch drops instead."""
        with self._lock:
            self._generation += 1
            if self._root != root:
                return
            self._entries = {**self._entries, entry.id: entry}
            self._by_path = {**self._by_path, entry.path: entry.id}

    def drop_path(self, path: Path) -> None:
        """Forget whatever node is filed at `path`. A delete reaches the
        maintenance seam after the file is gone, so this drops by path
        instead of re-reading it. A no-op for an unknown path."""
        with self._lock:
            self._generation += 1
            node_id = self._by_path.get(path)
            if node_id is None:
                return
            self._by_path = {k: v for k, v in self._by_path.items() if k != path}
            self._entries = {k: v for k, v in self._entries.items() if k != node_id}

    def id_for_path(self, path: Path) -> str | None:
        with self._lock:
            return self._by_path.get(path)

    def generation(self) -> int:
        """The current generation, to pass back into `publish` after a cold
        build started from it."""
        with self._lock:
            return self._generation

    def note_write(self) -> None:
        """Record that a write happened while the corpus held nothing to
        patch (`_patch_search_corpus` saw `peek` return None) — bumping the
        generation so an in-flight cold build sees it moved and rebuilds
        instead of publishing a snapshot the write predates."""
        with self._lock:
            self._generation += 1

    def drop(self) -> None:
        """Forget everything. Rides the node index's own invalidate — the
        corpus has no lifecycle of its own (ADR-0085 §1)."""
        with self._lock:
            self._generation += 1
            self._root = None
            self._entries = {}
            self._by_path = {}


search_corpus = SearchCorpus()
