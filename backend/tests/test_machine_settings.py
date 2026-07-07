from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.runtime import service as global_service
from app.services import machine_settings as ms


class AssistantTagsServiceTests(unittest.TestCase):
    """Machine-global assistant-tag vocabulary (#88) — register, color, persist."""

    def test_register_adds_new_tags_without_color(self) -> None:
        tags = ms.register_assistant_tags(["Roleplay", "  Editor  ", ""])
        by_name = {t.name: t for t in tags}
        self.assertEqual(set(by_name), {"Roleplay", "Editor"})  # blank dropped, trimmed
        self.assertIsNone(by_name["Roleplay"].color)

    def test_register_is_idempotent_and_never_clobbers_color(self) -> None:
        ms.register_assistant_tags(["Roleplay"])
        ms.set_assistant_tag_color("Roleplay", "rose")
        # Re-registering the same tag (e.g. saving the assistant again) keeps color.
        tags = ms.register_assistant_tags(["Roleplay", "Editor"])
        by_name = {t.name: t for t in tags}
        self.assertEqual(by_name["Roleplay"].color, "rose")
        self.assertIsNone(by_name["Editor"].color)

    def test_set_color_registers_an_unknown_tag(self) -> None:
        tags = ms.set_assistant_tag_color("Brand New", "teal")
        self.assertEqual([(t.name, t.color) for t in tags], [("Brand New", "teal")])

    def test_set_color_none_clears(self) -> None:
        ms.set_assistant_tag_color("Roleplay", "rose")
        tags = ms.set_assistant_tag_color("Roleplay", None)
        self.assertIsNone({t.name: t for t in tags}["Roleplay"].color)

    def test_tag_names_from_field_handles_list_and_csv(self) -> None:
        self.assertEqual(ms.tag_names_from_field(["a", " b "]), ["a", "b"])
        self.assertEqual(ms.tag_names_from_field("a, b ,"), ["a", "b"])
        self.assertEqual(ms.tag_names_from_field(None), [])


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
    """Use temp-dir paths instead of hardcoded `C:/...` literals — those
    look real enough to confuse anyone scanning a live config.yaml. With
    the autouse conftest fixture redirecting config_path to a tmp dir,
    the value still doesn't leak; using a tmp-derived path is just defensive."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.projects_folder = str(Path(self.tmp.name) / "writing")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_projects_folder_roundtrips_through_update(self) -> None:
        response = self.client.put(
            "/api/settings/machine",
            json={"default_projects_folder": self.projects_folder},
        )
        self.assertEqual(response.status_code, 200, response.text)
        view = self.client.get("/api/settings/machine").json()
        self.assertEqual(view["default_projects_folder"], self.projects_folder)

    def test_omitting_default_projects_folder_keeps_current(self) -> None:
        self.client.put(
            "/api/settings/machine",
            json={"default_projects_folder": self.projects_folder},
        )
        # Subsequent update of a different field doesn't clobber it.
        self.client.put(
            "/api/settings/machine",
            json={"default_provider": "openai"},
        )
        view = self.client.get("/api/settings/machine").json()
        self.assertEqual(view["default_projects_folder"], self.projects_folder)


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


class PaletteTests(unittest.TestCase):
    """Palette state: seeded defaults, rewrite via PUT, validation."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_seeded_palette_on_fresh_settings(self) -> None:
        view = self.client.get("/api/settings/machine").json()
        palette = view["palette"]
        # The seed list is non-empty and includes the four built-in kind
        # colors that the context picker historically hardcoded.
        self.assertGreater(len(palette), 4)
        ids = {s["id"] for s in palette}
        for required in ("forest", "slate-blue", "warm-brown", "graphite"):
            self.assertIn(required, ids)

    def test_palette_rewrite_replaces_list(self) -> None:
        response = self.client.put(
            "/api/settings/machine",
            json={
                "palette": [
                    {"id": "red", "label": "Red", "hex": "#cc0000"},
                    {"id": "blue", "label": "Blue", "hex": "#0044cc"},
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        view = self.client.get("/api/settings/machine").json()
        ids = [s["id"] for s in view["palette"]]
        # User-set swatches are at the FRONT (untouched), seeded swatches
        # the user is missing are appended at the END by _top_up_palette
        # so they don't have to manually re-add the latest defaults.
        self.assertEqual(ids[:2], ["red", "blue"])
        for seed_id in ("forest", "slate-blue", "warm-brown", "graphite"):
            self.assertIn(seed_id, ids)

    def test_palette_rejects_bad_hex(self) -> None:
        response = self.client.put(
            "/api/settings/machine",
            json={"palette": [{"id": "x", "label": "X", "hex": "not-a-color"}]},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_palette_rejects_bad_id(self) -> None:
        # ids must be slug-shaped (lowercase, alphanumeric, dashes).
        response = self.client.put(
            "/api/settings/machine",
            json={"palette": [{"id": "Has Spaces", "label": "X", "hex": "#cc0000"}]},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_omitting_palette_keeps_current(self) -> None:
        # Rewrite, then update a different field — user-set swatches stay put.
        # (Top-up also re-adds any missing seed swatches; the user's "only"
        # swatch must remain at the front, untouched.)
        self.client.put(
            "/api/settings/machine",
            json={"palette": [{"id": "only", "label": "Only", "hex": "#abcdef"}]},
        )
        self.client.put(
            "/api/settings/machine",
            json={"default_provider": "openai"},
        )
        view = self.client.get("/api/settings/machine").json()
        ids = [s["id"] for s in view["palette"]]
        self.assertEqual(ids[0], "only")


if __name__ == "__main__":
    unittest.main()
