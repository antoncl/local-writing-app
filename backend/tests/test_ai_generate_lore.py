"""ADR-0092 Amendment 1 §5: a one-shot run places declared lore only.

The inline surfaces (Tighten grammar, Expand, …) run through `/api/ai/generate`
and `/api/ai/generate/stream`. They place the `use()` picks and the project's
*always* entries after the system prompt, and never automatic lore, even when
the template calls `auto_lore()`: automatic lore belongs to a conversation. A
`no_lore()` prompt places its picks alone.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    SaveLoreEntryRequest,
    UpdateProjectSettingsRequest,
)
from app.services.ai.chat import one_shot_system_blocks
from app.services.ai.profiles.base import ChatOutcome
from app.services.ai.sessions import default_registry
from app.services.ai.templates import RenderedTemplate

_ANTHROPIC_CHAT = "app.services.ai.profiles.anthropic.AnthropicProfile.chat"
_SYSTEM = '{% role "system" %}You are an editor.{% endrole %}'
_USER = '{% role "user" %}Tighten: Mira opens the vault.{% endrole %}'


def _settings():
    from app.services import machine_settings as ms

    return ms.MachineSettings(
        providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
        default_provider="anthropic",
    )


class OneShotLoreTests(unittest.TestCase):
    def setUp(self) -> None:
        default_registry.clear()
        self.temp_dir = TemporaryDirectory()
        self.service = open_test_project(Path(self.temp_dir.name).resolve() / "project", "One-shot Lore")
        self.client = TestClient(app)
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="cloud-allowed"))
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="The Vault", entry_type="manuscript:scene")
        )
        self.scene_id = next(c.scene_id for c in structure.root.children if c.title == "The Vault")
        self._note("Narration Conventions", "always", "CONVENTIONS-SENTINEL short sentences.")
        # Named in the user turn: automatic detection would find it, so its
        # absence proves no automatic lore ran.
        self.mira = self._note("Mira", "auto", "MIRA-SENTINEL a locksmith.")

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _note(self, title: str, policy: str, body: str) -> str:
        created = self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type="lore:note"))
        existing = self.service.read_lore_entry(created.id)
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata={"context_policy": policy},
            ),
        )
        return created.id

    def _generate(self, template: str) -> str:
        """Run `/api/ai/generate` and return every system block's text, joined."""
        with patch("app.services.machine_settings.load_settings", return_value=_settings()), patch(
            _ANTHROPIC_CHAT, return_value=ChatOutcome("ok", "end_turn", SimpleNamespace())
        ) as mock_chat:
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": template,
                    "target_scene_id": self.scene_id,
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        call = mock_chat.call_args.args[0]
        return "\n".join(block["text"] for block in call.system_blocks or [])

    def test_a_prompt_with_no_lore_call_carries_the_always_entry(self) -> None:
        system = self._generate(_SYSTEM + _USER)
        self.assertIn("You are an editor.", system)
        self.assertIn("CONVENTIONS-SENTINEL", system)
        self.assertNotIn("MIRA-SENTINEL", system)

    def test_auto_lore_runs_no_automatic_lore_on_a_one_shot(self) -> None:
        # Mira is named in the system text, which automatic detection scans, so
        # she would be placed if automatic lore ran.
        system = self._generate(
            '{% do auto_lore() %}{% role "system" %}You edit Mira\'s chapter.{% endrole %}' + _USER
        )
        self.assertIn("CONVENTIONS-SENTINEL", system)
        self.assertNotIn("MIRA-SENTINEL", system)

    def test_a_lore_free_prompt_places_only_its_picks(self) -> None:
        system = self._generate(
            '{% do no_lore() %}{% do use("' + self.mira + '") %}' + _SYSTEM + _USER
        )
        self.assertIn("MIRA-SENTINEL", system)
        self.assertNotIn("CONVENTIONS-SENTINEL", system)

    def test_the_stream_route_carries_the_same_blocks(self) -> None:
        captured: dict[str, object] = {}

        def _fake_stream(call, **_kwargs):
            captured["call"] = call

            async def _none():
                return
                yield  # pragma: no cover - makes this an async generator

            return _none()

        with patch("app.services.machine_settings.load_settings", return_value=_settings()), patch(
            "app.routers.ai.ai_providers.chat_stream", side_effect=_fake_stream
        ):
            self.client.post(
                "/api/ai/generate/stream",
                json={
                    "template_source": _SYSTEM + _USER,
                    "target_scene_id": self.scene_id,
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                },
            )
        system = "\n".join(block["text"] for block in captured["call"].system_blocks or [])
        self.assertIn("CONVENTIONS-SENTINEL", system)


class OneShotSystemBlocksTests(unittest.TestCase):
    def test_lore_follows_the_system_prompt_stable_first(self) -> None:
        rendered = RenderedTemplate(messages=[], warnings=[])
        rendered.send_lore_stable = "<lore>stable</lore>"
        rendered.send_lore_volatile = "<lore>volatile</lore>"
        self.assertEqual(
            one_shot_system_blocks("SYSTEM", rendered),
            [
                {"text": "SYSTEM", "tier": "stable"},
                {"text": "<lore>stable</lore>", "tier": "stable"},
                {"text": "<lore>volatile</lore>", "tier": "volatile"},
            ],
        )

    def test_nothing_to_place_is_none(self) -> None:
        self.assertIsNone(one_shot_system_blocks("", RenderedTemplate(messages=[], warnings=[])))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
