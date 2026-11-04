"""A tab that outlives a backend upgrade cannot read or write around the
migration (#2675): the scope resolver refuses it, and the re-open it is told to
do brings the refused edit and the migrated file together."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import project_fixtures
import pytest
from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import SaveSceneRequest
from app.services import migrations
from app.services.migrations import (
    CURRENT_VERSION,
    read_project_version,
    write_project_version,
)
from app.services.project import version_gate


def _old(char: str, text: str, enc: str) -> str:
    return f"<!-- character:id={char};internal={enc} -->{text}<!-- /character -->"


def _beat(char: str, text: str, enc: str) -> str:
    return f"<!-- character:id={char} -->{text}<!-- /character:id={char};internal={enc} -->"


OLD_BODY = _old("annie", "One.", "x") + "\n\n" + _old("annie", "Two.", "x")


def _downgrade(root: Path, version: int = 16) -> None:
    """Stamp `root` old, moving the mtime on so the memo cannot miss a same-size,
    same-tick rewrite on a coarse-mtime filesystem."""
    write_project_version(root, version)
    stat = (root / "project.yaml").stat()
    os.utime(root / "project.yaml", ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def book(tmp_path: Path):
    root = tmp_path.resolve() / "book"
    return root, open_test_project(root, "Book")


@pytest.fixture
def old_scene(book, client):
    """A v16 project holding a v16 body, and the scene as a tab loaded it before
    the upgrade. No `/open` has happened since."""
    root, service = book
    scene_id = client.post("/api/scenes", json={"title": "The Tide"}).json()["id"]
    service.save_scene(
        scene_id,
        SaveSceneRequest(title="The Tide", body=OLD_BODY, status="draft", entry_type="manuscript:scene"),
    )
    loaded = service.read_scene(scene_id)
    _downgrade(root)
    return root, service, scene_id, loaded


def _save_payload(loaded, body: str) -> dict:
    return {
        "title": loaded.title,
        "body": body,
        "status": loaded.status,
        "entry_type": loaded.entry_type,
        "metadata": loaded.metadata,
        "base_revision": loaded.revision,
    }


def _assert_refused(response) -> None:
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "project_outdated"


def test_a_save_from_a_tab_that_never_opened_loses_nothing(old_scene, client) -> None:
    root, service, scene_id, loaded = old_scene
    scene_file = next((root / "scenes").glob("*.md"))
    before = scene_file.read_bytes()
    edited = OLD_BODY + "\n\nThe edit typed before the upgrade."

    # Refused: the file is byte-identical and the project is still on v16, so the
    # old-format body cannot land in a project about to be stamped current.
    _assert_refused(client.put(f"/api/scenes/{scene_id}", json=_save_payload(loaded, edited)))
    assert scene_file.read_bytes() == before
    assert read_project_version(root) == 16

    # The re-open the 409 asks for migrates; the attribution and interiority survive.
    opened = client.post("/api/project/open", json={"root_path": str(root)})
    assert opened.status_code == 200
    assert opened.json()["schema_version"] == CURRENT_VERSION
    migrated = client.get(f"/api/scenes/{scene_id}").json()
    assert migrated["body"].strip() == _beat("annie", "One.\n\nTwo.", "x")

    # The stale revision still conflicts rather than overwriting the migrated file
    # with the old format. That 409 is what starts the client's reconcile ladder.
    stale = client.put(f"/api/scenes/{scene_id}", json=_save_payload(loaded, edited))
    assert stale.status_code == 409
    assert "changed on disk" in stale.json()["detail"]

    # The ladder's re-save: the migrated body plus the edit, at the fresh revision.
    merged = migrated["body"].rstrip() + "\n\nThe edit typed before the upgrade."
    payload = {**_save_payload(loaded, merged), "base_revision": migrated["revision"]}
    assert client.put(f"/api/scenes/{scene_id}", json=payload).status_code == 200
    saved = service.read_scene(scene_id).body
    assert _beat("annie", "One.\n\nTwo.", "x") in saved
    assert "The edit typed before the upgrade." in saved


def test_reads_are_refused_too(old_scene, client) -> None:
    # The loss begins when a new editor LOADS an old-format body.
    _root, _service, scene_id, _loaded = old_scene
    _assert_refused(client.get(f"/api/scenes/{scene_id}"))


def test_a_tab_opened_under_another_version_is_refused_on_a_current_project(book, client) -> None:
    # The packaged update: the relaunch's new tab already migrated the project,
    # so the disk says current and only the tab's own version gives it away.
    root, _service = book
    assert read_project_version(root) == CURRENT_VERSION
    _assert_refused(client.get("/api/project", headers={"X-Project-Schema-Version": str(CURRENT_VERSION - 1)}))
    assert client.get("/api/project", headers={"X-Project-Schema-Version": str(CURRENT_VERSION)}).status_code == 200


def test_a_request_without_the_version_header_answers_only_to_the_disk(book, client) -> None:
    assert client.get("/api/project").status_code == 200


def test_a_backup_restored_under_a_live_tab_is_noticed(book, client) -> None:
    root, _service = book
    assert client.get("/api/project").status_code == 200
    _downgrade(root)
    _assert_refused(client.get("/api/project"))


def test_the_manifest_is_read_once_until_it_changes(book, client, monkeypatch) -> None:
    root, _service = book
    assert client.get("/api/project").status_code == 200
    reads: list[Path] = []
    real = migrations.stated_project_version
    monkeypatch.setattr(
        migrations, "stated_project_version", lambda path: reads.append(path) or real(path)
    )
    from app.runtime import resolve_current_project

    header = quote(str(root), safe="")
    resolve_current_project(header)
    resolve_current_project(header)
    assert reads == []  # the memo from the earlier requests answers both

    _downgrade(root, CURRENT_VERSION)
    resolve_current_project(header)
    resolve_current_project(header)
    assert reads == [root]


def test_opening_clears_the_refusal(old_scene, client) -> None:
    root, _service, scene_id, _loaded = old_scene
    assert client.post("/api/project/open", json={"root_path": str(root)}).status_code == 200
    assert client.get(f"/api/scenes/{scene_id}").status_code == 200


def test_a_header_naming_no_project_is_not_policed(tmp_path: Path, client) -> None:
    # It keeps today's downstream failure, never this 409.
    project_fixtures.clear_test_scope()
    response = client.get(
        "/api/project", headers={"X-Project-Root": quote(str(tmp_path / "nowhere"), safe="")}
    )
    detail = response.json().get("detail") if response.status_code == 409 else None
    assert not (isinstance(detail, dict) and detail.get("code") == "project_outdated")


def test_a_locked_manifest_fails_the_open_rather_than_migrating_from_zero(book, client, monkeypatch) -> None:
    # Windows: antivirus holding project.yaml for a moment. The ladder must not run
    # from v0 over a current project, and a request is not refused as outdated either.
    root, _service = book
    real_read_text = Path.read_text

    def locked(path: Path, *args, **kwargs) -> str:
        if path.name == "project.yaml":
            raise PermissionError("locked")
        return real_read_text(path, *args, **kwargs)

    # A changed stat, so the memo cannot answer and the file has to be read.
    _downgrade(root, CURRENT_VERSION)
    monkeypatch.setattr(Path, "read_text", locked)
    with pytest.raises(PermissionError):
        read_project_version(root)
    assert version_gate._version_on_disk(root) is None


def test_opening_forgets_a_version_remembered_mid_migration(book, client) -> None:
    # A coarse-mtime drive: the stamp landed in the tick of a read made before it,
    # at the same size, so the stat alone cannot tell the memo it is stale.
    root, _service = book
    stat = (root / "project.yaml").stat()
    version_gate._memo[root] = (stat.st_mtime_ns, stat.st_size, CURRENT_VERSION - 1)
    _assert_refused(client.get("/api/project"))
    assert client.post("/api/project/open", json={"root_path": str(root)}).status_code == 200
    assert client.get("/api/project").status_code == 200


def test_an_unreadable_manifest_is_not_treated_as_an_old_project(book, client) -> None:
    # A typo while hand-editing must not start a migration from v0 on its own.
    root, _service = book
    (root / "project.yaml").write_text("title: [unclosed\n", encoding="utf-8")
    response = client.get("/api/project")
    detail = response.json().get("detail") if response.status_code == 409 else None
    assert not (isinstance(detail, dict) and detail.get("code") == "project_outdated")
