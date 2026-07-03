from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as global_service
from app.models import UpdateProjectSettingsRequest
from app.services import machine_settings as ms


class MigrateDefaultModelsTests(unittest.TestCase):
    """On first load after upgrade, the loader writes one assistant file per
    non-empty (provider, model) pair in default_models, then leaves them
    alone on subsequent loads."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_first_load_writes_one_file_per_pair(self) -> None:
        ms.load_settings()
        folder = self.config_dir / "assistants"
        files = sorted(p.name for p in folder.glob("*.md"))
        self.assertEqual(len(files), 4)  # one per DEFAULT_MODELS entry
        # The ★ is_default flag is retired (ADR-0024) — no file carries it; the
        # default_provider (ollama) assistant is instead seeded first so it is
        # the topmost (dynamic default) row.
        for p in folder.glob("*.md"):
            self.assertNotIn("is_default", p.read_text(encoding="utf-8"))

    def test_subsequent_load_is_a_no_op(self) -> None:
        ms.load_settings()
        # Sentinel file to prove migration won't re-run.
        sentinel = self.config_dir / "assistants" / "sentinel.md"
        sentinel.write_text("placeholder", encoding="utf-8")
        ms.load_settings()
        self.assertTrue(sentinel.exists())
        # No additional .md files appeared.
        self.assertEqual(len(list((self.config_dir / "assistants").glob("*.md"))), 5)

    def test_empty_default_models_writes_nothing(self) -> None:
        settings = ms.MachineSettings(default_models={})
        ms.save_settings(settings)
        ms.load_settings()
        self.assertFalse((self.config_dir / "assistants").exists())


class ProjectServiceResolveAssistantTests(unittest.TestCase):
    """ProjectService.resolve_assistant reads the file-backed index and
    returns the AssistantEntry whose id matches (or the topmost in roster
    order when no id is passed — the ★ is_default flag is retired, ADR-0024)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        (folder / "creative.md").write_text(
            "---\n"
            "id: creative\n"
            "title: Creative\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-sonnet-4-6\n"
            "  ai_temperature: 0.9\n"
            "  ai_max_tokens: 4096\n"
            "---\n",
            encoding="utf-8",
        )
        (folder / "cheap.md").write_text(
            "---\n"
            "id: cheap\n"
            "title: Cheap\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-haiku-4-5-20251001\n"
            "  ai_temperature: 0.2\n"
            "---\n",
            encoding="utf-8",
        )
        global_service.__init__()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_resolve_by_id(self) -> None:
        result = global_service.resolve_assistant("cheap")
        assert result is not None
        self.assertEqual(result.id, "cheap")
        self.assertEqual(result.metadata["ai_model"], "claude-haiku-4-5-20251001")

    def test_resolve_falls_back_to_topmost(self) -> None:
        # No id → topmost in roster order. With no per-layer .order.yaml the
        # roster sorts by title, so "Cheap" precedes "Creative".
        result = global_service.resolve_assistant(None)
        assert result is not None
        self.assertEqual(result.id, "cheap")

    def test_resolve_returns_none_for_unknown_id(self) -> None:
        result = global_service.resolve_assistant("ghost")
        self.assertIsNone(result)


class ChatEndpointAssistantTests(unittest.TestCase):
    """Endpoint layer: assistant_id resolves to the assistant's params via
    the file-backed roster; explicit request fields still override."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Assistant Tests")
        global_service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        (folder / "creative.md").write_text(
            "---\n"
            "id: creative\n"
            "title: Creative drafting\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-sonnet-4-6\n"
            "  ai_temperature: 0.9\n"
            "  ai_max_tokens: 2048\n"
            "---\n",
            encoding="utf-8",
        )
        (folder / "cheap.md").write_text(
            "---\n"
            "id: cheap\n"
            "title: Cheap summary\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-haiku-4-5-20251001\n"
            "  ai_temperature: 0.2\n"
            "  ai_max_tokens: 512\n"
            "---\n",
            encoding="utf-8",
        )
        # Seed machine settings with the api key.
        ms.save_settings(
            ms.MachineSettings(
                providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
                default_provider="anthropic",
                default_models={"anthropic": "claude-haiku-4-5-20251001"},
            )
        )

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_assistant_id_resolves_provider_model_temperature(self) -> None:
        with patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn", SimpleNamespace())) as mock:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "assistant_id": "creative",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = mock.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-sonnet-4-6")
        self.assertEqual(kwargs["temperature"], 0.9)
        self.assertEqual(kwargs["max_tokens"], 2048)

    def test_default_assistant_used_when_no_id_supplied(self) -> None:
        with patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn", SimpleNamespace())) as mock:
            response = self.client.post(
                "/api/ai/chat",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = mock.call_args.kwargs
        # No id → topmost by title ("Cheap summary" < "Creative drafting").
        self.assertEqual(kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(kwargs["temperature"], 0.2)

    def test_explicit_model_overrides_assistant(self) -> None:
        with patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn", SimpleNamespace())) as mock:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "assistant_id": "creative",
                    "model": "claude-opus-4-8",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = mock.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-4-8")
        # Temperature still comes from the assistant — there's no override
        # field for it on the request shape (intentional; per-call temp tweaks
        # are a future enhancement).
        self.assertEqual(kwargs["temperature"], 0.9)


class MachineSettingsViewTests(unittest.TestCase):
    """The Slice D MachineSettingsView no longer exposes assistants or
    default_assistant_id — they moved entirely to the file-backed roster."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "View Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_get_does_not_expose_inline_assistants(self) -> None:
        body = self.client.get("/api/settings/machine").json()
        self.assertNotIn("assistants", body)
        self.assertNotIn("default_assistant_id", body)

    def test_put_ignores_legacy_assistants_payload(self) -> None:
        # The PUT silently drops unknown fields (FastAPI / Pydantic strict
        # validation would reject; the model declares only the kept fields).
        # We send a known-good provider patch alongside an obsolete assistants
        # payload and confirm the obsolete one has no effect.
        put = self.client.put(
            "/api/settings/machine",
            json={
                "default_provider": "anthropic",
                "assistants": [{"id": "x", "name": "X", "provider": "anthropic", "model": "m"}],
            },
        )
        self.assertEqual(put.status_code, 200, put.text)
        body = put.json()
        self.assertEqual(body["default_provider"], "anthropic")
        self.assertNotIn("assistants", body)


class FileBackedAssistantsTests(unittest.TestCase):
    """Slice A surface that survives Slice D: the file-backed assistants
    pane endpoint."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Files Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_assistant_index_includes_machine_layer(self) -> None:
        assistants_dir = self.config_dir / "assistants"
        assistants_dir.mkdir(parents=True)
        (assistants_dir / "fleet.md").write_text(
            "---\n"
            "id: fleet\n"
            "title: Fleet drafting\n"
            "entry_type: assistant\n"
            "metadata: { ai_provider: anthropic, ai_model: claude-sonnet-4-6 }\n"
            "---\n",
            encoding="utf-8",
        )
        response = self.client.get("/api/assistants")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        ids = [a["id"] for a in body["entries"]]
        self.assertIn("fleet", ids)
        fleet = next(a for a in body["entries"] if a["id"] == "fleet")
        self.assertEqual(fleet["source_layer_label"], "Machine")

    def test_create_assistant_endpoint_lands_in_machine_layer(self) -> None:
        create = self.client.post(
            "/api/assistants",
            json={"title": "New one", "entry_type": "assistant:assistant"},
        )
        self.assertEqual(create.status_code, 200, create.text)
        entry = create.json()
        self.assertTrue(entry["id"].startswith("assistant_"))
        self.assertEqual(entry["source_layer_label"], "Machine")
        files = list((self.config_dir / "assistants").glob("*.md"))
        self.assertEqual(len(files), 1)


class AssistantReorderTests(unittest.TestCase):
    """Slice C: per-layer assistants/.order.yaml drives list ordering;
    /api/assistants/order writes it."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Reorder Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        # Seed three machine-layer assistants.
        assistants_dir = self.config_dir / "assistants"
        assistants_dir.mkdir(parents=True)
        for slug in ("alpha", "bravo", "charlie"):
            (assistants_dir / f"{slug}.md").write_text(
                f"---\nid: {slug}\ntitle: {slug.capitalize()}\nentry_type: assistant\nmetadata: {{ ai_provider: anthropic, ai_model: m }}\n---\n",
                encoding="utf-8",
            )
        self.machine_layer_id = global_service._metadata_schema_layer_id(self.config_dir)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_default_order_is_alphabetical(self) -> None:
        response = self.client.get("/api/assistants")
        ids = [e["id"] for e in response.json()["entries"]]
        self.assertEqual(ids, ["alpha", "bravo", "charlie"])

    def test_reorder_endpoint_writes_order_file(self) -> None:
        response = self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["charlie", "alpha"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        order_file = self.config_dir / "assistants" / ".order.yaml"
        self.assertTrue(order_file.exists())
        ids = [e["id"] for e in response.json()["entries"]]
        self.assertEqual(ids, ["charlie", "alpha", "bravo"])

    def test_reorder_with_unknown_id_returns_422(self) -> None:
        response = self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["alpha", "ghost"]},
        )
        self.assertEqual(response.status_code, 422)

    def test_subsequent_get_respects_saved_order(self) -> None:
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["bravo", "charlie", "alpha"]},
        )
        response = self.client.get("/api/assistants")
        ids = [e["id"] for e in response.json()["entries"]]
        self.assertEqual(ids, ["bravo", "charlie", "alpha"])


if __name__ == "__main__":
    unittest.main()
