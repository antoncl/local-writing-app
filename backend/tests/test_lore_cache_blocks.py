"""docs/design/context-caching.md §4/§6: the send path places a chat's one
deduped lore set once *per stability tier*, partitioned per turn against the
chat's in-memory session baseline — unchanged-since-last-turn → a 1h stable
block, new-or-changed → a 5m volatile block.

`expand_and_prepare_chat_blocks` is pure (it assembles blocks, it doesn't call a
provider), so these exercise it directly and inspect the returned cache blocks.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
)
from app.services.ai.chat import expand_and_prepare_chat_blocks
from app.services.ai.sessions import default_registry


class LoreCacheBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        # The baseline lives in the process-wide in-memory registry; isolate it.
        default_registry.clear()
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Lore Cache Blocks")
        # An always-policy note reaches every lore-enabled chat via the union,
        # without needing a mention or a scene.
        self._make_note("Premise", policy="always", body="A hidden world.")
        self.chat_id = self._make_lore_enabled_chat("Brainstorm", "prompt_x")

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _make_note(self, title: str, *, policy: str | None = None, body: str = "") -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:note")
        )
        existing = self.service.read_lore_entry(created.id)
        metadata: dict[str, str] = {}
        if policy is not None:
            metadata["context_policy"] = policy
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata=metadata,
            ),
        )
        return created.id

    def _make_lore_enabled_chat(self, title: str, prompt_id: str) -> str:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title=title, prompt_entry_id=prompt_id)
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title=title, prompt_entry_id=prompt_id, lore_enabled=True),
        )
        return chat.id

    def _blocks(self, chat_id: str, messages: list[dict]) -> list[dict]:
        blocks, _sid, _added = expand_and_prepare_chat_blocks(
            self.service, chat_id, "SYSTEM PROMPT", messages
        )
        return blocks or []

    def test_first_turn_places_lore_in_the_volatile_tier(self) -> None:
        # Empty baseline → everything is new → volatile. So: the system 1h block,
        # and one 5m lore block carrying the premise. No stable lore block yet.
        blocks = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        one_h = [b for b in blocks if b["tier"] == "stable"]
        five_m = [b for b in blocks if b["tier"] == "volatile"]
        self.assertEqual(len(one_h), 1)  # just the system prompt
        self.assertEqual(len(five_m), 1)  # the volatile lore
        self.assertIn('name="Premise"', five_m[0]["text"])
        self.assertIn("A hidden world", five_m[0]["text"])

    def test_settled_lore_migrates_to_the_stable_tier_next_turn(self) -> None:
        # Turn 1: the premise is new → VOLATILE (and commits to the baseline).
        # Asserting the turn-1 precondition here — not just the turn-2 state — is
        # what makes this prove a *migration* rather than surviving a code that
        # always classifies stable.
        turn1 = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        t1_stable = "".join(b["text"] for b in turn1 if b["tier"] == "stable")
        t1_volatile = "".join(b["text"] for b in turn1 if b["tier"] == "volatile")
        self.assertIn('name="Premise"', t1_volatile)
        self.assertNotIn('name="Premise"', t1_stable)
        # Turn 2: the premise is unchanged since the baseline → it moves into the
        # cached 1h stable tier and is no longer re-billed as volatile.
        blocks = self._blocks(
            self.chat_id,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "tell me more"},
            ],
        )
        stable_text = "".join(b["text"] for b in blocks if b["tier"] == "stable")
        volatile_text = "".join(b["text"] for b in blocks if b["tier"] == "volatile")
        self.assertIn('name="Premise"', stable_text)
        self.assertNotIn('name="Premise"', volatile_text)

    def test_gate_off_places_no_lore(self) -> None:
        # A chat that never flipped the gate gets no lore at all, even though the
        # always-note exists (Journey C).
        off = self.service.create_chat_session(
            CreateChatSessionRequest(title="Lore-free", prompt_entry_id="prompt_y")
        )
        blocks = self._blocks(off.id, [{"role": "user", "content": "Premise please"}])
        self.assertEqual([b["tier"] for b in blocks], ["stable"])  # only the system prompt
        self.assertTrue(all("Premise" not in b["text"] for b in blocks))

    def test_scene_anchored_chat_includes_the_scenes_referenced_lore(self) -> None:
        # The roleplay case: a chat anchored to a scene must place the lore the
        # scene directly references (its characters), proving the send path
        # threads the chat's scene into the one selector. Before the fix this
        # lore came from the template's `relevant_lore(scene)` render; now the
        # backend resolves it as-of that scene.
        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
        )
        existing = self.service.read_lore_entry(hero.id)
        self.service.save_lore_entry(
            hero.id,
            SaveLoreEntryRequest(
                title="Honor Harrington",
                body="Captain of the Fearless.",
                base_revision=existing.revision,
                entry_type="lore:character",
                metadata={},
            ),
        )
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:act")
        added = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="manuscript:scene", parent_id=act.id
            )
        )
        scene_node = next(c for c in added.root.children if c.id == act.id).children[-1]
        scene_id = scene_node.scene_id
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body="Prose.",
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"characters": [hero.id]},
            ),
        )
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="RP", prompt_entry_id="p", subject=scene_id)
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="RP", prompt_entry_id="p", lore_enabled=True),
        )
        blocks = self._blocks(chat.id, [{"role": "user", "content": "begin"}])
        text = "".join(b["text"] for b in blocks)
        self.assertIn('name="Honor Harrington"', text)

    def test_use_selected_node_joins_the_lore_set(self) -> None:
        # ADR-0060 §2: a node the prompt selected via `use()` — persisted as the
        # chat's `used_node_ids` — joins the send path's ONE lore selector. No
        # scene ref, no mention, no always-policy: the selection alone pulls it in,
        # and it is placed and tiered like any other entry (never emitted inline).
        picked = self._make_note("Sidebar", body="A picked aside.")
        self.service.save_chat_session(
            self.chat_id,
            SaveChatSessionRequest(
                title="Brainstorm",
                prompt_entry_id="prompt_x",
                lore_enabled=True,
                used_node_ids=[picked],
            ),
        )
        blocks = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        text = "".join(b["text"] for b in blocks)
        self.assertIn('name="Sidebar"', text)
        self.assertIn("A picked aside", text)

    def test_use_selected_never_policy_node_stays_excluded(self) -> None:
        # `use()` joins the SAME direct channel, so it still obeys the one `never`
        # chokepoint — a selection cannot override a `never`-policy entry.
        blocked = self._make_note("Secret", policy="never", body="Do not show.")
        self.service.save_chat_session(
            self.chat_id,
            SaveChatSessionRequest(
                title="Brainstorm",
                prompt_entry_id="prompt_x",
                lore_enabled=True,
                used_node_ids=[blocked],
            ),
        )
        blocks = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        text = "".join(b["text"] for b in blocks)
        self.assertNotIn('name="Secret"', text)

    def test_an_entry_appears_in_exactly_one_tier(self) -> None:
        # The double-inclusion this fix removes: no entry may be in both blocks.
        self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        blocks = self._blocks(
            self.chat_id,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "more"},
            ],
        )
        in_stable = any(
            'name="Premise"' in b["text"] for b in blocks if b["tier"] == "stable"
        )
        in_volatile = any(
            'name="Premise"' in b["text"] for b in blocks if b["tier"] == "volatile"
        )
        self.assertNotEqual(in_stable, in_volatile)  # exactly one, never both


if __name__ == "__main__":
    unittest.main()
