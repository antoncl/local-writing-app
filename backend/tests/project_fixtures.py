"""Bind a fresh project for a test — and make it what the HTTP routes resolve.

Replaces the old two-step reset-then-create against the process-wide singleton
(#399) that every HTTP test opened with. There is no singleton now: a test
holds a `ProjectService` bound to its own project, and `current_scope` is what a
route's `CurrentProject` dependency resolves against.

Imported as a top-level module (`from project_fixtures import …`) rather than
`tests.project_fixtures`, matching `layer_fixtures` — `backend/tests` is on the
path as a rootdir, not as a package.
"""

from __future__ import annotations

from pathlib import Path

from app.runtime import current_scope
from app.services.project_service import ProjectService


def open_test_project(root: Path, title: str) -> ProjectService:
    """Create a project at `root` and make it the open scope for HTTP requests.

    Returns the handle for direct service-level setup, so a test drives the same
    project through both surfaces without either one re-resolving it.
    """
    service = ProjectService.created_at(root, title)
    current_scope.set(service.scope)
    return service


def bind_test_project(service: ProjectService) -> ProjectService:
    """Make an already-bound service's project the one routes resolve.

    For tests that build their project themselves (a layer chain, a second
    project) and then want the HTTP surface pointed at it.
    """
    scope = service.scope
    if scope is None:
        raise ValueError("Cannot bind a service with no project open.")
    current_scope.set(scope)
    return service
