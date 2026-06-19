from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, service as global_service
from app.models import UpdateProjectSettingsRequest
from app.services import machine_settings as ms


class AssistantMigrationTests(unittest.TestCase):
    """Backfill: when a user upgrades and has default_models but no
    assistants, the loader generates one assistant per (provider, model)
    pair and picks a default matching the existing default_provider."""

    def test_backfill_creates_one_assistant_per_default_model_pair(self) -> None:
        settings = ms.MachineSettings(
            default_provider="anthropic",
            default_models={
                "anthropic": "claude-haiku-4-5-20251001",
                "openai": "gpt-4o-mini",
                "openrouter": "anthropic/claude-haiku-4.5",
                "ollama": "",  # empty pairs are skipped
            },
            assistants=[],
            default_assistant_id="",
        )
        result = ms._backfill_assistants(settings)

        providers = {a.provider for a in result.assistants}
        self.assertEqual(providers, {"anthropic", "openai", "openrouter"})
        self.assertEqual(len(result.assistants), 3)
        anthropic_assistant = next(a for a in result.assistants if a.provider == "anthropic")
        self.assertIn("claude-haiku", anthropic_assistant.model)
        self.assertEqual(result.default_assistant_id, anthropic_assistant.id)

    def test_backfill_no_op_when_roster_already_populated(self) -> None:
        existing = ms.Assistant(
            id="my-pick",
            name="My handcrafted assistant",
            provider="anthropic",
            model="claude-sonnet-4-6",
            temperature=0.3,
            max_tokens=2048,
        )
        settings = ms.MachineSettings(
            default_provider="anthropic",
            default_models={"anthropic": "claude-haiku-4-5-20251001"},
            assistants=[existing],
            default_assistant_id="my-pick",
        )
        result = ms._backfill_assistants(settings)
        self.assertEqual(len(result.assistants), 1)
        self.assertEqual(result.assistants[0].id, "my-pick")
        self.assertEqual(result.default_assistant_id, "my-pick")

    def test_backfill_repairs_orphan_default_assistant_id(self) -> None:
        """If default_assistant_id references a now-deleted id, fall back to
        the first assistant in the roster."""
        existing = ms.Assistant(
            id="kept",
            name="Kept",
            provider="anthropic",
            model="claude-sonnet-4-6",
        )
        settings = ms.MachineSettings(
            assistants=[existing],
            default_assistant_id="vanished",
        )
        result = ms._backfill_assistants(settings)
        self.assertEqual(result.default_assistant_id, "kept")


class ResolveAssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = ms.MachineSettings(
            default_provider="anthropic",
            assistants=[
                ms.Assistant(id="a", name="A", provider="anthropic", model="m-a", temperature=0.3),
                ms.Assistant(id="b", name="B", provider="ollama", model="m-b", temperature=0.9),
            ],
            default_assistant_id="b",
        )

    def test_resolve_by_id(self) -> None:
        result = ms.resolve_assistant(self.settings, "a")
        assert result is not None
        self.assertEqual(result.id, "a")

    def test_resolve_falls_back_to_default(self) -> None:
        result = ms.resolve_assistant(self.settings, None)
        assert result is not None
        self.assertEqual(result.id, "b")

    def test_resolve_returns_none_for_unknown_id(self) -> None:
        # No fallback: a request that names a missing assistant gets None,
        # the endpoint surfaces this as the legacy default_provider path.
        result = ms.resolve_assistant(self.settings, "ghost")
        self.assertIsNone(result)


class ChatEndpointAssistantTests(unittest.TestCase):
    """Endpoint layer: assistant_id resolves to the assistant's params;
    explicit fields on the request override the assistant."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Assistant Tests")
        global_service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        self.client = TestClient(app)
        self.settings = ms.MachineSettings(
            providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
            default_provider="anthropic",
            default_models={"anthropic": "claude-haiku-4-5-20251001"},
            assistants=[
                ms.Assistant(
                    id="creative",
                    name="Creative drafting",
                    provider="anthropic",
                    model="claude-sonnet-4-6",
                    temperature=0.9,
                    max_tokens=2048,
                ),
                ms.Assistant(
                    id="cheap",
                    name="Cheap summary",
                    provider="anthropic",
                    model="claude-haiku-4-5-20251001",
                    temperature=0.2,
                    max_tokens=512,
                ),
            ],
            default_assistant_id="cheap",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_assistant_id_resolves_provider_model_temperature(self) -> None:
        with patch("app.services.machine_settings.load_settings", return_value=self.settings), \
             patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn")) as mock:
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
        with patch("app.services.machine_settings.load_settings", return_value=self.settings), \
             patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn")) as mock:
            response = self.client.post(
                "/api/ai/chat",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = mock.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(kwargs["temperature"], 0.2)

    def test_explicit_model_overrides_assistant(self) -> None:
        with patch("app.services.machine_settings.load_settings", return_value=self.settings), \
             patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn")) as mock:
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


class MachineSettingsRoundTripTests(unittest.TestCase):
    """Settings API round-trips assistants + default_assistant_id."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Settings Tests")
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

    def test_put_round_trips_assistants(self) -> None:
        put = self.client.put(
            "/api/settings/machine",
            json={
                "assistants": [
                    {
                        "id": "main",
                        "name": "Main",
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-6",
                        "temperature": 0.5,
                        "max_tokens": 4096,
                    }
                ],
                "default_assistant_id": "main",
            },
        )
        self.assertEqual(put.status_code, 200, put.text)
        get = self.client.get("/api/settings/machine")
        body = get.json()
        self.assertEqual(len(body["assistants"]), 1)
        self.assertEqual(body["assistants"][0]["id"], "main")
        self.assertEqual(body["default_assistant_id"], "main")


class FileBackedAssistantsTests(unittest.TestCase):
    """Slice A: assistants now live as Node-style markdown files in the
    machine config dir (and ancestor / project layers). The inline
    settings.assistants list mirrors the file index on load."""

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

    def test_save_then_load_round_trips_via_files(self) -> None:
        """PUT writes assistant files to disk; subsequent GET reads them back."""
        put = self.client.put(
            "/api/settings/machine",
            json={
                "assistants": [
                    {
                        "id": "creative",
                        "name": "Creative drafting",
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-6",
                        "temperature": 0.9,
                        "max_tokens": 4096,
                    },
                    {
                        "id": "cheap",
                        "name": "Cheap summary",
                        "provider": "anthropic",
                        "model": "claude-haiku-4-5-20251001",
                        "temperature": 0.2,
                        "max_tokens": 512,
                    },
                ],
                "default_assistant_id": "creative",
            },
        )
        self.assertEqual(put.status_code, 200, put.text)

        assistants_dir = self.config_dir / "assistants"
        self.assertTrue((assistants_dir / "creative.md").exists())
        self.assertTrue((assistants_dir / "cheap.md").exists())

        # Verify is_default lives in the metadata of the right file.
        creative_text = (assistants_dir / "creative.md").read_text(encoding="utf-8")
        self.assertIn("is_default: true", creative_text)
        cheap_text = (assistants_dir / "cheap.md").read_text(encoding="utf-8")
        self.assertNotIn("is_default: true", cheap_text)

        get = self.client.get("/api/settings/machine")
        body = get.json()
        ids = {a["id"] for a in body["assistants"]}
        self.assertEqual(ids, {"creative", "cheap"})
        self.assertEqual(body["default_assistant_id"], "creative")

    def test_files_override_inline_yaml_list(self) -> None:
        """If the user hand-edits config.yaml's inline list but files exist,
        the file index wins (single source of truth)."""
        assistants_dir = self.config_dir / "assistants"
        assistants_dir.mkdir(parents=True)
        (assistants_dir / "from-disk.md").write_text(
            "---\n"
            "id: from-disk\n"
            "title: From disk\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: ollama\n"
            "  ai_model: llama3.2\n"
            "  ai_temperature: 0.3\n"
            "  ai_max_tokens: 1024\n"
            "  is_default: true\n"
            "---\n",
            encoding="utf-8",
        )
        (self.config_dir / "config.yaml").write_text(
            "version: 1\n"
            "default_provider: anthropic\n"
            "default_models: {}\n"
            "assistants:\n"
            "  - id: only-inline\n"
            "    name: Only inline\n"
            "    provider: anthropic\n"
            "    model: claude-sonnet-4-6\n"
            "    temperature: 0.7\n"
            "    max_tokens: 4096\n"
            "default_assistant_id: only-inline\n",
            encoding="utf-8",
        )

        get = self.client.get("/api/settings/machine")
        body = get.json()

        # The file wins.
        self.assertEqual([a["id"] for a in body["assistants"]], ["from-disk"])
        self.assertEqual(body["default_assistant_id"], "from-disk")
        self.assertEqual(body["assistants"][0]["temperature"], 0.3)

    def test_assistant_index_includes_machine_layer(self) -> None:
        """Project-scoped reads (e.g. /api/assistants) see the machine
        layer's assistants."""
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
        # The machine layer carries a stable label.
        fleet = next(a for a in body["entries"] if a["id"] == "fleet")
        self.assertEqual(fleet["source_layer_label"], "Machine")

    def test_create_assistant_endpoint_lands_in_machine_layer(self) -> None:
        """POST without a layer_id lands in the machine config dir."""
        create = self.client.post(
            "/api/assistants",
            json={"title": "New one", "entry_type": "assistant"},
        )
        self.assertEqual(create.status_code, 200, create.text)
        entry = create.json()
        self.assertTrue(entry["id"].startswith("assistant_"))
        self.assertEqual(entry["source_layer_label"], "Machine")

        # File is on disk under the patched assistants dir.
        files = list((self.config_dir / "assistants").glob("*.md"))
        self.assertEqual(len(files), 1)


if __name__ == "__main__":
    unittest.main()
