"""Shared FastAPI runtime: the scope choke point and error translation (#170, #399).

There is no process-wide `ProjectService` any more. A service is bound to an
immutable `WorkScope` at construction, and `resolve_current_project` is the
**one place** an incoming request's scope is read (ADR-0045). Routes declare
`project: CurrentProject` and get a handle that cannot be re-pointed under
them; a concurrent `open_project` changes what the *next* request resolves and
can no longer redirect a write already in flight.

Today the resolver reads `current_scope`, because the wire carries no project
identifier. When it does, this function reads the request instead — and no
route changes. The same seam carries ADR-0042's authoring layer L.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, HTTPException

from app.scope import CurrentScope
from app.services.project_service import ProjectService, ProjectServiceError

current_scope = CurrentScope()


def resolve_current_project() -> ProjectService:
    """Bind a service to this request's scope — once, here, and nowhere else.

    An absent scope is not refused here: several routes (the machine-level
    assistant surfaces) legitimately run with no project open, and every route
    that does need a root already says so through `_require_project()`'s 409.
    Refusing early would turn a working surface into a 409 and put a policy
    decision in the wiring.
    """
    return ProjectService(current_scope.get())


CurrentProject = Annotated[ProjectService, Depends(resolve_current_project)]


@contextmanager
def translate_errors():
    try:
        yield
    except ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
