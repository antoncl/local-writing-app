from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.runtime import current_scope
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
        self.project_root = Path(self.tmp.name).resolve()

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
        self.root = Path(self.tmp.name).resolve()
        current_scope.clear()
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

    def test_create_ignores_a_projects_base_folder_it_no_longer_accepts(self) -> None:
        """#429 removed the field; a client still sending it must not break.

        It went required → optional → gone. The walk's bound is the machine
        root now, so create has nothing to do with one. Pydantic ignores
        unknown keys by default and that is the behaviour worth pinning: a
        frontend cached from before the change keeps working, and — the part
        that matters — the value it sends has no effect on the chain.
        """
        response = self.client.post(
            "/api/project/create",
            json={
                "root_path": str(self.root / "no-base"),
                "title": "No Base",
                "projects_base_folder": str(self.root / "somewhere-else"),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        manifest_path = Path(response.json()["root_path"]) / "project.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("projects_base_folder", manifest["settings"])


class DefaultProjectsFolderTests(unittest.TestCase):
    """Use temp-dir paths instead of hardcoded `C:/...` literals — those
    look real enough to confuse anyone scanning a live config.yaml. With
    the autouse conftest fixture redirecting config_path to a tmp dir,
    the value still doesn't leak; using a tmp-derived path is just defensive."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        folder = Path(self.tmp.name).resolve() / "writing"
        # Has to exist since #429: the value is the layer walk's bound now, and
        # a root that is not a real folder is refused on save.
        folder.mkdir()
        self.projects_folder = str(folder)
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


class TheProjectsRootIsValidatedOnSaveTests(unittest.TestCase):
    """#429 moved the layer walk's bound here, so a bad value is not a local
    mistake — it silently flattens the chain for **every** project at once.

    The check that used to guard the equivalent per-project key
    (`_validate_projects_base_folder`) was deleted along with that key. These
    pin its replacement, because the failure it prevents is invisible: an
    unvalidated root produces no error, just every project quietly inheriting
    nothing and a validation warning blaming each project for being "outside" a
    folder that never existed.
    """

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name).resolve()
        self.client = TestClient(app)

    def _put(self, folder: str) -> Any:
        return self.client.put("/api/settings/machine", json={"default_projects_folder": folder})

    def test_a_folder_that_does_not_exist_is_refused(self) -> None:
        response = self._put(str(self.dir / "typo"))

        self.assertEqual(response.status_code, 404, response.text)
        self.assertIn("does not exist", response.json()["detail"])
        self.assertEqual(ms.load_settings().default_projects_folder, "")

    def test_a_file_is_refused(self) -> None:
        target = self.dir / "notes.txt"
        target.write_text("not a folder", encoding="utf-8")

        response = self._put(str(target))

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(ms.load_settings().default_projects_folder, "")

    def test_a_real_folder_is_stored_resolved(self) -> None:
        response = self._put(str(self.dir))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(ms.load_settings().default_projects_folder, str(self.dir))

    def test_empty_clears_it_rather_than_being_refused(self) -> None:
        """Unset is a legal state — every machine starts there, and it is the
        only way to deliberately clear the setting."""
        self.assertEqual(self._put(str(self.dir)).status_code, 200)

        response = self._put("")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(ms.load_settings().default_projects_folder, "")

    def test_a_root_the_open_project_is_outside_is_still_accepted(self) -> None:
        """Deliberately NOT checked (unlike the per-project key it replaced).

        Refusing a root because the currently-open project sits outside it
        would make the setting unfixable from the one screen that edits it —
        exactly when the author most needs to fix it. A project outside the
        root is #441's subject, not this validator's.
        """
        elsewhere = self.dir / "elsewhere"
        elsewhere.mkdir()

        self.assertEqual(self._put(str(elsewhere)).status_code, 200)


if __name__ == "__main__":
    unittest.main()
