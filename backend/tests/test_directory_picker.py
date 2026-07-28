"""Folder-picker v2 backend surface (#530, slice P).

The picker is pure filesystem browsing — no open project needed — so these
drive `ProjectService()` methods directly against a tmp tree: enriched
listings (is-project / is-empty), the roots enumerator, the non-throwing path
probe, and inline folder creation. A second block exercises the same surface
through the HTTP routes, including the no-open-project path the wizard's
first-run step relies on.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


@pytest.fixture
def service() -> ProjectService:
    # No scope: the picker never touches an open project.
    return ProjectService()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _make_project(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.yaml").write_text("title: A\n", encoding="utf-8")


# --- service level -------------------------------------------------------


def test_listing_flags_mark_projects_and_empties(service: ProjectService, tmp_path: Path) -> None:
    _make_project(tmp_path / "a-book")
    (tmp_path / "empty").mkdir()
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "note.txt").write_text("x", encoding="utf-8")

    listing = service.list_directories(tmp_path)

    by_name = {entry.name: entry for entry in listing.directories}
    assert by_name["a-book"].is_project is True
    assert by_name["a-book"].is_empty is False
    assert by_name["empty"].is_project is False
    assert by_name["empty"].is_empty is True
    assert by_name["busy"].is_empty is False

    # The shown folder holds children, so it is not itself a project.
    assert listing.is_project is False
    assert listing.parent_path == str(tmp_path.parent)


def test_listing_within_root_reflects_the_machine_root(service: ProjectService, tmp_path: Path) -> None:
    """The open-project picker refuses a folder outside the machine root (#441);
    the backend decides membership and the frontend dims Select on it.

    Unset root is permissive — the wizard sets one before the app is usable, and
    flagging *everything* on the rare unset state would be worse."""
    from layer_fixtures import set_projects_root

    root = tmp_path / "shelf"
    inside = root / "book"
    outside = tmp_path / "elsewhere"
    for folder in (inside, outside):
        folder.mkdir(parents=True)

    set_projects_root(None)
    assert service.list_directories(inside).within_root is True
    assert service.list_directories(outside).within_root is True

    set_projects_root(root)
    assert service.list_directories(root).within_root is True
    assert service.list_directories(inside).within_root is True
    assert service.list_directories(outside).within_root is False


def test_listing_marks_a_project_folder_it_is_shown_from(service: ProjectService, tmp_path: Path) -> None:
    _make_project(tmp_path)
    assert service.list_directories(tmp_path).is_project is True


def test_listing_hides_internal_folders_inside_a_project(service: ProjectService, tmp_path: Path) -> None:
    # Browsing *inside* a project, its structural guts are clutter and never a
    # place to open or create a project (#559).
    _make_project(tmp_path)
    for name in ("scenes", "lore", "prompts", "research", "overrides", ".cache"):
        (tmp_path / name).mkdir()
    (tmp_path / "Book Two").mkdir()  # an ordinary sub-folder is still shown

    names = {entry.name for entry in service.list_directories(tmp_path).directories}

    assert names == {"Book Two"}


def test_listing_shows_internal_named_folders_outside_a_project(service: ProjectService, tmp_path: Path) -> None:
    # tmp_path is NOT a project, so a top-level folder merely named "lore" is a
    # real navigation target and must not be hidden (#559).
    (tmp_path / "lore").mkdir()
    (tmp_path / "scenes").mkdir()

    names = {entry.name for entry in service.list_directories(tmp_path).directories}

    assert names == {"lore", "scenes"}


def test_listing_keeps_a_child_project_sharing_an_internal_name(service: ProjectService, tmp_path: Path) -> None:
    # A child project that happens to be named like a structural folder is still
    # a project, so it survives the filter while the parent's real guts do not
    # (#559).
    _make_project(tmp_path)
    _make_project(tmp_path / "research")  # a nested project literally named "research"
    (tmp_path / "scenes").mkdir()  # the parent's actual guts — hidden

    by_name = {entry.name: entry for entry in service.list_directories(tmp_path).directories}

    assert by_name["research"].is_project is True
    assert "scenes" not in by_name


def test_listing_rejects_missing_and_non_folder(service: ProjectService, tmp_path: Path) -> None:
    with pytest.raises(ProjectServiceError) as missing:
        service.list_directories(tmp_path / "nope")
    assert missing.value.status_code == 404

    a_file = tmp_path / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(ProjectServiceError) as not_dir:
        service.list_directories(a_file)
    assert not_dir.value.status_code == 400


def test_probe_is_non_throwing_and_echoes_input(service: ProjectService, tmp_path: Path) -> None:
    blank = service.probe_path("   ")
    assert blank.is_dir is False and blank.is_project is False

    missing = service.probe_path(str(tmp_path / "ghost"))
    assert missing.is_dir is False
    assert missing.is_project is False

    a_file = tmp_path / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    assert service.probe_path(str(a_file)).is_dir is False

    _make_project(tmp_path / "book")
    hit = service.probe_path(str(tmp_path / "book"))
    assert hit.is_dir is True
    assert hit.is_project is True
    # `input` echoes verbatim so the client can drop a superseded reply.
    assert hit.input == str(tmp_path / "book")


def test_create_directory_returns_enriched_entry(service: ProjectService, tmp_path: Path) -> None:
    entry = service.create_directory(tmp_path, "New World")
    assert entry.name == "New World"
    assert (tmp_path / "New World").is_dir()
    assert entry.is_empty is True
    assert entry.is_project is False


def test_create_directory_guards(service: ProjectService, tmp_path: Path) -> None:
    with pytest.raises(ProjectServiceError) as bad_parent:
        service.create_directory(tmp_path / "missing", "child")
    assert bad_parent.value.status_code == 404

    for name in ("", "  ", ".", "..", "a/b", "a\\b"):
        with pytest.raises(ProjectServiceError) as bad_name:
            service.create_directory(tmp_path, name)
        assert bad_name.value.status_code == 400

    service.create_directory(tmp_path, "dup")
    with pytest.raises(ProjectServiceError) as clash:
        service.create_directory(tmp_path, "dup")
    assert clash.value.status_code == 409


def test_roots_include_home_and_a_drive(service: ProjectService) -> None:
    roots = service.list_directory_roots()
    kinds = {root.kind for root in roots}
    assert "home" in kinds
    assert "drive" in kinds
    for root in roots:
        assert Path(root.path).exists()
    if os.name != "nt":
        assert any(root.path == "/" for root in roots)


# --- route level (no project open — the wizard first-run path) -----------


def test_routes_work_without_an_open_project(client: TestClient, tmp_path: Path) -> None:
    _make_project(tmp_path / "book")

    listed = client.get("/api/directories", params={"path": str(tmp_path)})
    assert listed.status_code == 200
    names = {entry["name"]: entry for entry in listed.json()["directories"]}
    assert names["book"]["is_project"] is True

    roots = client.get("/api/directories/roots")
    assert roots.status_code == 200
    assert any(root["kind"] == "home" for root in roots.json())

    probe = client.get("/api/directories/probe", params={"path": str(tmp_path / "book")})
    assert probe.status_code == 200
    assert probe.json() == {
        "input": str(tmp_path / "book"),
        "is_dir": True,
        "is_project": True,
    }


def test_create_directory_route(client: TestClient, tmp_path: Path) -> None:
    made = client.post("/api/directories", json={"parent": str(tmp_path), "name": "fresh"})
    assert made.status_code == 200
    assert made.json()["name"] == "fresh"
    assert (tmp_path / "fresh").is_dir()

    clash = client.post("/api/directories", json={"parent": str(tmp_path), "name": "fresh"})
    assert clash.status_code == 409
