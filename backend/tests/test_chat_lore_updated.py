"""#2586: an entry the chat's session saw on an earlier turn and whose revision
has since changed is (1) flagged to the model by a `<changed_since_your_last_reply>`
note leading the volatile lore block and (2) reported as `lore_updated` for the
author's "Updated since last turn" chips, persisted on the message.
"""

from __future__ import annotations

import unittest

from test_lore_cache_blocks import _LoreCacheFixture

from app.models import (
    ChatUpdatedEntry,
    CreateChatSessionRequest,
    CreateStructureNodeRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
)
from app.services.ai.chat import expand_and_prepare_chat_blocks

_NOTE = "<changed_since_your_last_reply>"
_MSGS = [{"role": "user", "content": "hi"}]


class LoreUpdatedTests(_LoreCacheFixture):
    def setUp(self) -> None:
        super().setUp()
        self.premise_id = next(
            e.id for e in self.service.list_lore_entries().entries if e.title == "Premise"
        )

    def _prepare(self, chat_id: str | None = None):
        return expand_and_prepare_chat_blocks(
            self.service, chat_id or self.chat_id, "SYSTEM PROMPT", _MSGS
        )

    @staticmethod
    def _text(prepared, tier: str) -> str:
        return "".join(b["text"] for b in prepared.system_blocks or [] if b["tier"] == tier)

    def _edit_premise(self, body: str) -> str:
        premise_id = self.premise_id
        existing = self.service.read_lore_entry(premise_id)
        self.service.save_lore_entry(
            premise_id,
            SaveLoreEntryRequest(
                title="Premise",
                body=body,
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata={"context_policy": "always"},
            ),
        )
        return premise_id

    def test_first_turn_reports_nothing_updated(self) -> None:
        prepared = self._prepare()
        self.assertEqual(prepared.lore_updated, [])
        for block in prepared.system_blocks or []:
            self.assertNotIn(_NOTE, block["text"])

    def test_edit_between_turns_flags_the_entry_then_clears(self) -> None:
        self._prepare()
        premise_id = self._edit_premise("A shattered world.")
        turn2 = self._prepare()
        self.assertEqual(
            turn2.lore_updated, [ChatUpdatedEntry(entry_id=premise_id, title="Premise")]
        )
        volatile = self._text(turn2, "volatile")
        self.assertTrue(volatile.startswith(_NOTE))
        self.assertIn("- Premise", volatile.split("</changed_since_your_last_reply>")[0])
        self.assertIn("A shattered world.", volatile)
        self.assertNotIn(_NOTE, self._text(turn2, "stable"))
        # Turn 3, no further edit: settled — no flag, no note.
        turn3 = self._prepare()
        self.assertEqual(turn3.lore_updated, [])
        for block in turn3.system_blocks or []:
            self.assertNotIn(_NOTE, block["text"])

    def test_edited_picked_scene_is_flagged(self) -> None:
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:container")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:container")
        added = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="manuscript:scene", parent_id=act.id
            )
        )
        scene_id = next(c for c in added.root.children if c.id == act.id).children[-1].scene_id

        def write(body: str) -> None:
            scene = self.service.read_scene(scene_id)
            self.service.save_scene(
                scene_id,
                SaveSceneRequest(
                    title=scene.title,
                    body=body,
                    base_revision=scene.revision,
                    status="draft",
                    entry_type="manuscript:scene",
                    metadata={},
                ),
            )

        write("The train leaves at dawn.")
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="Pick", prompt_entry_id="p")
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(
                title="Pick", prompt_entry_id="p", lore_enabled=False, used_node_ids=[scene_id]
            ),
        )
        self.assertEqual(self._prepare(chat.id).lore_updated, [])
        write("The train left without her.")
        turn2 = self._prepare(chat.id)
        self.assertEqual(
            [(e.entry_id, e.title) for e in turn2.lore_updated],
            [(scene_id, "The Departure")],
        )
        volatile = self._text(turn2, "volatile")
        self.assertTrue(volatile.startswith(_NOTE))
        self.assertIn("The train left without her.", volatile)

    def test_lore_updated_round_trips_on_the_saved_message(self) -> None:
        self.service.save_chat_session(
            self.chat_id,
            SaveChatSessionRequest(
                title="Brainstorm",
                prompt_entry_id="prompt_x",
                lore_enabled=True,
                messages=[
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": "ok",
                        "lore_updated": [{"entry_id": "lore_1", "title": "Premise"}],
                    },
                    {"role": "assistant", "content": "later"},
                ],
            ),
        )
        msgs = self.service.read_chat_session(self.chat_id).messages
        self.assertEqual(
            msgs[1].lore_updated, [ChatUpdatedEntry(entry_id="lore_1", title="Premise")]
        )
        self.assertEqual(msgs[2].lore_updated, [])


if __name__ == "__main__":
    unittest.main()
