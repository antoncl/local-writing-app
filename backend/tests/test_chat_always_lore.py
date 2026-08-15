"""ADR-0057 slice 1 (#1016): `context_policy: always` lore reaches EVERY chat's
send payload — including a brainstorm whose template never calls `relevant_lore()`
— seeded by the send path itself, not the template.

The regression this guards: a create-character brainstorm ignored two notes the
writer had marked Context policy = Always, because the send path only ran the
auto-only textual expander and the `always` wholesale union lived solely inside
the `relevant_lore()` helper (which such a template never calls). The union now
fires from `expand_and_prepare_chat_blocks`, deduped by id against the journal
and explicit picks.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    ChatSessionContextItem,
    ChatSessionJournalEntry,
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    SaveLoreEntryRequest,
)
from app.services.ai.chat import _always_policy_lore_ids, expand_and_prepare_chat_blocks


class ChatAlwaysPolicyLoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Always Policy Lore Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers ---------------------------------------------------------

    def _make_lore(self, title: str, *, policy: str | None = None, body: str = "") -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:note")
        )
        self._set(created.id, title=title, body=body, policy=policy)
        return created.id

    def _set(self, entry_id: str, *, title: str, body: str, policy: str | None) -> None:
        existing = self.service.read_lore_entry(entry_id)
        metadata = dict(existing.metadata)
        if policy is None:
            metadata.pop("context_policy", None)
        else:
            metadata["context_policy"] = policy
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata=metadata,
            ),
        )

    def _make_chat(self, context_items: list[ChatSessionContextItem] | None = None) -> str:
        session = self.service.create_chat_session(
            CreateChatSessionRequest(title="Brainstorm", context_items=context_items or [])
        )
        return session.id

    def _blocks_text(
        self,
        chat_id: str,
        *,
        system_prompt: str = "You are an ideation partner. Draft a new character.",
        user: str = "Let's brainstorm the protagonist.",
    ) -> str:
        # A brainstorm system prompt with NO lore and NO `relevant_lore()` output —
        # exactly the template that dropped the notes.
        blocks, _, _ = expand_and_prepare_chat_blocks(
            self.service, chat_id, system_prompt, [{"role": "user", "content": user}]
        )
        return "\n".join(block["text"] for block in (blocks or []))

    # --- the fix ---------------------------------------------------------

    def test_always_note_reaches_a_brainstorm_that_never_mentions_it(self) -> None:
        # The dogfooding symptom: neither note is named in the user message, and
        # the template calls no `relevant_lore()`. Under `auto` they stay out;
        # under `always` they must appear.
        note = self._make_lore(
            "Feral Line: Urban Bestiary universe",
            body="Shapeshifters live hidden in the modern city.",
        )
        chat_id = self._make_chat()
        self.assertNotIn("Feral Line", self._blocks_text(chat_id))
        self._set(
            note,
            title="Feral Line: Urban Bestiary universe",
            body="Shapeshifters live hidden in the modern city.",
            policy="always",
        )
        text = self._blocks_text(chat_id)
        self.assertIn('name="Feral Line: Urban Bestiary universe"', text)
        self.assertIn("Shapeshifters live hidden", text)

    def test_no_always_entries_seeds_no_block(self) -> None:
        # A plain project with only auto-policy lore and no textual match must
        # produce no lore block at all — no regression for the common case.
        self._make_lore("Premise", body="A short premise.")  # default (auto)
        chat_id = self._make_chat()
        self.assertNotIn("<lore>", self._blocks_text(chat_id))

    def test_recomputed_from_current_policy_each_send(self) -> None:
        # `always` is a live policy read, not journal state: un-marking an entry
        # drops it on the very next send.
        note = self._make_lore("Premise", body="A short premise.", policy="always")
        chat_id = self._make_chat()
        self.assertIn('name="Premise"', self._blocks_text(chat_id))
        self._set(note, title="Premise", body="A short premise.", policy="auto")
        self.assertNotIn('name="Premise"', self._blocks_text(chat_id))

    # --- dedup (§Journey B) ---------------------------------------------

    def test_deduped_against_an_explicit_lore_pick(self) -> None:
        # The writer marked "Premise" Always AND pinned it in the picker. The
        # explicit pick owns it (rendered via that channel); the always union
        # must not add it a second time.
        note = self._make_lore("Premise", body="A short premise.", policy="always")
        pick = ChatSessionContextItem(kind="lore", id=note, title="Premise")
        self.assertEqual(
            _always_policy_lore_ids(self.service, [pick], []),
            [],
        )

    def test_deduped_against_the_journal(self) -> None:
        # An always entry already in the journal (it happened to be textually
        # detected on a prior turn) is not re-added by the union.
        note = self._make_lore("Premise", body="A short premise.", policy="always")
        journal = [ChatSessionJournalEntry(entry_id=note, title="Premise")]
        self.assertEqual(
            _always_policy_lore_ids(self.service, [], journal),
            [],
        )

    def test_union_ids_are_sorted_and_exclude_non_always(self) -> None:
        # Only `always`-policy entries are unioned; ids come back sorted for a
        # stable, cache-friendly block.
        b = self._make_lore("Bravo", policy="always")
        a = self._make_lore("Alpha", policy="always")
        self._make_lore("Charlie", policy="auto")  # excluded
        self.assertEqual(
            _always_policy_lore_ids(self.service, [], []),
            sorted([a, b]),
        )

    def test_always_block_is_stable_tier(self) -> None:
        # Project-wide context is not conversation-volatile — it must ride the
        # 1h cache tier, above the 5m journal block.
        self._make_lore("Premise", body="A short premise.", policy="always")
        chat_id = self._make_chat()
        blocks, _, _ = expand_and_prepare_chat_blocks(
            self.service, chat_id, "Draft a character.", [{"role": "user", "content": "hi"}]
        )
        always_block = next(b for b in (blocks or []) if "Premise" in b["text"])
        self.assertEqual(always_block["ttl"], "1h")


if __name__ == "__main__":
    unittest.main()
