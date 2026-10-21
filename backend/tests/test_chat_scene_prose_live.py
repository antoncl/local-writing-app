"""#2584: a chat renders its prompt template once, at the first send, and the
preset lock keeps that render byte-stable for the chat's life (ADR-0051 §6) —
so prose a template *prints* is frozen as of the first send, while what it
*chooses* with `use()` is re-rendered every turn.

The shipped "Summarize scene" chat is about a scene the author keeps editing, so
it must deliver the scene through `use()`. Driven the way the app drives it: the
lock render (`build_preview`, whose system text and `use()` picks the lock save
persists), then the send path's assembly for a later turn after an edit.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _builtins import builtin_prompt_id
from project_fixtures import open_test_project

from app.models import (
    CreateChatSessionRequest,
    CreateStructureNodeRequest,
    SaveChatSessionRequest,
    SaveSceneRequest,
)
from app.services.ai.chat import expand_and_prepare_chat_blocks
from app.services.ai.preview import PreviewRequest, build_preview
from app.services.ai.sessions import default_registry


class SummarizeSceneChatSeesEditsTests(unittest.TestCase):
    def setUp(self) -> None:
        default_registry.clear()
        self.temp_dir = TemporaryDirectory()
        self.service = open_test_project(
            Path(self.temp_dir.name).resolve() / "project", "Live scene"
        )
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Storm", entry_type="manuscript:scene")
        )
        self.scene_id = next(c.scene_id for c in structure.root.children if c.title == "Storm")
        self._save_scene("Seren rides into the storm.", "Old synopsis.")
        self.prompt = self.service.read_prompt_entry(
            builtin_prompt_id(self.service, "Summarize scene")
        )

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _save_scene(self, body: str, summary: str) -> None:
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=body,
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"summary": summary},
            ),
        )

    def _lock_chat(self) -> tuple[str, str]:
        """The first send's lock render + save (promptTemplateLock.ts): the system
        text and the `use()` picks are what the chat keeps for its life."""
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.prompt.body,
                target_scene_id="",
                session_id=None,
                inputs={"entry": self.scene_id},
                text_before="",
                text_after="",
                subject=self.scene_id,
                commit=False,
            ),
        )
        system_prompt = "".join(m.text for m in rendered.messages if m.role == "system")
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(
                title="Summary", prompt_entry_id=self.prompt.id, subject=self.scene_id
            )
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(
                title="Summary",
                prompt_entry_id=self.prompt.id,
                subject=self.scene_id,
                system_prompt=system_prompt,
                lore_enabled=rendered.lore_invoked,
                lore_free=rendered.lore_free,
                used_node_ids=rendered.used_node_ids,
                used_node_hints=rendered.used_node_hints,
            ),
        )
        return chat.id, system_prompt

    def _sent_text(self, chat_id: str, system_prompt: str, messages: list[dict]) -> str:
        prepared = expand_and_prepare_chat_blocks(self.service, chat_id, system_prompt, messages)
        return "\n".join(b["text"] for b in prepared.system_blocks or [])

    def test_a_later_turn_carries_the_edited_prose_not_the_first_sends(self) -> None:
        chat_id, system_prompt = self._lock_chat()
        turn1 = self._sent_text(chat_id, system_prompt, [{"role": "user", "content": "hi"}])
        self.assertIn("Seren rides into the storm.", turn1)

        self._save_scene("Seren turns back at the ford.", "Seren turns back.")
        turn2 = self._sent_text(
            chat_id,
            system_prompt,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "A synopsis."},
                {"role": "user", "content": "I rewrote it, try again"},
            ],
        )
        self.assertIn("Seren turns back at the ford.", turn2)
        self.assertIn("Seren turns back.", turn2)  # the current summary too
        # Nothing of the first send's prose survives anywhere in the request —
        # not in the locked system text, not as a second, stale copy.
        self.assertNotIn("Seren rides into the storm.", turn2)
        self.assertNotIn("Old synopsis.", turn2)


if __name__ == "__main__":
    unittest.main()
