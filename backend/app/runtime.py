"""Shared FastAPI runtime: the scope choke point and error translation (#170, #399, #413).

There is no process-wide `ProjectService`, and since #413 no process-wide record
of what is open either. A service is bound to an immutable `WorkScope` at
construction, and `resolve_current_project` is the **one place** an incoming
request's scope is read (ADR-0045). Routes declare `project: CurrentProject` and
get a handle that cannot be re-pointed under them.

The scope rides the wire in the `X-Project-Root` header (URL-encoded, so a
non-ASCII folder name survives a latin-1 header): the resolver reads it and no
route changes — that is what choosing `Depends` over an explicit resolve bought.
Because the scope is the request's own, a late autosave after a restart writes
to the book it was editing or fails, never to whatever some other request opened
in the meantime; the ambient `current_scope` that used to answer that question is
gone (#413). The same seam carries ADR-0042's authoring layer L when a picker
ships (#313/#314).

An absent header is not refused here: several routes (the machine-level
assistant surfaces) legitimately run with no project open, and every route that
does need a root already says so through `_require_project()`'s 409. A header
that names something that is not a project is not policed either — there is no
ambient scope left to silently fall back to, so its downstream reads simply fail,
the same way editing a project whose files were deleted mid-session does.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, Header, HTTPException

from app.scope import WorkScope
from app.services.project_service import ProjectService, ProjectServiceError


def resolve_current_project(
    x_project_root: Annotated[str | None, Header()] = None,
) -> ProjectService:
    """Bind a service to this request's scope — once, here, and nowhere else."""
    if not x_project_root:
        return ProjectService(None)
    root = Path(unquote(x_project_root)).expanduser().resolve()
    return ProjectService(WorkScope(root=root))


CurrentProject = Annotated[ProjectService, Depends(resolve_current_project)]


@contextmanager
def translate_errors():
    try:
        yield
    except ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
