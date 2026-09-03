"""GET /api/ai/invocations/summary (#10): project-wide AI spend rollup over
the ai_invocations ledger — totals plus by-model / by-chat / by-scene /
by-day buckets. Costs are summed from stored `cost_usd` verbatim; unpriced
rows stay excluded from every sum but still counted, and a scope with rows
but no priced row reports cost None rather than 0.0 (#697). Rows are read
raw with the same tolerant semantics as the scene/character/project computed
costs, so the surfaces can never disagree about which rows count.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app


class AICostSummaryEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Cost Summary Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_rows(self, rows: list[dict]) -> None:
        """Hand-craft the sidecar log so tests can control `ts` and
        `chat_session_id`/`scene_id` freely — the append endpoint always
        stamps `ts` itself.
        """
        path = self.root / "ai_invocations.yaml"
        existing: list[dict] = []
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            existing = list(data.get("invocations", []))
        path.write_text(
            yaml.safe_dump({"invocations": existing + rows}, sort_keys=False),
            encoding="utf-8",
        )

    def test_empty_project_has_zero_totals_and_empty_buckets(self) -> None:
        response = self.client.get("/api/ai/invocations/summary")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total_cost_usd"], 0.0)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["unpriced_count"], 0)
        self.assertEqual(body["input_tokens"], 0)
        self.assertEqual(body["output_tokens"], 0)
        self.assertEqual(body["by_model"], [])
        self.assertEqual(body["by_chat"], [])
        self.assertEqual(body["by_scene"], [])
        self.assertEqual(body["by_prompt"], [])
        self.assertEqual(body["by_day"], [])

    def test_mixed_rows_aggregate_totals_and_by_model_ordering(self) -> None:
        self._write_rows(
            [
                {
                    "id": "inv_1",
                    "ts": "2026-08-01T10:00:00+00:00",
                    "model": "claude-opus",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 10,
                        "cache_write_tokens": 5,
                        "output_tokens": 50,
                    },
                    "cost_usd": 0.10,
                },
                {
                    "id": "inv_2",
                    "ts": "2026-08-02T10:00:00+00:00",
                    "model": "claude-opus",
                    "usage": {
                        "input_tokens": 200,
                        "cached_input_tokens": 0,
                        "cache_write_tokens": 0,
                        "output_tokens": 75,
                    },
                    "cost_usd": 0.30,
                },
                {
                    "id": "inv_3",
                    "ts": "2026-08-02T11:00:00+00:00",
                    "model": "gpt-5",
                    "usage": {
                        "input_tokens": 50,
                        "cached_input_tokens": 0,
                        "cache_write_tokens": 0,
                        "output_tokens": 25,
                    },
                    "cost_usd": 0.05,
                },
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertAlmostEqual(body["total_cost_usd"], 0.45, places=6)
        self.assertEqual(body["count"], 3)
        self.assertEqual(body["unpriced_count"], 0)
        # input = sum of the three input slots across all rows.
        self.assertEqual(body["input_tokens"], 100 + 10 + 5 + 200 + 50)
        self.assertEqual(body["output_tokens"], 50 + 75 + 25)

        by_model = body["by_model"]
        self.assertEqual(len(by_model), 2)
        # Highest cost first: claude-opus (0.40) before gpt-5 (0.05).
        self.assertEqual(by_model[0]["key"], "claude-opus")
        self.assertAlmostEqual(by_model[0]["cost_usd"], 0.40, places=6)
        self.assertEqual(by_model[0]["count"], 2)
        self.assertEqual(by_model[1]["key"], "gpt-5")
        self.assertAlmostEqual(by_model[1]["cost_usd"], 0.05, places=6)

        # Newest day first.
        by_day = body["by_day"]
        self.assertEqual([b["key"] for b in by_day], ["2026-08-02", "2026-08-01"])
        self.assertAlmostEqual(by_day[0]["cost_usd"], 0.35, places=6)
        self.assertAlmostEqual(by_day[1]["cost_usd"], 0.10, places=6)

    def test_unpriced_row_excluded_from_cost_but_counted(self) -> None:
        self._write_rows(
            [
                {
                    "id": "inv_priced",
                    "ts": "2026-08-01T10:00:00+00:00",
                    "model": "claude-opus",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 0,
                        "cache_write_tokens": 0,
                        "output_tokens": 50,
                    },
                    "cost_usd": 0.10,
                },
                {
                    "id": "inv_unpriced",
                    "ts": "2026-08-01T11:00:00+00:00",
                    "model": "llama3",
                    "usage": {
                        "input_tokens": 20,
                        "cached_input_tokens": 0,
                        "cache_write_tokens": 0,
                        "output_tokens": 10,
                    },
                    "cost_usd": None,
                },
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        body = response.json()
        self.assertAlmostEqual(body["total_cost_usd"], 0.10, places=6)
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["unpriced_count"], 1)
        # Tokens still counted for the unpriced row.
        self.assertEqual(body["input_tokens"], 120)
        self.assertEqual(body["output_tokens"], 60)

        # A bucket with no priced row reports None, not 0.0 — the frontend
        # renders it as "—" straight off the wire (#697).
        llama_bucket = next(b for b in body["by_model"] if b["key"] == "llama3")
        self.assertIsNone(llama_bucket["cost_usd"])
        self.assertEqual(llama_bucket["count"], 1)
        self.assertEqual(llama_bucket["unpriced_count"], 1)
        self.assertEqual(llama_bucket["input_tokens"], 20)

    def test_all_unpriced_scope_reports_none_total_not_zero(self) -> None:
        self._write_rows(
            [
                {"id": "inv_1", "ts": "2026-08-01T10:00:00+00:00", "model": "llama3"},
                {"id": "inv_2", "ts": "2026-08-02T10:00:00+00:00", "model": "llama3"},
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["unpriced_count"], 2)
        # Rows exist but none is priced: unknown, not a known zero.
        self.assertIsNone(body["total_cost_usd"])

    def test_malformed_row_counted_like_the_sibling_summers(self) -> None:
        # A hand-edited row that would fail AIInvocation validation (usage is
        # a string, no ts) must still be counted the way the computed cost
        # fields count it — priced rows sum, junk fields degrade to defaults.
        self._write_rows(
            [
                {"id": "inv_ok", "ts": "2026-08-01T10:00:00+00:00", "cost_usd": 0.10},
                {"cost_usd": 0.25, "usage": "garbage", "model": 7},
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertAlmostEqual(body["total_cost_usd"], 0.35, places=6)
        # The junk model field degrades to the unknown-model bucket; the
        # ts-less row lands in no day bucket.
        labels = [b["label"] for b in body["by_model"]]
        self.assertIn("unknown model", labels)
        self.assertEqual([b["key"] for b in body["by_day"]], ["2026-08-01"])

    def test_malformed_date_bounds_are_rejected_not_silently_empty(self) -> None:
        self._write_rows(
            [{"id": "inv_1", "ts": "2026-08-30T10:00:00+00:00", "cost_usd": 0.10}]
        )
        # Unpadded/garbage dates would compare lexicographically and return an
        # all-zero 200; the pattern guard must 422 them instead.
        for bad in ("2026-8-1", "30/08/2026", "yesterday"):
            response = self.client.get(f"/api/ai/invocations/summary?since={bad}")
            self.assertEqual(response.status_code, 422, bad)

    def test_since_and_until_filter_by_inclusive_day_bounds(self) -> None:
        self._write_rows(
            [
                {"id": "inv_1", "ts": "2026-08-01T10:00:00+00:00", "cost_usd": 0.10},
                {"id": "inv_2", "ts": "2026-08-02T10:00:00+00:00", "cost_usd": 0.20},
                {"id": "inv_3", "ts": "2026-08-03T10:00:00+00:00", "cost_usd": 0.30},
            ]
        )
        # since == until == the middle day only.
        response = self.client.get(
            "/api/ai/invocations/summary?since=2026-08-02&until=2026-08-02"
        )
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertAlmostEqual(body["total_cost_usd"], 0.20, places=6)

        # since-only: the last two days.
        response = self.client.get("/api/ai/invocations/summary?since=2026-08-02")
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertAlmostEqual(body["total_cost_usd"], 0.50, places=6)

        # until-only: the first two days.
        response = self.client.get("/api/ai/invocations/summary?until=2026-08-02")
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertAlmostEqual(body["total_cost_usd"], 0.30, places=6)

    def test_chat_bucket_falls_back_to_id_when_no_title(self) -> None:
        self._write_rows(
            [
                {
                    "id": "inv_1",
                    "ts": "2026-08-01T10:00:00+00:00",
                    "chat_session_id": "chat_nonexistent",
                    "prompt_entry_id": "prompt_nonexistent",
                    "cost_usd": 0.10,
                },
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        body = response.json()
        self.assertEqual(len(body["by_chat"]), 1)
        self.assertEqual(body["by_chat"][0]["key"], "chat_nonexistent")
        self.assertEqual(body["by_chat"][0]["label"], "chat_nonexistent")
        # by_prompt falls back to the id the same way when no title resolves.
        self.assertEqual(len(body["by_prompt"]), 1)
        self.assertEqual(body["by_prompt"][0]["key"], "prompt_nonexistent")
        self.assertEqual(body["by_prompt"][0]["label"], "prompt_nonexistent")

    def test_chat_bucket_uses_real_session_title_when_present(self) -> None:
        from app.models import CreateChatSessionRequest

        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="Plot brainstorm", system_prompt="")
        )
        self._write_rows(
            [
                {
                    "id": "inv_1",
                    "ts": "2026-08-01T10:00:00+00:00",
                    "chat_session_id": chat.id,
                    "cost_usd": 0.10,
                },
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        body = response.json()
        self.assertEqual(len(body["by_chat"]), 1)
        self.assertEqual(body["by_chat"][0]["key"], chat.id)
        self.assertEqual(body["by_chat"][0]["label"], "Plot brainstorm")

    def test_empty_chat_scene_and_prompt_ids_do_not_create_buckets(self) -> None:
        self._write_rows(
            [
                {
                    "id": "inv_1",
                    "ts": "2026-08-01T10:00:00+00:00",
                    "chat_session_id": "",
                    "scene_id": "",
                    "prompt_entry_id": "",
                    "cost_usd": 0.10,
                },
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        body = response.json()
        self.assertEqual(body["by_chat"], [])
        self.assertEqual(body["by_scene"], [])
        self.assertEqual(body["by_prompt"], [])

    def test_scene_bucket_present_for_non_empty_scene_id(self) -> None:
        self._write_rows(
            [
                {
                    "id": "inv_1",
                    "ts": "2026-08-01T10:00:00+00:00",
                    "scene_id": "scene_abc",
                    "cost_usd": 0.10,
                },
                {
                    "id": "inv_2",
                    "ts": "2026-08-01T11:00:00+00:00",
                    "scene_id": "scene_abc",
                    "cost_usd": 0.05,
                },
            ]
        )
        response = self.client.get("/api/ai/invocations/summary")
        body = response.json()
        self.assertEqual(len(body["by_scene"]), 1)
        self.assertEqual(body["by_scene"][0]["key"], "scene_abc")
        self.assertEqual(body["by_scene"][0]["label"], "scene_abc")
        self.assertAlmostEqual(body["by_scene"][0]["cost_usd"], 0.15, places=6)
        self.assertEqual(body["by_scene"][0]["count"], 2)

    # --- #1708: the three ledger summers now share one scan + reducer, so a
    # per-chat/per-scene figure and its matching summary bucket must agree.
    # These pin that agreement so a future edit to one summer can't drift.

    def _bucket(self, breakdown: str, key: str) -> dict:
        body = self.client.get("/api/ai/invocations/summary").json()
        return next(b for b in body[breakdown] if b["key"] == key)

    def test_per_chat_total_agrees_with_by_chat_bucket(self) -> None:
        from app.models import CreateChatSessionRequest

        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="c", system_prompt="")
        )
        self._write_rows(
            [
                {"id": "r1", "ts": "2026-08-01T10:00:00+00:00",
                 "chat_session_id": chat.id, "cost_usd": 0.02},
                {"id": "r2", "ts": "2026-08-01T11:00:00+00:00",
                 "chat_session_id": chat.id, "cost_usd": None},
                {"id": "r3", "ts": "2026-08-01T12:00:00+00:00",
                 "chat_session_id": chat.id, "cost_usd": 0.03},
            ]
        )
        projection = self.service.read_chat_session(chat.id).cost_usd_total
        self.assertAlmostEqual(projection, 0.05, places=6)
        self.assertAlmostEqual(self._bucket("by_chat", chat.id)["cost_usd"], projection, places=6)

    def test_per_chat_unknown_total_agrees_with_by_chat_bucket(self) -> None:
        # Only-unpriced chat: both the projection and the bucket report None
        # (not 0.0) through the shared reducer (#697).
        from app.models import CreateChatSessionRequest

        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="c", system_prompt="")
        )
        self._write_rows(
            [
                {"id": "r1", "ts": "2026-08-01T10:00:00+00:00",
                 "chat_session_id": chat.id, "cost_usd": None},
            ]
        )
        self.assertIsNone(self.service.read_chat_session(chat.id).cost_usd_total)
        self.assertIsNone(self._bucket("by_chat", chat.id)["cost_usd"])

    def test_scene_computed_cost_agrees_with_by_scene_bucket(self) -> None:
        self._write_rows(
            [
                {"id": "r1", "ts": "2026-08-01T10:00:00+00:00",
                 "scene_id": "scene_x", "cost_usd": 0.04},
                {"id": "r2", "ts": "2026-08-01T11:00:00+00:00",
                 "scene_id": "scene_x", "cost_usd": None},
            ]
        )
        computed = self.service._compute_invocation_cost("scene", "scene_x")
        self.assertAlmostEqual(computed, 0.04, places=6)
        self.assertAlmostEqual(self._bucket("by_scene", "scene_x")["cost_usd"], computed, places=6)


if __name__ == "__main__":
    unittest.main()
