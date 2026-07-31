"""Step 6 of V2: per-chat cost accumulator + per-slot cache write
timestamps.

Saves are additive — `cost_delta_usd` accumulates into
`ChatSession.cost_usd_total`; `cache_write_slots` stamps the named
slots with the current server time.
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

    def test_new_chat_starts_with_zero_cost(self) -> None:
        cid = self._create_chat()
        chat = self.service.read_chat_session(cid)
        self.assertEqual(chat.cost_usd_total, 0.0)
        self.assertEqual(chat.cache_write_times, {})

    def test_cost_delta_accumulates_across_saves(self) -> None:
        cid = self._create_chat()
        self._save(cid, cost_delta_usd=0.0012)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.0012)
        self._save(cid, cost_delta_usd=0.0008)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.0020)
        self._save(cid, cost_delta_usd=0.50)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.5020)

    def test_save_without_cost_delta_preserves_total(self) -> None:
        cid = self._create_chat()
        self._save(cid, cost_delta_usd=0.0050)
        # Plain save (rename, etc.) shouldn't reset the cost.
        self._save(cid)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 0.0050)

    def test_negative_cost_delta_is_clamped_to_zero(self) -> None:
        # Cost is monotonic. A buggy frontend sending -0.5 must not
        # decrement the persisted total.
        cid = self._create_chat()
        self._save(cid, cost_delta_usd=1.0)
        self._save(cid, cost_delta_usd=-0.5)
        self.assertAlmostEqual(self.service.read_chat_session(cid).cost_usd_total, 1.0)

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
