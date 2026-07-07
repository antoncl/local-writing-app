from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CreateStructureNodeRequest,
    SaveSceneRequest,
    UpdateProjectSettingsRequest,
)
from app.runtime import service as global_service
from app.services.ai.sessions import default_registry


def _settings(**keys: str):
    from app.services import machine_settings as ms

    return ms.MachineSettings(
        providers=ms.ProviderCredentials(
            anthropic_api_key=keys.get("anthropic", ""),
            openai_api_key=keys.get("openai", ""),
            openrouter_api_key=keys.get("openrouter", ""),
            ollama_host=keys.get("ollama_host", "http://127.0.0.1:11434"),
        ),
        default_provider=keys.get("default_provider", "ollama"),
    )


class GenerateEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Generate Tests")
        default_registry.clear()
        self.client = TestClient(app)

        # Minimal scene with a summary
        structure = global_service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_node = next(c for c in structure.root.children if c.type == "scene:act")
        s = global_service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="scene:scene", parent_id=act_node.id
            )
        )
        # Re-find the act with its children populated
        act_after = next(c for c in s.root.children if c.id == act_node.id)
        self.scene_id = act_after.children[-1].scene_id

        scene = global_service.read_scene(self.scene_id)
        global_service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body="Scene body.",
                base_revision=scene.revision,
                status="draft",
                entry_type="scene:scene",
                metadata={"summary": "Honor takes the Salamander into battle."},
            ),
        )

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _allow_cloud(self) -> None:
        global_service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )

    def test_generate_sends_rendered_payload_to_provider(self) -> None:
        self._allow_cloud()
        settings = _settings(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=settings), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("Generated continuation.", "end_turn", SimpleNamespace()),
            ) as mock_chat:
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": (
                        '{% role "system" %}You are a writer.{% endrole %}'
                        '{% role "user" %}Continue: {{ scene.title }}{% endrole %}'
                    ),
                    "target_scene_id": self.scene_id,
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["content"], "Generated continuation.")
        # System prompt was extracted from system message
        kwargs = mock_chat.call_args.kwargs
        self.assertEqual(kwargs["system_prompt"], "You are a writer.")
        # User message was passed through with rendered content
        self.assertEqual(len(kwargs["messages"]), 1)
        self.assertEqual(kwargs["messages"][0]["role"], "user")
        self.assertEqual(kwargs["messages"][0]["content"], "Continue: The Departure")
        # Response echoes the rendered messages so the UI can show them
        self.assertEqual(len(body["rendered_messages"]), 2)

    def test_multi_role_payload_threads_user_assistant_alternation(self) -> None:
        self._allow_cloud()
        settings = _settings(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=settings), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("OK", "end_turn", SimpleNamespace()),
            ) as mock_chat:
            self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": (
                        '{% role "system" %}sys{% endrole %}'
                        '{% role "user" %}first{% endrole %}'
                        '{% role "assistant" %}reply{% endrole %}'
                        '{% role "user" %}continue{% endrole %}'
                    ),
                    "target_scene_id": self.scene_id,
                    "provider": "anthropic",
                    "model": "x",
                },
            )
        kwargs = mock_chat.call_args.kwargs
        self.assertEqual(
            [m["role"] for m in kwargs["messages"]],
            ["user", "assistant", "user"],
        )
        self.assertEqual(
            [m["content"] for m in kwargs["messages"]],
            ["first", "reply", "continue"],
        )

    def test_empty_user_messages_rejected_with_400(self) -> None:
        # Template has only a system role; no user/assistant. Endpoint should
        # refuse since chat() can't be called with empty messages.
        self._allow_cloud()
        settings = _settings(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=settings):
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": '{% role "system" %}only system{% endrole %}',
                    "target_scene_id": self.scene_id,
                    "provider": "anthropic",
                    "model": "x",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no user/assistant messages", response.json()["detail"])

    def test_template_syntax_error_returns_422(self) -> None:
        self._allow_cloud()
        response = self.client.post(
            "/api/ai/generate",
            json={
                "template_source": '{% role "user" %}{{ undefined_var }}{% endrole %}',
                "target_scene_id": self.scene_id,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_missing_target_returns_404(self) -> None:
        self._allow_cloud()
        response = self.client.post(
            "/api/ai/generate",
            json={
                "template_source": '{% role "user" %}x{% endrole %}',
                "target_scene_id": "scene_does_not_exist",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_policy_off_blocks_via_chat_layer(self) -> None:
        # Default policy is off — rendering succeeds, but chat refuses.
        settings = _settings(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=settings), \
             patch("app.services.ai.providers._anthropic_chat") as mock_chat:
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": '{% role "user" %}hi{% endrole %}',
                    "target_scene_id": self.scene_id,
                    "provider": "anthropic",
                    "model": "x",
                },
            )
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("policy: off", body["error"])
        # Empty content; mock should never have been called
        self.assertEqual(body["content"], "")
        mock_chat.assert_not_called()

    def test_truncated_flag_propagates(self) -> None:
        self._allow_cloud()
        settings = _settings(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=settings), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("partial", "max_tokens", SimpleNamespace()),
            ):
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": '{% role "user" %}go{% endrole %}',
                    "target_scene_id": self.scene_id,
                    "provider": "anthropic",
                    "model": "x",
                    "max_tokens": 100,
                },
            )
        body = response.json()
        self.assertTrue(body["truncated"])
        self.assertEqual(body["stop_reason"], "max_tokens")

    def test_selection_is_available_in_template(self) -> None:
        self._allow_cloud()
        settings = _settings(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=settings), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("OK", "end_turn", SimpleNamespace()),
            ) as mock_chat:
            self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": '{% role "user" %}Rewrite: {{ selection }}{% endrole %}',
                    "target_scene_id": self.scene_id,
                    "selection": "the original sentence",
                    "provider": "anthropic",
                    "model": "x",
                },
            )
        kwargs = mock_chat.call_args.kwargs
        self.assertEqual(len(kwargs["messages"]), 1)
        self.assertEqual(kwargs["messages"][0]["content"], "Rewrite: the original sentence")

    def test_session_id_echoed_when_supplied(self) -> None:
        self._allow_cloud()
        settings = _settings(anthropic="sk-ant-test", default_provider="anthropic")
        with patch("app.services.machine_settings.load_settings", return_value=settings), \
             patch(
                "app.services.ai.providers._anthropic_chat",
                return_value=("ok", "end_turn", SimpleNamespace()),
            ):
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": '{% role "user" %}hi{% endrole %}',
                    "target_scene_id": self.scene_id,
                    "session_id": "test-session",
                    "provider": "anthropic",
                    "model": "x",
                },
            )
        self.assertEqual(response.json()["session_id"], "test-session")


if __name__ == "__main__":
    unittest.main()
