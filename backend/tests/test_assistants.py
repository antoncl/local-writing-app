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


if __name__ == "__main__":
    unittest.main()
