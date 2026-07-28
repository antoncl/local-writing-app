"""The scope of one unit of work (#399, #413, ADR-0045).

ADR-0045: *scope belongs to the unit of work, not the process*, and *a unit
resolves its scope once and never re-resolves it*. Before #399 the scope lived
in a mutable field on a process-wide `ProjectService` that `open_project`
swapped in place, so any helper re-reading it mid-request could straddle a scope
change — the shape behind #379's and #381's data-loss paths.

`WorkScope` is **immutable** and belongs to the unit. A `ProjectService` is
bound to one at construction and cannot be re-pointed, so re-reading it is not
merely discouraged — there is nothing to re-read.

Where the scope *comes from* is the wire: #413 put the resolution scope on the
request (the `X-Project-Root` header), and `app.runtime.resolve_current_project`
is the one choke point that reads it. There is no process-wide record of "what
the client last opened" any more — a stale write carries its own project on the
request and lands there or fails, never in whatever some other request opened.
"""

from __future__ import annotations

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
    `validate_project` reports it. A scope resolved straight from the wire (a
    request that never went through `/open`) carries none, which is correct —
    nothing migrated on that path.
    """

    root: Path
    authoring_layer: Path | None = None
    migrations_applied: tuple[str, ...] = field(default=())
