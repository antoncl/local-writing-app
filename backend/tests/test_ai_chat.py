from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, service as global_service
from app.models import UpdateProjectSettingsRequest


def _set_machine_keys(**keys: str) -> None:
    """Patch the loaded machine settings for a single test."""
    from app.services import machine_settings as ms

    settings = ms.MachineSettings(
        providers=ms.ProviderCredentials(
            anthropic_api_key=keys.get("anthropic", ""),
            openai_api_key=keys.get("openai", ""),
            openrouter_api_key=keys.get("openrouter", ""),
            ollama_host=keys.get("ollama_host", "http://127.0.0.1:11434"),
        ),
        default_provider=keys.get("default_provider", "ollama"),
    )
    return settings


class ChatEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Chat Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _allow_cloud(self) -> None:
        global_service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )

    def _allow_local_only(self) -> None:
        global_service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="local-only")
        )

    # ---- happy path ----

    def test_anthropic_chat_returns_assistant_reply(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat", return_value=("Hello back.", "end_turn")):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "system_prompt": "You are helpful.",
                    "messages": [{"role": "user", "content": "Hello?"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["role"], "assistant")
        self.assertEqual(body["content"], "Hello back.")
        self.assertEqual(body["provider"], "anthropic")
        self.assertEqual(body["policy"], "cloud-allowed")
        self.assertIsNone(body["error"])

    def test_ollama_chat_uses_openai_compatible_path(self) -> None:
        self._allow_local_only()
        loaded = _set_machine_keys(default_provider="ollama")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._openai_compatible_chat",
                return_value=("Local reply.", "stop"),
            ) as mock_chat:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "ollama",
                    "model": "llama3.2",
                    "system_prompt": "Be terse.",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["content"], "Local reply.")
        # Verify the call used Ollama's base URL
        kwargs = mock_chat.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "http://127.0.0.1:11434/v1")
        self.assertFalse(kwargs["requires_key"])

    def test_multi_turn_messages_passed_through(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("Third reply.", "end_turn"),
            ) as mock_chat:
            self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "system_prompt": "Continue the conversation.",
                    "messages": [
                        {"role": "user", "content": "First"},
                        {"role": "assistant", "content": "Second"},
                        {"role": "user", "content": "Third?"},
                    ],
                },
            )
        passed_messages = mock_chat.call_args.kwargs["messages"]
        self.assertEqual(len(passed_messages), 3)
        self.assertEqual(passed_messages[0]["role"], "user")
        self.assertEqual(passed_messages[1]["role"], "assistant")
        self.assertEqual(passed_messages[2]["content"], "Third?")
        self.assertEqual(mock_chat.call_args.kwargs["system_prompt"], "Continue the conversation.")

    # ---- policy enforcement ----

    def test_policy_off_blocks_everything(self) -> None:
        # Default project policy is "off".
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat") as mock_chat:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("policy: off", body["error"])
        mock_chat.assert_not_called()

    def test_policy_local_only_blocks_cloud(self) -> None:
        self._allow_local_only()
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat") as mock_chat:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("local-only", body["error"])
        mock_chat.assert_not_called()

    def test_policy_local_only_allows_ollama(self) -> None:
        self._allow_local_only()
        loaded = _set_machine_keys(default_provider="ollama")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._openai_compatible_chat",
                return_value=("OK.", "stop"),
            ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "ollama",
                    "model": "llama3.2",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertTrue(response.json()["ok"])

    # ---- error paths ----

    def test_missing_api_key_returns_error(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys()  # no anthropic key
        with patch("app.services.machine_settings.load_settings", return_value=loaded):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("API key", body["error"])

    def test_empty_messages_rejected(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        with patch("app.services.machine_settings.load_settings", return_value=loaded):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [],
                },
            )
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("messages must not be empty", body["error"])

    def test_unknown_provider_returns_error(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys()
        with patch("app.services.machine_settings.load_settings", return_value=loaded):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "fictional",
                    "model": "x",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("Unknown provider", body["error"])

    def test_truncated_flag_set_when_stop_reason_is_max_tokens(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("partial response that hit the cap", "max_tokens"),
            ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "Write something long."}],
                },
            )
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["truncated"])
        self.assertEqual(body["stop_reason"], "max_tokens")

    def test_truncated_false_on_normal_stop(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("complete reply", "end_turn"),
            ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        body = response.json()
        self.assertFalse(body["truncated"])
        self.assertEqual(body["stop_reason"], "end_turn")

    def test_provider_defaults_from_machine_settings(self) -> None:
        self._allow_local_only()
        loaded = _set_machine_keys(default_provider="ollama")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._openai_compatible_chat",
                return_value=("default-provider reply", "stop"),
            ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    # No provider specified — should fall back to default_provider
                    "model": "llama3.2",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["provider"], "ollama")


if __name__ == "__main__":
    unittest.main()
