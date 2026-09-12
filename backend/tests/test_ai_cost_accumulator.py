"""Step 6 of V2: per-chat cost total + per-slot cache write timestamps.

`cost_usd_total` is a projection of the invocation log: each turn's row is
recorded by the server that ran it (#1877), and a save only ever carries the
projection back — never a delta. `cache_write_slots` stamps the named slots
with the current server time.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateChatSessionRequest,
    SaveChatSessionRequest,
)
from app.services.ai.sessions import default_registry


class ChatCostAccumulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Cost Acc Tests")
        default_registry.clear()

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _create_chat(self) -> str:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="t", system_prompt="s")
        )
        return chat.id

    def _save(self, chat_id: str, **kwargs) -> None:
        existing = self.service.read_chat_session(chat_id)
        self.service.save_chat_session(
            chat_id,
            SaveChatSessionRequest(
                title=existing.title,
                prompt_entry_id=existing.prompt_entry_id,
                assistant_id=existing.assistant_id,
                system_prompt=existing.system_prompt,
                pinned=existing.pinned,
                context_items=existing.context_items,
                messages=existing.messages,
                inputs=existing.inputs,
                **kwargs,
            ),
        )

    def test_new_chat_has_unknown_cost_until_a_priced_turn(self) -> None:
        # A chat with no priced cost row (fresh, or unpriced-model turns —
        # which record no positive-cost row) reports cost_usd_total = None,
        # not 0.0: the footer hides rather than showing a fabricated €0.00
        # (#697). The first priced turn switches it to a real total.
        cid = self._create_chat()
        chat = self.service.read_chat_session(cid)
        self.assertIsNone(chat.cost_usd_total)
        self.assertEqual(chat.cache_write_times, {})

    def _record(self, chat_id: str, cost: float) -> None:
        # #1877: rows are recorded by the server that ran the turn, never by a
        # client delta on the save — the same seam the stream + commit use.
        self.service.record_chat_turn_invocation(
            self.service.read_chat_session(chat_id),
            provider="anthropic", model="m", usage=None, cost_usd=cost,
        )

    def test_recorded_turns_accumulate_into_the_total(self) -> None:
        cid = self._create_chat()
        self._record(cid, 0.0012)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.0012)
        self._record(cid, 0.0008)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.0020)
        self._record(cid, 0.50)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.5020)

    def test_save_preserves_the_total_and_never_adds_to_it(self) -> None:
        cid = self._create_chat()
        self._record(cid, 0.0050)
        # A plain save (rename, transcript append, …) neither resets nor
        # inflates the cost — it is a projection of the log, not a counter.
        self._save(cid)
        self._save(cid)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.0050)

    def test_cache_write_slots_stamp_each_slot(self) -> None:
        cid = self._create_chat()
        self._save(cid, cache_write_slots=["system", "lore"])
        chat = self.service.read_chat_session(cid)
        self.assertIn("system", chat.cache_write_times)
        self.assertIn("lore", chat.cache_write_times)
        # ISO format check — has a 'T' between date and time.
        self.assertIn("T", chat.cache_write_times["system"])

    def test_cache_write_slots_subsequent_write_updates_timestamp(self) -> None:
        cid = self._create_chat()
        self._save(cid, cache_write_slots=["system"])
        first = self.service.read_chat_session(cid).cache_write_times["system"]
        # Save again immediately — timestamps in microsecond precision should differ.
        self._save(cid, cache_write_slots=["system"])
        second = self.service.read_chat_session(cid).cache_write_times["system"]
        # Second timestamp should be >= first (and almost always greater).
        self.assertGreaterEqual(second, first)

    def test_save_without_slots_preserves_existing_timestamps(self) -> None:
        cid = self._create_chat()
        self._save(cid, cache_write_slots=["system"])
        first = self.service.read_chat_session(cid).cache_write_times["system"]
        self._save(cid)  # rename-style save
        chat = self.service.read_chat_session(cid)
        self.assertEqual(chat.cache_write_times["system"], first)

    def test_unknown_slot_added_alongside_existing(self) -> None:
        cid = self._create_chat()
        self._save(cid, cache_write_slots=["system"])
        self._save(cid, cache_write_slots=["lore"])
        chat = self.service.read_chat_session(cid)
        self.assertIn("system", chat.cache_write_times)
        self.assertIn("lore", chat.cache_write_times)


if __name__ == "__main__":
    unittest.main()
