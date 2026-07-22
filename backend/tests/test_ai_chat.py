from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
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
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Chat Tests")
        self.client = TestClient(app)
        # Isolate the file-backed assistant store so the chat resolver
        # doesn't pick up the developer's real ~/AppData entries.
        self.config_dir = Path(self.temp_dir.name).resolve() / "machine_config"
        self.config_dir.mkdir()
        self._config_patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._config_patcher.start()

    def tearDown(self) -> None:
        self._config_patcher.stop()
        self.temp_dir.cleanup()

    def _allow_cloud(self) -> None:
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )

    def _allow_local_only(self) -> None:
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="local-only")
        )

    # ---- happy path ----

    def test_anthropic_chat_returns_assistant_reply(self) -> None:
        self._allow_cloud()
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat", return_value=("Hello back.", "end_turn", SimpleNamespace())):
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
                return_value=("Local reply.", "stop", SimpleNamespace()),
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
                return_value=("Third reply.", "end_turn", SimpleNamespace()),
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
                return_value=("OK.", "stop", SimpleNamespace()),
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
                return_value=("partial response that hit the cap", "max_tokens", SimpleNamespace()),
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
                return_value=("complete reply", "end_turn", SimpleNamespace()),
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
                return_value=("default-provider reply", "stop", SimpleNamespace()),
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


class ChatStreamEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Stream Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name).resolve() / "machine_config"
        self.config_dir.mkdir()
        self._config_patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._config_patcher.start()

    def tearDown(self) -> None:
        self._config_patcher.stop()
        self.temp_dir.cleanup()

    def _parse_ndjson(self, body: str) -> list[dict]:
        import json
        events = []
        for line in body.splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events

    def test_chat_stream_emits_deltas_then_done(self) -> None:
        from app.services.ai import providers as ai_providers
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")

        def fake_anthropic_stream(**_kwargs):
            yield ai_providers.StreamDelta(text="Hello, ")
            yield ai_providers.StreamDelta(text="world!")
            yield ai_providers._StreamFinal(stop_reason="end_turn")

        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat_stream", side_effect=fake_anthropic_stream):
            response = self.client.post(
                "/api/ai/chat/stream",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("application/x-ndjson"))
        events = self._parse_ndjson(response.text)
        deltas = [e for e in events if e["type"] == "delta"]
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual([d["text"] for d in deltas], ["Hello, ", "world!"])
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["provider"], "anthropic")
        self.assertEqual(done[0]["stop_reason"], "end_turn")
        self.assertFalse(done[0]["truncated"])
        self.assertEqual(done[0]["policy"], "cloud-allowed")

    def test_chat_stream_policy_off_emits_error(self) -> None:
        # default project policy is "off"
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat_stream") as mock_stream:
            response = self.client.post(
                "/api/ai/chat/stream",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        events = self._parse_ndjson(response.text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("policy: off", events[0]["error"])
        mock_stream.assert_not_called()

    def test_chat_stream_anthropic_thinking_events(self) -> None:
        from app.services.ai import providers as ai_providers
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        loaded = _set_machine_keys(anthropic="sk-ant-test")

        def fake_stream(**_kwargs):
            yield ai_providers.StreamThinking(text="Let me think… ")
            yield ai_providers.StreamThinking(text="OK.")
            yield ai_providers.StreamDelta(text="Hi!")
            yield ai_providers._StreamFinal(stop_reason="end_turn")

        # Create an assistant with ai_thinking enabled so the resolver
        # plumbs thinking_enabled=True. The provider mock doesn't care, but
        # this exercises the param wiring.
        from app.models import CreateAssistantEntryRequest, SaveAssistantEntryRequest
        created = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title="Thinker", entry_type="assistant:assistant")
        )
        self.service.save_assistant_entry(
            created.id,
            SaveAssistantEntryRequest(
                title="Thinker",
                base_revision=created.revision,
                entry_type="assistant:assistant",
                metadata={
                    "ai_provider": "anthropic",
                    "ai_model": "claude-haiku-4-5-20251001",
                    "ai_thinking": True,
                },
            ),
        )

        captured: dict = {}

        def capture_and_stream(**kwargs):
            captured.update(kwargs)
            yield from fake_stream(**kwargs)

        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat_stream", side_effect=capture_and_stream):
            response = self.client.post(
                "/api/ai/chat/stream",
                json={
                    "assistant_id": created.id,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(captured.get("thinking_enabled"))
        events = self._parse_ndjson(response.text)
        thinking = [e for e in events if e["type"] == "thinking"]
        deltas = [e for e in events if e["type"] == "delta"]
        self.assertEqual([t["text"] for t in thinking], ["Let me think… ", "OK."])
        self.assertEqual([d["text"] for d in deltas], ["Hi!"])

    def test_chat_stream_truncated_when_stop_reason_is_max_tokens(self) -> None:
        from app.services.ai import providers as ai_providers
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        loaded = _set_machine_keys(anthropic="sk-ant-test")

        def fake_stream(**_kwargs):
            yield ai_providers.StreamDelta(text="partial")
            yield ai_providers._StreamFinal(stop_reason="max_tokens")

        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch("app.services.ai.providers._anthropic_chat_stream", side_effect=fake_stream):
            response = self.client.post(
                "/api/ai/chat/stream",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "go"}],
                },
            )
        events = self._parse_ndjson(response.text)
        done = next(e for e in events if e["type"] == "done")
        self.assertTrue(done["truncated"])
        self.assertEqual(done["stop_reason"], "max_tokens")


class ChatEndpointJournalTests(unittest.TestCase):
    """End-to-end exercise of the implicit-context journal on chat send.

    Creates a project with lore wired so Honor's body textually mentions
    Pavel (depth-1 expansion target), starts a chat, and posts a message
    that triggers detection. Verifies the journal gets appended, the
    provider receives system_blocks with the lore XML, and journal_added
    surfaces on the response for the audit UI.
    """

    def setUp(self) -> None:
        from app.models import (
            CreateChatSessionRequest,
            CreateLoreEntryRequest,
            SaveLoreEntryRequest,
        )
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Journal Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name).resolve() / "machine_config"
        self.config_dir.mkdir()
        self._config_patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._config_patcher.start()

        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )

        # Lore: Honor (with alias) → body mentions Pavel (depth-1); Nimitz unrelated.
        honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
        )
        nimitz = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Nimitz", entry_type="lore:character")
        )
        pavel = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Pavel Young", entry_type="lore:character")
        )

        def _save(entry_id: str, metadata: dict, body: str) -> None:
            existing = self.service.read_lore_entry(entry_id)
            self.service.save_lore_entry(
                entry_id,
                SaveLoreEntryRequest(
                    title=existing.title, body=body,
                    base_revision=existing.revision, entry_type="lore:character",
                    metadata=metadata,
                ),
            )

        _save(honor.id, {"aliases": ["Honor"]}, "Captain of the Fearless. Rival of Pavel Young.")
        _save(nimitz.id, {"aliases": []}, "Treecat.")
        _save(pavel.id, {"aliases": []}, "Disgraced Captain.")
        self.honor_id = honor.id
        self.nimitz_id = nimitz.id
        self.pavel_id = pavel.id

        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="Test", prompt_entry_id="prompt_x")
        )
        self.chat_id = chat.id

    def tearDown(self) -> None:
        self._config_patcher.stop()
        self.temp_dir.cleanup()

    def test_chat_send_appends_to_journal_and_passes_system_blocks(self) -> None:
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("Reply.", "end_turn", SimpleNamespace()),
             ) as mock_chat:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "system_prompt": "You are a writing assistant.",
                    "messages": [{"role": "user", "content": "Honor walked in."}],
                    "chat_id": self.chat_id,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])

        # journal_added must include both the direct hit and the depth-1
        # expansion. Entries are full snapshots with title + source.
        added_ids = {e["entry_id"] for e in body["journal_added"]}
        self.assertIn(self.honor_id, added_ids)
        self.assertIn(self.pavel_id, added_ids)
        self.assertNotIn(self.nimitz_id, added_ids)
        honor_entry = next(e for e in body["journal_added"] if e["entry_id"] == self.honor_id)
        pavel_entry = next(e for e in body["journal_added"] if e["entry_id"] == self.pavel_id)
        self.assertEqual(honor_entry["title"], "Honor Harrington")
        self.assertEqual(honor_entry["source"], "user_message")
        self.assertEqual(pavel_entry["source"], "depth1_expansion")

        # Persisted chat journal mirrors what was added.
        chat = self.service.read_chat_session(self.chat_id)
        journal_ids = [e.entry_id for e in chat.journal]
        self.assertIn(self.honor_id, journal_ids)
        self.assertIn(self.pavel_id, journal_ids)

        # Provider received system_blocks: slot 1 = system_prompt (1h),
        # slot 2 = journal XML (5m).
        kwargs = mock_chat.call_args.kwargs
        blocks = kwargs["system_blocks"]
        self.assertIsNotNone(blocks)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["text"], "You are a writing assistant.")
        self.assertEqual(blocks[0]["ttl"], "1h")
        self.assertIn("Honor Harrington", blocks[1]["text"])
        self.assertIn("Pavel Young", blocks[1]["text"])
        self.assertEqual(blocks[1]["ttl"], "5m")

    def test_no_chat_id_skips_journal_path(self) -> None:
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("Reply.", "end_turn", SimpleNamespace()),
             ) as mock_chat:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "system_prompt": "You are helpful.",
                    "messages": [{"role": "user", "content": "Honor walked in."}],
                    # No chat_id — legacy path
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["journal_added"], [])
        # Legacy path: system_blocks not passed.
        kwargs = mock_chat.call_args.kwargs
        self.assertIsNone(kwargs.get("system_blocks"))
        self.assertIsNone(kwargs.get("session_id"))

    def test_journal_is_append_only_across_turns(self) -> None:
        # Turn 1: user mentions Honor → Honor + Pavel added.
        loaded = _set_machine_keys(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("OK.", "end_turn", SimpleNamespace()),
             ):
            self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "Honor stepped onto the bridge."}],
                    "chat_id": self.chat_id,
                },
            )
        first = self.service.read_chat_session(self.chat_id)
        first_ids = {e.entry_id for e in first.journal}
        self.assertIn(self.honor_id, first_ids)

        # Turn 2: user mentions Nimitz → Nimitz added; Honor NOT re-added.
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("OK.", "end_turn", SimpleNamespace()),
             ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [
                        {"role": "user", "content": "Honor stepped onto the bridge."},
                        {"role": "assistant", "content": "OK."},
                        {"role": "user", "content": "What about Nimitz?"},
                    ],
                    "chat_id": self.chat_id,
                },
            )
        added_ids = {e["entry_id"] for e in response.json()["journal_added"]}
        self.assertIn(self.nimitz_id, added_ids)
        self.assertNotIn(self.honor_id, added_ids)  # dedup against existing journal
        second = self.service.read_chat_session(self.chat_id)
        second_ids = [e.entry_id for e in second.journal]
        # All first-turn entries preserved + new ones appended (order stable).
        for eid in first_ids:
            self.assertIn(eid, second_ids)
        self.assertIn(self.nimitz_id, second_ids)


if __name__ == "__main__":
    unittest.main()
