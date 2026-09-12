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


class _LoreCacheFixture(unittest.TestCase):
    """The project + lore-enabled chat every case below starts from. Test-less,
    so the two suites that extend it don't re-run each other's cases."""

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

    def _make_note(
        self,
        title: str,
        *,
        policy: str | None = None,
        body: str = "",
        refs: list[str] | None = None,
    ) -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:note")
        )
        existing = self.service.read_lore_entry(created.id)
        metadata: dict[str, object] = {}
        if policy is not None:
            metadata["context_policy"] = policy
        if refs:
            metadata["related_entries"] = list(refs)
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
        prepared = expand_and_prepare_chat_blocks(
            self.service, chat_id, "SYSTEM PROMPT", messages
        )
        return prepared.system_blocks or []


class LoreCacheBlockTests(_LoreCacheFixture):
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

    def test_used_mode_sends_only_the_chats_own_picks_and_leaves_the_chat_as_found(self) -> None:
        # #1874 / ADR-0067 Amendment 2: the commit's transcription turn narrows
        # the selector to the chat's `use()` picks — the always-policy Premise
        # stays out. And it is READ-ONLY on the chat's lore state: no journal
        # detection, no seen-revisions save (which, carrying an empty journal,
        # would trip the append-only guard with a 409), and no baseline promotion
        # (which would demote every settled world entry to volatile on the next
        # ordinary turn). Start from a chat that already HAS that state, so each
        # of those regressions would show.
        picked = self._make_note("Sidebar", body="A picked aside.")
        self._make_note("Gaslamp", body="Lit by whale oil.")  # journaled by mention on turn 1
        self.service.save_chat_session(
            self.chat_id,
            SaveChatSessionRequest(
                title="Brainstorm",
                prompt_entry_id="prompt_x",
                lore_enabled=True,
                used_node_ids=[picked],
            ),
        )
        self._blocks(self.chat_id, [{"role": "user", "content": "Tell me about Gaslamp"}])
        before = self.service.read_chat_session(self.chat_id)
        self.assertTrue(before.journal, "turn 1 should have journal-detected the mention")
        self.assertTrue(before.seen_revisions)
        baseline_before = dict(default_registry.get_or_create(f"chatlore:{self.chat_id}").baseline)

        prepared = expand_and_prepare_chat_blocks(
            self.service,
            self.chat_id,
            "SYSTEM PROMPT",
            [
                {"role": "user", "content": "Tell me about Gaslamp"},
                {"role": "assistant", "content": "Premise, Gaslamp, all of it."},
                {"role": "user", "content": "commit"},
            ],
            lore_mode="used",
        )
        text = "".join(b["text"] for b in prepared.system_blocks or [])
        self.assertIn("A picked aside", text)
        self.assertNotIn("A hidden world", text)  # always-policy: out
        self.assertNotIn("Lit by whale oil", text)  # journaled mention: out
        self.assertEqual(prepared.journal_added, [])
        after = self.service.read_chat_session(self.chat_id)
        self.assertEqual(after.journal, before.journal)
        self.assertEqual(after.seen_revisions, before.seen_revisions)
        self.assertEqual(
            default_registry.get_or_create(f"chatlore:{self.chat_id}").baseline, baseline_before
        )
        # The next ordinary turn still finds the world settled in the stable tier.
        turn3 = self._blocks(self.chat_id, [{"role": "user", "content": "more"}])
        stable_text = "".join(b["text"] for b in turn3 if b["tier"] == "stable")
        self.assertIn('name="Premise"', stable_text)

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


class LoreBudgetSendTests(_LoreCacheFixture):
    """ADR-0086 S1 on the send path: the inferred selection fits the assistant's
    budget, the declared set never does, and the turn reports what it left out.
    Shares the fixture (an `always` Premise = declared) and the helpers."""

    def test_a_detected_entry_that_is_also_a_pick_still_seeds_the_hop(self) -> None:
        # Parity with the pre-budget selector: EVERY detection seeds the
        # structural hop — including one that lands in the declared set because
        # it is also a use() pick. The pick itself is exact (not a seed); the
        # detection of it is.
        from app.models import ChatSessionJournalEntry
        from app.services.ai.lore_selection import _select_lore

        sidekick = self._make_note("Sidekick", body="Loyal.")
        hero = self._make_note("Hero", body="Brave.", refs=[sidekick])
        journal = [
            ChatSessionJournalEntry(
                entry_id=hero, title="Hero", source="user_message", added_at_turn=1
            )
        ]
        selection = _select_lore(self.service, None, journal, [hero])
        self.assertIn(hero, selection.declared)
        self.assertEqual(
            [(c.id, c.source) for c in selection.inferred], [(sidekick, "structural_hop")]
        )
        # Whereas a bare pick with no detection stays exact: no hop through it.
        bare = _select_lore(self.service, None, [], [hero])
        self.assertEqual(bare.inferred, ())

    _PROSE = "The tower keeps a beacon lit for the harbour pilots through winter. " * 40

    def _prepared(self, chat_id: str, messages: list[dict], **limits):
        from app.services.ai.lore_budget import LoreLimits

        return expand_and_prepare_chat_blocks(
            self.service, chat_id, "SYSTEM PROMPT", messages, lore_limits=LoreLimits(**limits)
        )

    def _wire_text(self, prepared) -> str:
        return "".join(b["text"] for b in prepared.system_blocks or [])

    def test_a_fitting_selection_sends_exactly_what_it_sent_before(self) -> None:
        # Acceptance: a chat whose inferred selection fits sends the same bytes,
        # in the same order, as the unbudgeted path — and reports nothing left out.
        self._make_note("Gaslamp", body="Lit by whale oil.")
        turn = [{"role": "user", "content": "Tell me about Gaslamp"}]
        # Two cold chats with the same prompt and turn: one through the
        # resolver's defaults (no limits given), one with an explicit budget
        # the selection fits in. Same bytes, same order.
        unbudgeted = expand_and_prepare_chat_blocks(self.service, self.chat_id, "SYSTEM PROMPT", turn)
        other = self._make_lore_enabled_chat("Brainstorm 2", "prompt_x")
        budgeted = self._prepared(other, turn, budget_tokens=400)
        self.assertEqual(budgeted.system_blocks, unbudgeted.system_blocks)
        assert budgeted.lore_fit is not None
        self.assertEqual(budgeted.lore_fit.left_out, [])
        self.assertEqual(budgeted.lore_fit.kept, 2)  # Premise (declared) + Gaslamp (inferred)
        self.assertGreater(budgeted.lore_fit.used_tokens, 0)
        self.assertGreater(budgeted.lore_fit.declared_tokens, 0)

    def test_the_budget_drops_inferred_entries_whole_and_reports_them(self) -> None:
        # Three mentioned towers, each ~500 tokens, and a budget that holds one:
        # the wire carries the declared Premise plus ONE whole tower; the report
        # names the two left out with their source and size, and matches the wire.
        towers = [self._make_note(f"Tower {n}", body=self._PROSE) for n in ("Ash", "Bell", "Cinder")]
        prepared = self._prepared(
            self.chat_id,
            [{"role": "user", "content": "Compare Tower Ash, Tower Bell and Tower Cinder."}],
            budget_tokens=600,
        )
        text = self._wire_text(prepared)
        fit = prepared.lore_fit
        assert fit is not None
        self.assertIn('name="Premise"', text)  # declared: never dropped
        sent = [t for t in towers if f'id="{t}"' in text]
        self.assertEqual(len(sent), 1, text)
        self.assertEqual(fit.kept, 2)
        self.assertEqual(len(fit.left_out), 2)
        self.assertEqual({e.id for e in fit.left_out}, set(towers) - set(sent))
        for entry in fit.left_out:
            self.assertEqual(entry.source, "user_message")
            self.assertTrue(entry.title.startswith("Tower "))
            self.assertGreater(entry.tokens, fit.budget_tokens - fit.used_tokens)
        self.assertLessEqual(fit.used_tokens, fit.budget_tokens)
        self.assertEqual(fit.budget_tokens, 600)

    def test_zero_budget_sends_only_declared_entries(self) -> None:
        self._make_note("Gaslamp", body="Lit by whale oil.")
        prepared = self._prepared(
            self.chat_id, [{"role": "user", "content": "Tell me about Gaslamp"}], budget_tokens=0
        )
        text = self._wire_text(prepared)
        self.assertIn('name="Premise"', text)
        self.assertNotIn('name="Gaslamp"', text)
        assert prepared.lore_fit is not None
        self.assertEqual([e.title for e in prepared.lore_fit.left_out], ["Gaslamp"])
        # The journal still recorded the mention — the budget shapes the send only.
        self.assertEqual(
            [e.title for e in self.service.read_chat_session(self.chat_id).journal], ["Gaslamp"]
        )

    def test_a_declared_set_over_the_budget_is_sent_whole_and_reported(self) -> None:
        # The declared set is the author's: a picked entry larger than the whole
        # budget still goes, and the inferred fit runs unchanged beside it.
        picked = self._make_note("Atlas", body=self._PROSE * 3)
        self._make_note("Gaslamp", body="Lit by whale oil.")
        self.service.save_chat_session(
            self.chat_id,
            SaveChatSessionRequest(
                title="Brainstorm", prompt_entry_id="prompt_x", lore_enabled=True,
                used_node_ids=[picked],
            ),
        )
        prepared = self._prepared(
            self.chat_id, [{"role": "user", "content": "Tell me about Gaslamp"}], budget_tokens=200
        )
        text = self._wire_text(prepared)
        fit = prepared.lore_fit
        assert fit is not None
        self.assertIn('name="Atlas"', text)
        self.assertIn('name="Gaslamp"', text)
        self.assertGreater(fit.declared_tokens, fit.budget_tokens)
        self.assertEqual(fit.left_out, [])

    def test_named_expansion_sends_no_hop_while_the_journal_still_records_it(self) -> None:
        # ADR-0086 §2b: `named` is applied at selection. The depth-1 detection
        # (Honey Jar, reached through Gaslamp's body) is still journaled, and a
        # structural ref off the scene-less chat's always-entry would be too —
        # but neither reaches the wire. Under `one_hop` both do.
        honey = self._make_note("Honey Jar", body="A tavern by the docks.")
        self._make_note("Gaslamp", body="Lit by whale oil, across from the Honey Jar.")
        turn = [{"role": "user", "content": "Tell me about Gaslamp"}]
        named = self._prepared(self.chat_id, turn, expansion="named")
        text = self._wire_text(named)
        self.assertIn('name="Gaslamp"', text)
        self.assertNotIn('name="Honey Jar"', text)
        journal = self.service.read_chat_session(self.chat_id).journal
        self.assertIn(("Honey Jar", "depth1_expansion"), [(e.title, e.source) for e in journal])
        assert named.lore_fit is not None
        self.assertEqual(named.lore_fit.left_out, [])  # not a candidate, so not "left out"
        # The same chat under `one_hop` sends the hop.
        default_registry.clear()
        hopped = self._prepared(self.chat_id, turn, expansion="one_hop")
        self.assertIn(f'id="{honey}"', self._wire_text(hopped))
        # ADR-0086 Amendment 1 (#1887): the author then NAMES the Honey Jar.
        # The journal, which knew it only through the hop, records it again
        # under the author's message, and `named` now sends it.
        default_registry.clear()
        named_later = self._prepared(
            self.chat_id,
            [
                *turn,
                {"role": "assistant", "content": "Gaslamp it is."},
                {"role": "user", "content": "And what happens at the Honey Jar?"},
            ],
            expansion="named",
        )
        self.assertIn(f'id="{honey}"', self._wire_text(named_later))
        sources = [(e.title, e.source) for e in self.service.read_chat_session(self.chat_id).journal]
        self.assertEqual(
            [s for s in sources if s[0] == "Honey Jar"],
            [("Honey Jar", "depth1_expansion"), ("Honey Jar", "user_message")],
        )

    def test_the_commit_turn_is_not_budgeted(self) -> None:
        # Anti-goal: the `used` turn has nothing inferred to budget and reports nothing.
        picked = self._make_note("Sidebar", body="A picked aside.")
        self.service.save_chat_session(
            self.chat_id,
            SaveChatSessionRequest(
                title="Brainstorm", prompt_entry_id="prompt_x", lore_enabled=True,
                used_node_ids=[picked],
            ),
        )
        prepared = expand_and_prepare_chat_blocks(
            self.service, self.chat_id, "SYSTEM PROMPT",
            [{"role": "user", "content": "commit"}], lore_mode="used",
        )
        self.assertIsNone(prepared.lore_fit)
        self.assertIn("A picked aside", self._wire_text(prepared))


class ChatLoreXmlTests(_LoreCacheFixture):
    """ADR-0086 S2: a sent turn's `lore_fit` names what was left out but carries
    no XML; the door renders an entry on request, as-of the chat's scene, through
    the same per-node render the send places."""

    def test_renders_one_entry_for_the_doors_drill_and_404s_the_rest(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services.ai.chat import render_chat_lore_entry_xml

        gaslamp = self._make_note("Gaslamp", body="Lit by whale oil.")
        xml = render_chat_lore_entry_xml(self.service, self.chat_id, gaslamp)
        assert xml is not None
        self.assertIn(f'id="{gaslamp}"', xml)
        self.assertIn("Lit by whale oil", xml)
        self.assertIsNone(render_chat_lore_entry_xml(self.service, self.chat_id, "lore_missing"))

        client = TestClient(app)
        response = client.get(f"/api/chats/{self.chat_id}/lore-xml/{gaslamp}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"entry_id": gaslamp, "xml": xml})
        self.assertEqual(
            client.get(f"/api/chats/{self.chat_id}/lore-xml/lore_missing").status_code, 404
        )
        self.assertEqual(client.get(f"/api/chats/chat_missing/lore-xml/{gaslamp}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
