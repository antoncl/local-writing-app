from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, service as global_service
from app.services import machine_settings as ms


class RecentProjectsServiceTests(unittest.TestCase):
    """touch_recent_project semantics — dedupe, cap, order."""

    def setUp(self) -> None:
        # The autouse conftest fixture already redirects config_path to a
        # per-test tempdir; we just need fresh state.
        self.tmp = TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_touch_prepends_new_entry(self) -> None:
        ms.touch_recent_project(self.project_root / "a", "Project A")
        settings = ms.load_settings()
        self.assertEqual(len(settings.recent_projects), 1)
        self.assertEqual(settings.recent_projects[0].title, "Project A")

    def test_touch_dedupes_by_path_and_moves_to_top(self) -> None:
        ms.touch_recent_project(self.project_root / "a", "Project A")
        ms.touch_recent_project(self.project_root / "b", "Project B")
        ms.touch_recent_project(self.project_root / "a", "Project A renamed")
        settings = ms.load_settings()
        self.assertEqual(len(settings.recent_projects), 2)
        self.assertEqual(settings.recent_projects[0].title, "Project A renamed")
        self.assertEqual(settings.recent_projects[1].title, "Project B")

    def test_touch_caps_at_max(self) -> None:
        for i in range(ms.RECENT_PROJECTS_MAX + 5):
            ms.touch_recent_project(self.project_root / f"p{i}", f"Project {i}")
        settings = ms.load_settings()
        self.assertEqual(len(settings.recent_projects), ms.RECENT_PROJECTS_MAX)
        # Newest at top, oldest dropped from the bottom.
        self.assertEqual(settings.recent_projects[0].title, f"Project {ms.RECENT_PROJECTS_MAX + 4}")

    def test_touch_swallows_save_errors(self) -> None:
        # Simulate a write failure — touch should NOT raise; recents is UX
        # polish, not a correctness path.
        with patch.object(ms, "save_settings", side_effect=OSError("disk full")):
            ms.touch_recent_project(self.project_root / "x", "X")  # no exception


class RecentProjectsEndpointTests(unittest.TestCase):
    """Open / create routes push onto recents; settings view exposes it."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        global_service.__init__()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_pushes_onto_recents(self) -> None:
        response = self.client.post(
            "/api/project/create",
            json={"root_path": str(self.root / "new"), "title": "Fresh Project"},
        )
        self.assertEqual(response.status_code, 200, response.text)

        view = self.client.get("/api/settings/machine").json()
        recents = view["recent_projects"]
        self.assertEqual(len(recents), 1)
        self.assertEqual(recents[0]["title"], "Fresh Project")
        self.assertTrue(recents[0]["path"].endswith("new"))

    def test_open_pushes_onto_recents(self) -> None:
        # Create first so there's something to open.
        created = self.client.post(
            "/api/project/create",
            json={"root_path": str(self.root / "p"), "title": "P"},
        ).json()
        response = self.client.post(
            "/api/project/open",
            json={"root_path": created["root_path"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        view = self.client.get("/api/settings/machine").json()
        # Create + open of the same path → dedup'd to one entry at top.
        recents = view["recent_projects"]
        self.assertEqual(len(recents), 1)

    def test_create_request_accepts_omitted_projects_base_folder(self) -> None:
        # Previously projects_base_folder was required; now optional. The
        # frontend no longer surfaces it.
        response = self.client.post(
            "/api/project/create",
            json={"root_path": str(self.root / "no-base"), "title": "No Base"},
        )
        self.assertEqual(response.status_code, 200, response.text)


class DefaultProjectsFolderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_default_projects_folder_roundtrips_through_update(self) -> None:
        response = self.client.put(
            "/api/settings/machine",
            json={"default_projects_folder": "C:/Users/me/writing"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        view = self.client.get("/api/settings/machine").json()
        self.assertEqual(view["default_projects_folder"], "C:/Users/me/writing")

    def test_omitting_default_projects_folder_keeps_current(self) -> None:
        self.client.put(
            "/api/settings/machine",
            json={"default_projects_folder": "C:/keep-me"},
        )
        # Subsequent update of a different field doesn't clobber it.
        self.client.put(
            "/api/settings/machine",
            json={"default_provider": "openai"},
        )
        view = self.client.get("/api/settings/machine").json()
        self.assertEqual(view["default_projects_folder"], "C:/keep-me")


class RecentProjectsRewriteTests(unittest.TestCase):
    """The PUT endpoint accepts an explicit recent_projects list to rewrite."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_explicit_list_replaces_recents(self) -> None:
        # Seed with two via the route, then rewrite via the update endpoint.
        ms.touch_recent_project(Path("/tmp/a"), "A")
        ms.touch_recent_project(Path("/tmp/b"), "B")

        response = self.client.put(
            "/api/settings/machine",
            json={"recent_projects": [{"path": "/tmp/c", "title": "C", "opened_at": "2026-06-20T12:00:00+00:00"}]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        view = self.client.get("/api/settings/machine").json()
        self.assertEqual([r["title"] for r in view["recent_projects"]], ["C"])

    def test_omitting_recent_projects_keeps_current(self) -> None:
        ms.touch_recent_project(Path("/tmp/x"), "X")
        self.client.put(
            "/api/settings/machine",
            json={"default_provider": "openai"},
        )
        view = self.client.get("/api/settings/machine").json()
        self.assertEqual(len(view["recent_projects"]), 1)


if __name__ == "__main__":
    unittest.main()
