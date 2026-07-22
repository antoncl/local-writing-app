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
        with self._lock:
            self._scope = scope

    def clear(self) -> None:
        with self._lock:
            self._scope = None
