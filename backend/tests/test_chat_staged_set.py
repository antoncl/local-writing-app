"""ADR-0055 S4: a chat OWNS its staged mutation set (the chat->set edge) and
seeds it into the AI context on send, so a resumed brainstorm keeps refining the
same change. The pin is a `staged_set` entity_ref in the chat node's `metadata`,
mirroring `subject` — singular, empty for impersonate / freeform chats.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateChatSessionRequest,
    CreateMutationSetEntryRequest,
    MutationSetRow,
    SaveChatSessionRequest,
)
from app.routers.ai import _prepare_chat_send_payload, _staged_set_block
from app.services.ai.helpers import _format_staged_set_block


class StagedSetBlockFormatTests(unittest.TestCase):
    """The pure XML formatter for a chat's owned staged set (ADR-0055 §4)."""

    def test_renders_rows_with_label_and_target(self) -> None:
        block = _format_staged_set_block(
            "Becomes a werewolf",
            "lore:character",
            [
                MutationSetRow(field="condition", op="replace", value="werewolf"),
                MutationSetRow(field="body", op="append", value="She turns at the blood moon."),
            ],
        )
        self.assertIn(
            '<staged_change label="Becomes a werewolf" target_type="lore:character">', block
        )
        self.assertIn('<mutation field="condition" op="replace">werewolf</mutation>', block)
        self.assertIn(
            '<mutation field="body" op="append">She turns at the blood moon.</mutation>', block
        )
        self.assertTrue(block.endswith("</staged_change>"))

    def test_empty_when_no_usable_rows(self) -> None:
        self.assertEqual(_format_staged_set_block("x", "lore:character", []), "")
        # A field-less row contributes nothing, so an all-blank set seeds no block.
        self.assertEqual(
            _format_staged_set_block("x", "lore:character", [MutationSetRow(field="", value="v")]),
            "",
        )

    def test_escapes_markup_in_values_and_omits_empty_attrs(self) -> None:
        block = _format_staged_set_block(
            "", "", [MutationSetRow(field="body", value="A <tag> & more")]
        )
        self.assertIn("&lt;tag&gt;", block)
        self.assertIn("&amp;", block)
        # No label / target attrs when both are empty.
        self.assertIn("<staged_change>\n", block)


class ChatStagedSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Chat Staged Set Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_set(self, title: str = "Becomes a werewolf") -> str:
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title=title,
                target_entry_type="lore:character",
                rows=[MutationSetRow(field="condition", op="replace", value="werewolf")],
            )
        )
        return created.id

    def _make_chat(self, staged_set: str = "") -> str:
        session = self.service.create_chat_session(
            CreateChatSessionRequest(title="Brainstorm", staged_set=staged_set)
        )
        return session.id

    def _chat_text(self, chat_id: str) -> str:
        return (self.root / "chats" / f"{chat_id}.md").read_text(encoding="utf-8")

    def test_staged_set_roundtrips_through_metadata(self) -> None:
        set_id = self._make_set()
        chat_id = self._make_chat(staged_set=set_id)
        # The model carries the pin top-level; the file stores it in `metadata`.
        self.assertEqual(self.service.read_chat_session(chat_id).staged_set, set_id)
        self.assertIn(f"staged_set: {set_id}", self._chat_text(chat_id))

    def test_chat_without_staged_set_writes_no_pin(self) -> None:
        chat_id = self._make_chat()
        self.assertEqual(self.service.read_chat_session(chat_id).staged_set, "")
        # omit_empty_metadata keeps an un-staged chat's file free of the pin.
        self.assertNotIn("staged_set", self._chat_text(chat_id))

    def test_chat_owns_set_via_reverse_edge(self) -> None:
        # The whole point of §4: the set's reverse index lists the chats refining
        # it, exactly as a subject lists its conversations (kind-neutral edge).
        set_id = self._make_set()
        chat_id = self._make_chat(staged_set=set_id)
        reverse = self.service._build_node_index().edges_by_dst.get(set_id, [])
        self.assertIn(chat_id, [edge.src for edge in reverse])
        self.assertIn("staged_set", [edge.field_id for edge in reverse])

    def test_staged_set_survives_a_save_that_omits_it(self) -> None:
        # A per-turn / rename save that doesn't carry the pin must not drop it
        # (the `request.staged_set or existing.staged_set` fallback, like subject).
        set_id = self._make_set()
        chat_id = self._make_chat(staged_set=set_id)
        self.service.save_chat_session(
            chat_id, SaveChatSessionRequest(title="Renamed", pinned=False)
        )
        self.assertEqual(self.service.read_chat_session(chat_id).staged_set, set_id)

    def test_staged_set_block_resolves_empty_and_dangling_to_blank(self) -> None:
        # The resolver guard: no id and an unresolvable id both seed nothing,
        # while a real set renders. Covers the helper independent of the router.
        self.assertEqual(_staged_set_block(self.service, ""), "")
        self.assertEqual(_staged_set_block(self.service, "mutation_set_gone"), "")
        set_id = self._make_set()
        self.assertIn("<staged_change", _staged_set_block(self.service, set_id))

    def test_send_payload_seeds_the_owned_set(self) -> None:
        # Resume seeding: the send envelope carries the staged set's rows so the
        # AI continues refining the same change.
        set_id = self._make_set()
        chat_id = self._make_chat(staged_set=set_id)
        blocks, _, _ = _prepare_chat_send_payload(
            self.service, chat_id, "System brief.", [{"role": "user", "content": "hi"}]
        )
        texts = "\n".join(block["text"] for block in (blocks or []))
        self.assertIn("<staged_change", texts)
        self.assertIn('field="condition"', texts)

    def test_send_payload_omits_a_dangling_staged_set(self) -> None:
        # A ref to a set that no longer resolves seeds no block and does not fail
        # the send (deleting a set normally purges this pin anyway).
        chat_id = self._make_chat(staged_set="mutation_set_deleted")
        blocks, _, _ = _prepare_chat_send_payload(
            self.service, chat_id, "System brief.", [{"role": "user", "content": "hi"}]
        )
        texts = "\n".join(block["text"] for block in (blocks or []))
        self.assertNotIn("<staged_change", texts)


if __name__ == "__main__":
    unittest.main()
