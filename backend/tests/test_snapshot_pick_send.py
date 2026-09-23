"""ADR-0093 §2: the send places a `use(node, snapshot=id)` pick's before
element as its own entry in the stable lore block, tiered by the
`use(node, "stable")` rule — never folded into the after.

Fixture reused from `test_lore_cache_blocks.py` (`_LoreCacheFixture`), incl.
its `default_registry.clear()` habit — the in-memory session baseline lives
in a process-wide registry that must be isolated per test.
"""

from __future__ import annotations

from test_lore_cache_blocks import _LoreCacheFixture

from app.models import (
    CreateLoreEntryRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SnapshotPick,
)
from app.services.ai.chat import expand_and_prepare_chat_blocks
from app.services.ai.lore_budget import snapshot_pick_key
from app.services.ai.sessions import default_registry


class SnapshotPickSendTests(_LoreCacheFixture):
    def _make_character(self, title: str, *, body: str = "", related: list[str] | None = None):
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        )
        existing = self.service.read_lore_entry(created.id)
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:character",
                metadata={"related_entries": related or []},
            ),
        )
        return created.id

    def _set_picks(self, *, used_node_ids=None, used_snapshots=None, lore_enabled=False) -> None:
        self.service.save_chat_session(
            self.chat_id,
            SaveChatSessionRequest(
                title="Brainstorm",
                prompt_entry_id="prompt_x",
                lore_enabled=lore_enabled,
                used_node_ids=used_node_ids or [],
                used_snapshots=used_snapshots or [],
            ),
        )

    def test_before_and_after_both_present_flag_off_never_dedupe(self) -> None:
        source = self._make_character("Marek Vell", body="A captain.")
        snap = self.service.capture_snapshot(source, kind="lore", origin="propagation")
        self._set_picks(
            used_node_ids=[source],
            used_snapshots=[SnapshotPick(entry_id=source, snapshot_id=snap.id)],
        )
        blocks = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        stable_text = "".join(b["text"] for b in blocks if b["tier"] == "stable")
        volatile_text = "".join(b["text"] for b in blocks if b["tier"] == "volatile")
        # Turn one: the after (a fresh pick) is new → volatile; the before is
        # new-but-unseen → stable (the `use(node, "stable")` rule, not the base
        # per-revision rule, which would wrongly volatile it on a cold baseline).
        self.assertIn(f'snapshot="{snap.id}"', stable_text)
        self.assertIn("captured=", stable_text)
        self.assertIn(f'id="{source}"', volatile_text)
        self.assertNotIn("snapshot=", volatile_text)
        # Never dedupes: the after's own element (no `snapshot=` attribute) is
        # NOT also folded into the stable block under the before's key.
        self.assertEqual(stable_text.count(f'id="{source}"'), 1)

    def test_snapshot_pick_alone_still_places_and_records_seen_revisions(self) -> None:
        source = self._make_character("Solo Source", body="Alone.")
        snap = self.service.capture_snapshot(source, kind="lore", origin="propagation")
        self._set_picks(used_snapshots=[SnapshotPick(entry_id=source, snapshot_id=snap.id)])
        blocks = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        text = "".join(b["text"] for b in blocks)
        self.assertIn(f'snapshot="{snap.id}"', text)
        after = self.service.read_chat_session(self.chat_id)
        self.assertIn(snapshot_pick_key(source, snap.id), after.seen_revisions)

    def test_editing_source_retiers_after_before_stays_stable(self) -> None:
        source = self._make_character("Marek Vell", body="A captain.")
        snap = self.service.capture_snapshot(source, kind="lore", origin="propagation")
        self._set_picks(
            used_node_ids=[source],
            used_snapshots=[SnapshotPick(entry_id=source, snapshot_id=snap.id)],
        )
        # Turn 1: settle the after into the baseline.
        self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        # Edit the live source.
        existing = self.service.read_lore_entry(source)
        self.service.save_lore_entry(
            source,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="A captain, now promoted.",
                base_revision=existing.revision,
                entry_type="lore:character",
                metadata={"related_entries": []},
            ),
        )
        blocks = self._blocks(
            self.chat_id,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "more"},
            ],
        )
        stable_text = "".join(b["text"] for b in blocks if b["tier"] == "stable")
        volatile_text = "".join(b["text"] for b in blocks if b["tier"] == "volatile")
        # The after re-tiers to volatile (its bytes changed); the before —
        # frozen at the snapshot — never re-renders differently, so it stays
        # stable across the edit.
        self.assertIn(f'id="{source}"', volatile_text)
        self.assertIn(f'snapshot="{snap.id}"', stable_text)
        self.assertNotIn("snapshot=", volatile_text)

    def test_renaming_a_referenced_entry_retiers_the_before_once(self) -> None:
        target = self._make_character("Old Name")
        source = self._make_character("Referrer", related=[target])
        snap = self.service.capture_snapshot(source, kind="lore", origin="propagation")
        self._set_picks(used_snapshots=[SnapshotPick(entry_id=source, snapshot_id=snap.id)])

        # Turn 1: unseen before → stable.
        turn1 = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        turn1_stable = "".join(b["text"] for b in turn1 if b["tier"] == "stable")
        turn1_volatile = "".join(b["text"] for b in turn1 if b["tier"] == "volatile")
        self.assertIn("Old Name", turn1_stable)
        self.assertNotIn("snapshot=", turn1_volatile)

        # Rename the entry the source's own field points at — the before's
        # LIVE-resolved reference name changes, so its rendered bytes change.
        existing_target = self.service.read_lore_entry(target)
        self.service.save_lore_entry(
            target,
            SaveLoreEntryRequest(
                title="New Name",
                body="",
                base_revision=existing_target.revision,
                entry_type="lore:character",
                metadata={},
            ),
        )

        # Turn 2: the before's bytes changed since the seeded baseline → volatile once.
        turn2 = self._blocks(
            self.chat_id,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "more"},
            ],
        )
        turn2_stable = "".join(b["text"] for b in turn2 if b["tier"] == "stable")
        turn2_volatile = "".join(b["text"] for b in turn2 if b["tier"] == "volatile")
        self.assertIn("New Name", turn2_volatile)
        self.assertNotIn("snapshot=", turn2_stable)

        # Turn 3: settled again.
        turn3 = self._blocks(
            self.chat_id,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "more"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "still more"},
            ],
        )
        turn3_stable = "".join(b["text"] for b in turn3 if b["tier"] == "stable")
        turn3_volatile = "".join(b["text"] for b in turn3 if b["tier"] == "volatile")
        self.assertIn("New Name", turn3_stable)
        self.assertNotIn("snapshot=", turn3_volatile)

    def test_a_missing_snapshot_sends_with_no_before(self) -> None:
        source = self._make_character("Ghost Source", body="Gone.")
        self._set_picks(
            used_node_ids=[source],
            used_snapshots=[SnapshotPick(entry_id=source, snapshot_id="not-a-real-snapshot")],
        )
        blocks = self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        text = "".join(b["text"] for b in blocks)
        self.assertNotIn("snapshot=", text)
        self.assertIn(f'id="{source}"', text)  # the live pick still sends fine

    def test_used_mode_carries_no_before(self) -> None:
        picked = self._make_note("Sidebar", body="A picked aside.")
        source = self._make_character("Marek Vell", body="A captain.")
        snap = self.service.capture_snapshot(source, kind="lore", origin="propagation")
        self._set_picks(
            used_node_ids=[picked],
            used_snapshots=[SnapshotPick(entry_id=source, snapshot_id=snap.id)],
            lore_enabled=True,
        )
        prepared = expand_and_prepare_chat_blocks(
            self.service,
            self.chat_id,
            "SYSTEM PROMPT",
            [{"role": "user", "content": "commit"}],
            lore_mode="used",
        )
        text = "".join(b["text"] for b in prepared.system_blocks or [])
        self.assertIn("A picked aside", text)
        self.assertNotIn("snapshot=", text)

    def test_cold_restart_keeps_the_before_stable_seeded_from_seen_revisions(self) -> None:
        source = self._make_character("Marek Vell", body="A captain.")
        snap = self.service.capture_snapshot(source, kind="lore", origin="propagation")
        self._set_picks(used_snapshots=[SnapshotPick(entry_id=source, snapshot_id=snap.id)])
        # Turn 1 settles the before's key into `seen_revisions`.
        self._blocks(self.chat_id, [{"role": "user", "content": "hi"}])
        after_turn1 = self.service.read_chat_session(self.chat_id)
        self.assertIn(snapshot_pick_key(source, snap.id), after_turn1.seen_revisions)

        # Cold restart: drop the in-memory registry, so the next send must
        # seed the baseline from the persisted `seen_revisions`.
        default_registry.clear()
        blocks = self._blocks(self.chat_id, [{"role": "user", "content": "hi again"}])
        stable_text = "".join(b["text"] for b in blocks if b["tier"] == "stable")
        volatile_text = "".join(b["text"] for b in blocks if b["tier"] == "volatile")
        self.assertIn(f'snapshot="{snap.id}"', stable_text)
        self.assertNotIn("snapshot=", volatile_text)
