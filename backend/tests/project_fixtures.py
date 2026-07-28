"""Bind a fresh project for a test — and make it what the HTTP routes resolve.

Since #413 the resolution scope rides the wire (`X-Project-Root`), so there is
no process global to point routes at: a route resolves its project from the
request header. These helpers record the project a test wants resolved in a
module-global, and the autouse client-patch in `conftest.py` injects it as the
header on every `TestClient` request — exactly as the browser's `api.ts` does.
So the real resolver (`resolve_current_project`) still runs over the ASGI
boundary; the test just plays the browser.

A test holds a `ProjectService` bound to its own project for direct service-level
setup, and the same project resolves through the HTTP surface, without either one
re-resolving it.

Imported as a top-level module (`from project_fixtures import …`) rather than
`tests.project_fixtures`, matching `layer_fixtures` — `backend/tests` is on the
path as a rootdir, not as a package.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from app.scope import WorkScope
from app.services.project_service import ProjectService

# The project the HTTP surface should resolve for the current test, or None for
# the unbound (no project open) surfaces. Reset per-test by the conftest fixture.
_test_scope_root: Path | None = None


def set_test_scope(scope: WorkScope | None) -> None:
    """Make `scope`'s project the one `TestClient` requests resolve (or None)."""
    global _test_scope_root
    _test_scope_root = scope.root if scope is not None else None


def clear_test_scope() -> None:
    """Drop the wire scope, so requests resolve unbound — the old
    `current_scope.clear()`."""
    global _test_scope_root
    _test_scope_root = None


def test_scope_header() -> dict[str, str]:
    """The `X-Project-Root` header for the current test scope, or `{}` when
    unbound. URL-encoded to mirror the frontend's `encodeURIComponent`."""
    if _test_scope_root is None:
        return {}
    return {"X-Project-Root": quote(str(_test_scope_root), safe="")}


def open_test_project(root: Path, title: str) -> ProjectService:
    """Create a project at `root` and make it the wire scope for HTTP requests.

    Returns the handle for direct service-level setup, so a test drives the same
    project through both surfaces without either one re-resolving it.
    """
    service = ProjectService.created_at(root, title)
    set_test_scope(service.scope)
    return service


def bind_test_project(service: ProjectService) -> ProjectService:
    """Make an already-bound service's project the one routes resolve.

    For tests that build their project themselves (a layer chain, a second
    project) and then want the HTTP surface pointed at it.
    """
    scope = service.scope
    if scope is None:
        raise ValueError("Cannot bind a service with no project open.")
    set_test_scope(scope)
    return service
