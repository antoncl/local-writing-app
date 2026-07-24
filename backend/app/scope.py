"""The scope of one unit of work, and the process's record of what is open (#399).

ADR-0045: *scope belongs to the unit of work, not the process*, and *a unit
resolves its scope once and never re-resolves it*. Before this, the scope lived
in a mutable field on a process-wide `ProjectService` that `open_project` swapped
in place, so any helper re-reading it mid-request could straddle a scope change —
the shape behind #379's and #381's data-loss paths.

Two objects, deliberately separate:

- `WorkScope` is **immutable** and belongs to the unit. A `ProjectService` is
  bound to one at construction and cannot be re-pointed, so re-reading it is
  not merely discouraged — there is nothing to re-read.
- `CurrentScope` is the process's memory of *what the client last opened*. It
  exists only because the wire carries no project identifier yet; it is read at
  exactly one choke point (`app.runtime.resolve_current_project`) and never
  again inside a unit. When scope reaches the wire, the choke point reads the
  request instead and this registry goes away without touching a route.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WorkScope:
    """What one unit of work is operating on.

    `root` is ADR-0045's *resolution scope* — the project being built.
    `authoring_layer` is its *authoring layer L*, the write target ADR-0042
    binds; it is reserved, not yet sent by any client, and defaults to the
    resolution scope. It lives here rather than arriving later so that #313/#314
    add it by changing the resolver alone.

    `migrations_applied` is a property of the *open event*, not of the project:
    it is what `migrate_project` did when this scope was resolved, and
    `validate_project` reports it.
    """

    root: Path
    authoring_layer: Path | None = None
    migrations_applied: tuple[str, ...] = field(default=())


class CurrentScope:
    """The project the client last opened.

    Guarded by a lock because mutation routes run on FastAPI's threadpool, so a
    read and a concurrent `open_project` genuinely interleave. The lock makes the
    *handoff* atomic; it is not what makes a unit coherent — that is the handle
    being immutable once resolved.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scope: WorkScope | None = None

    def get(self) -> WorkScope | None:
        with self._lock:
            return self._scope

    def set(self, scope: WorkScope) -> None:
        # Flush any deferred snapshot **before** taking the lock (#476): the
        # flush is a disk serialize + atomic write, and `get()` shares this lock
        # on the request hot path, so holding it across the flush would stall
        # every concurrent scope read for the duration of a project switch. The
        # under-lock `invalidate()` still flushes-if-dirty as a backstop, but the
        # common case is already clean here.
        self._flush_index_memo()
        with self._lock:
            self._scope = scope
            self._drop_index_memo()

    def clear(self) -> None:
        self._flush_index_memo()
        with self._lock:
            self._scope = None
            self._drop_index_memo()

    @staticmethod
    def _flush_index_memo() -> None:
        """Write any pending node-index snapshot, off `self._lock` (#476).

        Runs before the scope lock is taken so a project switch never holds the
        lock across the flush's disk I/O. Best-effort and idempotent — a no-op
        when nothing is pending, so calling it before every `_drop_index_memo` is
        free in the common (clean) case."""
        from app.services.project.node_index_gate import node_index_gate

        node_index_gate.flush()

    @staticmethod
    def _drop_index_memo() -> None:
        """Invalidate the process-global node-index memo on every scope change.

        Unconditional — it must fire even when the new scope has the **same
        root** as the old one (#392). The memo is keyed by root, so a re-open of
        the same project would otherwise serve the index built before it: exactly
        the bug when a user reverts files from a backup while the server keeps
        running and then reopens the project. Clearing on the open event makes
        the next resolve rebuild from disk.

        Held **under `self._lock`**, so the new scope and the dropped memo become
        visible together: a concurrent request that resolves the just-set scope
        cannot slip in between and read the pre-restore index for the same root.
        The lock order is scope→gate and never the reverse (nothing holding the
        gate lock reaches for `current_scope`), so this cannot deadlock. Imported
        lazily to keep `scope.py` free of a service-layer import at module load.
        `invalidate()` still flushes-if-dirty before clearing (a backstop for a
        write that raced in after `_flush_index_memo` above); that flush is the
        rare case now, not the common one.
        """
        from app.services.project.node_index_gate import node_index_gate

        node_index_gate.invalidate()
