"""Step 6 of V2: per-chat cost accumulator + per-slot cache write
timestamps, and the project-level rollup endpoint.

Saves are additive — `cost_delta_usd` accumulates into
`ChatSession.cost_usd_total`; `cache_write_slots` stamps the named
slots with the current server time. The /api/ai/project-cost endpoint
sums across all chats.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
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
        self.client = TestClient(app)

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


class ProjectCostEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Project Cost Tests")
        default_registry.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def test_no_chats_returns_zero(self) -> None:
        response = self.client.get("/api/ai/project-cost")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total_usd"], 0.0)
        self.assertEqual(body["chats"], [])

    def test_sum_across_chats(self) -> None:
        def make_with_cost(title: str, cost: float) -> str:
            chat = self.service.create_chat_session(
                CreateChatSessionRequest(title=title, system_prompt="")
            )
            self.service.save_chat_session(
                chat.id,
                SaveChatSessionRequest(
                    title=title,
                    prompt_entry_id="",
                    assistant_id="",
                    system_prompt="",
                    pinned=False,
                    cost_delta_usd=cost,
                ),
            )
            return chat.id

        make_with_cost("Brainstorm", 0.10)
        make_with_cost("Continuation", 0.30)
        make_with_cost("Empty", 0.0)

        response = self.client.get("/api/ai/project-cost")
        body = response.json()
        self.assertAlmostEqual(body["total_usd"], 0.40)
        # Phase C2 Slice B: zero-cost chats don't appear in the per-chat
        # list — the source is the ai_invocations log and zero-delta saves
        # don't append a row. "Empty" is omitted.
        self.assertEqual(len(body["chats"]), 2)
        # Sorted desc by cost.
        self.assertEqual(body["chats"][0]["title"], "Continuation")
        self.assertEqual(body["chats"][1]["title"], "Brainstorm")


if __name__ == "__main__":
    unittest.main()
