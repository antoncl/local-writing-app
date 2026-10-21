"""#2586: an entry the model received on an earlier turn and whose revision has
since changed is (1) flagged to the model by a `<changed_since_you_last_saw_them>`
note trailing the volatile lore block and (2) reported as `lore_updated` for the
author's "Updated since last turn" chips, persisted on the message.

"Received" is literal: a turn's lore is committed only by a completed send
(`send_turn` here; the stream's `on_done` / an ok reply in the app). A bare
`expand_and_prepare_chat_blocks` models a send that failed.
"""

from __future__ import annotations

import unittest

from _chat_turns import send_turn
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
from app.services.ai.sessions import default_registry

_NOTE = "<changed_since_you_last_saw_them>"
_NOTE_END = "</changed_since_you_last_saw_them>"
_MSGS = [{"role": "user", "content": "hi"}]


class LoreUpdatedTests(_LoreCacheFixture):
    def setUp(self) -> None:
        super().setUp()
        self.premise_id = next(
            e.id for e in self.service.list_lore_entries().entries if e.title == "Premise"
        )

    def _send(self, chat_id: str | None = None):
        return send_turn(self.service, chat_id or self.chat_id, "SYSTEM PROMPT", _MSGS)

    def _failed_send(self, chat_id: str | None = None):
        return expand_and_prepare_chat_blocks(
            self.service, chat_id or self.chat_id, "SYSTEM PROMPT", _MSGS
        )

    @staticmethod
    def _text(prepared, tier: str) -> str:
        return "".join(b["text"] for b in prepared.system_blocks or [] if b["tier"] == tier)

    @staticmethod
    def _ids(prepared) -> list[str]:
        return [e.entry_id for e in prepared.lore_updated]

    def _edit(self, entry_id: str, body: str, *, policy: str | None = None) -> None:
        existing = self.service.read_lore_entry(entry_id)
        metadata = {"context_policy": policy} if policy else {}
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=existing.title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata=metadata,
            ),
        )

    def _pick_chat(self, picked: list[str], hints: dict[str, str] | None = None) -> str:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="Pick", prompt_entry_id="p")
        )
        self._set_picks(chat.id, picked, hints)
        return chat.id

    def _set_picks(
        self, chat_id: str, picked: list[str], hints: dict[str, str] | None = None
    ) -> None:
        self.service.save_chat_session(
            chat_id,
            SaveChatSessionRequest(
                title="Pick",
                prompt_entry_id="p",
                lore_enabled=False,
                used_node_ids=picked,
                used_node_hints=hints or {},
            ),
        )

    def test_first_turn_reports_nothing_updated(self) -> None:
        prepared = self._send()
        self.assertEqual(prepared.lore_updated, [])
        for block in prepared.system_blocks or []:
            self.assertNotIn(_NOTE, block["text"])

    def test_edit_between_turns_flags_the_entry_then_clears(self) -> None:
        self._send()
        self._edit(self.premise_id, "A shattered world.", policy="always")
        turn2 = self._send()
        self.assertEqual(
            turn2.lore_updated, [ChatUpdatedEntry(entry_id=self.premise_id, title="Premise")]
        )
        volatile = self._text(turn2, "volatile")
        self.assertTrue(volatile.endswith(_NOTE_END))
        self.assertIn("- Premise", volatile.split(_NOTE)[1])
        self.assertIn("A shattered world.", volatile)
        self.assertNotIn(_NOTE, self._text(turn2, "stable"))
        # Turn 3, no further edit: settled — no flag, no note.
        turn3 = self._send()
        self.assertEqual(turn3.lore_updated, [])
        for block in turn3.system_blocks or []:
            self.assertNotIn(_NOTE, block["text"])

    def test_the_note_names_what_changed_never_who(self) -> None:
        self._send()
        self._edit(self.premise_id, "A shattered world.", policy="always")
        volatile = self._text(self._send(), "volatile")
        self.assertNotIn("author", volatile.split(_NOTE)[1].lower())

    def test_only_the_changed_entry_is_named(self) -> None:
        other = self._make_note("Gaslamp", policy="always", body="Lit by whale oil.")
        self._send()
        self._edit(self.premise_id, "A shattered world.", policy="always")
        turn2 = self._send()
        self.assertEqual(self._ids(turn2), [self.premise_id])
        self.assertNotIn("- Gaslamp", self._text(turn2, "volatile").split(_NOTE)[1])
        self.assertIn(other, self.service.read_chat_session(self.chat_id).seen_revisions)

    def test_a_failed_send_does_not_consume_the_flag(self) -> None:
        self._send()
        self._edit(self.premise_id, "A shattered world.", policy="always")
        seen_before = self.service.read_chat_session(self.chat_id).seen_revisions
        failed = self._failed_send()
        self.assertEqual(self._ids(failed), [self.premise_id])
        # Nothing persisted, nothing promoted: the retry still sees the change.
        self.assertEqual(self.service.read_chat_session(self.chat_id).seen_revisions, seen_before)
        retry = self._send()
        self.assertEqual(self._ids(retry), [self.premise_id])
        self.assertEqual(self._send().lore_updated, [])

    def test_an_entry_that_skipped_a_turn_is_still_flagged(self) -> None:
        aside = self._make_note("Aside", body="A picked aside.")
        chat_id = self._pick_chat([aside])
        self._send(chat_id)
        self._set_picks(chat_id, [])
        self.assertEqual(self._send(chat_id).lore_updated, [])  # absent this turn
        self._edit(aside, "The aside, rewritten.")
        self._set_picks(chat_id, [aside])
        back = self._send(chat_id)
        self.assertEqual(self._ids(back), [aside])
        self.assertIn("The aside, rewritten.", self._text(back, "volatile"))

    def test_a_stable_hinted_pick_is_flagged_even_while_tiered_stable(self) -> None:
        # Skipping a turn makes the pick "new" to the tiering, so its "stable"
        # hint keeps it in the stable block — the note must still reach the
        # model, in the volatile block, and name it.
        aside = self._make_note("Aside", body="A picked aside.")
        chat_id = self._pick_chat([aside], {aside: "stable"})
        self._send(chat_id)
        self._set_picks(chat_id, [], {})
        self._send(chat_id)
        self._edit(aside, "The aside, rewritten.")
        self._set_picks(chat_id, [aside], {aside: "stable"})
        back = self._send(chat_id)
        self.assertEqual(self._ids(back), [aside])
        self.assertIn("The aside, rewritten.", self._text(back, "stable"))
        self.assertIn("- Aside", self._text(back, "volatile").split(_NOTE)[1])

    def test_a_volatile_hinted_pick_is_flagged_once(self) -> None:
        aside = self._make_note("Aside", body="A picked aside.")
        chat_id = self._pick_chat([aside], {aside: "volatile"})
        self._send(chat_id)
        self.assertEqual(self._send(chat_id).lore_updated, [])  # pinned volatile, unchanged
        self._edit(aside, "The aside, rewritten.")
        self.assertEqual(self._ids(self._send(chat_id)), [aside])
        self.assertEqual(self._send(chat_id).lore_updated, [])

    def test_a_cold_restart_still_flags_an_edit(self) -> None:
        self._send()
        default_registry.clear()  # a fresh process: seeded from seen_revisions
        self._edit(self.premise_id, "A shattered world.", policy="always")
        self.assertEqual(self._ids(self._send()), [self.premise_id])

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
        chat_id = self._pick_chat([scene_id])
        self.assertEqual(self._send(chat_id).lore_updated, [])
        write("The train left without her.")
        turn2 = self._send(chat_id)
        self.assertEqual(
            [(e.entry_id, e.title) for e in turn2.lore_updated],
            [(scene_id, "The Departure")],
        )
        volatile = self._text(turn2, "volatile")
        self.assertTrue(volatile.endswith(_NOTE_END))
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
