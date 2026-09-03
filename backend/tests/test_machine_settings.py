from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient
from project_fixtures import clear_test_scope

from app.main import app
from app.routers import machine_settings as machine_settings_router
from app.services import machine_settings as ms


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
        clear_test_scope()
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

    def test_settings_view_exposes_the_config_dir(self) -> None:
        # #1750: the app-data folder holding app.log + errors.log is surfaced so a
        # user can find the logs a bug report asks for. config_dir() is
        # authoritative (config_path = config_dir()/config.yaml); patch it here
        # since the autouse conftest redirects only config_path.
        fake = self.root / "appdata"
        with patch.object(ms, "config_dir", lambda: fake):
            view = self.client.get("/api/settings/machine").json()
        self.assertEqual(view["config_dir"], str(fake))

    def test_settings_view_marks_out_of_root_recents_unavailable(self) -> None:
        """A recent outside the machine root is unavailable — equivalent to a
        deleted folder (#441). The view marks it (`within_root=False`) so the UI
        dims it; the flag is computed, never stored."""
        from layer_fixtures import set_projects_root

        shelf = self.root / "shelf"
        shelf.mkdir()
        ms.touch_recent_project(shelf / "book", "In-root Book")
        ms.touch_recent_project(self.root / "elsewhere" / "stray", "Stray Book")
        set_projects_root(shelf)

        recents = {r["title"]: r for r in self.client.get("/api/settings/machine").json()["recent_projects"]}
        self.assertTrue(recents["In-root Book"]["within_root"])
        self.assertFalse(recents["Stray Book"]["within_root"])

        # Computed, not persisted: the stored config carries no within_root key.
        stored = yaml.safe_load(Path(ms.config_path()).read_text(encoding="utf-8"))
        self.assertTrue(all("within_root" not in r for r in stored["recent_projects"]))

    def test_settings_view_recents_are_available_when_no_root_is_set(self) -> None:
        """Unset root is permissive: every recent stays openable so first-run
        isn't bricked (#441)."""
        ms.touch_recent_project(self.root / "anywhere", "Anywhere")
        recents = self.client.get("/api/settings/machine").json()["recent_projects"]
        self.assertTrue(all(r["within_root"] for r in recents))

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


class DisplaySettingsTests(unittest.TestCase):
    """Prose-presentation prefs (#127 / #575) — defaults, persistence, clamp."""

    def setUp(self) -> None:
        clear_test_scope()
        self.client = TestClient(app)

    def test_view_defaults_when_unset(self) -> None:
        display = self.client.get("/api/settings/machine").json()["display"]
        self.assertEqual(display, {"ui_scale": 1.0, "paragraph_align": "left", "paragraph_indent": False})

    def test_put_persists_display(self) -> None:
        body = {"display": {"ui_scale": 1.2, "paragraph_align": "justify", "paragraph_indent": True}}
        returned = self.client.put("/api/settings/machine", json=body)
        self.assertEqual(returned.status_code, 200, returned.text)
        self.assertEqual(returned.json()["display"], body["display"])
        # Survives a fresh load from disk.
        self.assertEqual(ms.load_settings().display.model_dump(), body["display"])

    def test_ui_scale_is_clamped_both_ends(self) -> None:
        hi = self.client.put("/api/settings/machine", json={"display": {"ui_scale": 5.0}}).json()
        self.assertEqual(hi["display"]["ui_scale"], 1.5)
        lo = self.client.put("/api/settings/machine", json={"display": {"ui_scale": 0.1}}).json()
        self.assertEqual(lo["display"]["ui_scale"], 0.85)

    def test_display_patch_leaves_other_settings_untouched(self) -> None:
        self.client.put("/api/settings/machine", json={"default_provider": "anthropic"})
        self.client.put("/api/settings/machine", json={"display": {"paragraph_indent": True}})
        settings = ms.load_settings()
        self.assertEqual(settings.default_provider, "anthropic")
        self.assertTrue(settings.display.paragraph_indent)

    def test_partial_display_patch_preserves_unset_nondefault_fields(self) -> None:
        # First store all-non-default display, then patch ONE field. The other
        # two must survive rather than reset to their defaults — this exercises
        # the exclude_unset recursion into the nested model, not just a no-op.
        self.client.put(
            "/api/settings/machine",
            json={"display": {"ui_scale": 1.3, "paragraph_align": "justify", "paragraph_indent": True}},
        )
        self.client.put("/api/settings/machine", json={"display": {"ui_scale": 1.1}})
        display = ms.load_settings().display
        self.assertEqual(display.ui_scale, 1.1)
        self.assertEqual(display.paragraph_align, "justify")  # not reset to "left"
        self.assertTrue(display.paragraph_indent)  # not reset to False


class AppWideAiPolicyTests(unittest.TestCase):
    """The application-global default AI policy (#746) — the chain's floor."""

    def setUp(self) -> None:
        clear_test_scope()
        self.client = TestClient(app)

    def test_view_defaults_off_when_unset(self) -> None:
        view = self.client.get("/api/settings/machine").json()
        self.assertEqual(view["ai_policy"], "off")

    def test_put_persists_ai_policy(self) -> None:
        returned = self.client.put("/api/settings/machine", json={"ai_policy": "cloud-allowed"})
        self.assertEqual(returned.status_code, 200, returned.text)
        self.assertEqual(returned.json()["ai_policy"], "cloud-allowed")
        # Survives a fresh load from disk.
        self.assertEqual(ms.load_settings().ai_policy, "cloud-allowed")

    def test_put_rejects_a_value_outside_the_policy_set(self) -> None:
        bad = self.client.put("/api/settings/machine", json={"ai_policy": "cloud_allowed"})
        self.assertEqual(bad.status_code, 422)

    def test_ai_policy_patch_leaves_other_settings_untouched(self) -> None:
        self.client.put("/api/settings/machine", json={"default_provider": "anthropic"})
        self.client.put("/api/settings/machine", json={"ai_policy": "local-only"})
        settings = ms.load_settings()
        self.assertEqual(settings.default_provider, "anthropic")
        self.assertEqual(settings.ai_policy, "local-only")


class DefaultAiPolicyReadTests(unittest.TestCase):
    """`default_ai_policy()` is the resolver's seed — a raw read that must not
    carry `load_settings()`'s side effects (#746, review finding)."""

    def _write_config(self, data: dict) -> None:
        path = ms.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def test_reads_the_stored_value(self) -> None:
        self._write_config({"ai_policy": "cloud-allowed"})
        self.assertEqual(ms.default_ai_policy(), "cloud-allowed")

    def test_defaults_off_when_unset_or_out_of_set(self) -> None:
        self.assertEqual(ms.default_ai_policy(), "off")  # no config file
        for bad in ({"ai_policy": "cloud_allowed"}, {"ai_policy": None}, {"ai_policy": 3}, {}):
            with self.subTest(config=bad):
                self._write_config(bad)
                self.assertEqual(ms.default_ai_policy(), "off")

    def test_default_ai_policy_reads_without_materializing_assistants(self) -> None:
        # default_ai_policy() reads the stored policy directly, never routing
        # through load_settings() — a read path must stay a pure read (the rule
        # projects_root() documents). With the auto-seed removed (#1413), neither
        # it nor load_settings() materializes assistant files.
        self._write_config({"ai_policy": "local-only", "default_models": {"ollama": "llama3.2"}})
        assistants = ms.assistants_dir()

        self.assertEqual(ms.default_ai_policy(), "local-only")
        self.assertFalse(
            assistants.exists() and any(assistants.glob("*.md")),
            "default_ai_policy() must not materialize assistant files",
        )

        # load_settings() no longer seeds a default roster either.
        ms.load_settings()
        self.assertFalse(assistants.exists() and any(assistants.glob("*.md")))


class TestRevealConfigDir:
    """The service reveal (#1749): create the dir, dispatch to the platform opener."""

    def test_opens_with_startfile_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "appdata"
        monkeypatch.setattr(ms, "config_dir", lambda: target)
        monkeypatch.setattr(ms.sys, "platform", "win32")
        opened: list[object] = []
        monkeypatch.setattr(ms.os, "startfile", opened.append, raising=False)

        ms.reveal_config_dir()

        assert target.exists()  # created if absent so a first-run reveal never fails
        assert opened == [target]

    @pytest.mark.parametrize(("platform", "opener"), [("linux", "xdg-open"), ("darwin", "open")])
    def test_opens_with_the_file_manager_on_posix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, opener: str
    ) -> None:
        target = tmp_path / "appdata"
        monkeypatch.setattr(ms, "config_dir", lambda: target)
        monkeypatch.setattr(ms.sys, "platform", platform)
        calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: calls.append((a, k)))

        ms.reveal_config_dir()

        assert target.exists()
        (args, kwargs), = calls
        assert args[0] == [opener, str(target)]
        assert kwargs["check"] is False  # a headless host must not raise


class TestRevealLogsRoute:
    """The route (#1749): loopback-only, else 403; never reveals for a remote caller."""

    @pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1"])
    def test_loopback_caller_reveals_and_returns_the_dir(
        self, monkeypatch: pytest.MonkeyPatch, host: str
    ) -> None:
        revealed: list[bool] = []
        monkeypatch.setattr(
            machine_settings_router.machine_settings_service,
            "reveal_config_dir",
            lambda: revealed.append(True),
        )
        monkeypatch.setattr(
            machine_settings_router.machine_settings_service, "config_dir", lambda: Path("/x/appdata")
        )
        request = SimpleNamespace(client=SimpleNamespace(host=host))

        result = machine_settings_router.reveal_logs(request)  # type: ignore[arg-type]

        assert revealed == [True]
        assert result["config_dir"] == str(Path("/x/appdata"))

    @pytest.mark.parametrize("host", ["192.168.1.7", "10.0.0.2", None])
    def test_remote_caller_is_refused_and_never_reveals(
        self, monkeypatch: pytest.MonkeyPatch, host: str | None
    ) -> None:
        called: list[bool] = []
        monkeypatch.setattr(
            machine_settings_router.machine_settings_service,
            "reveal_config_dir",
            lambda: called.append(True),
        )
        client = None if host is None else SimpleNamespace(host=host)
        request = SimpleNamespace(client=client)

        with pytest.raises(HTTPException) as exc:
            machine_settings_router.reveal_logs(request)  # type: ignore[arg-type]

        assert exc.value.status_code == 403
        assert called == []  # the reveal never ran for a non-local caller


if __name__ == "__main__":
    unittest.main()
