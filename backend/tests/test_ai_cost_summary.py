"""GET /api/ai/invocations/summary (#10): project-wide AI spend rollup over
the ai_invocations ledger — totals plus by-model / by-chat / by-scene /
by-day buckets. Costs are summed from stored `cost_usd` verbatim; unpriced
rows (`cost_usd is None`) stay excluded from every sum but still counted
(#697).
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

        llama_bucket = next(b for b in body["by_model"] if b["key"] == "llama3")
        self.assertEqual(llama_bucket["cost_usd"], 0.0)
        self.assertEqual(llama_bucket["count"], 1)
        self.assertEqual(llama_bucket["unpriced_count"], 1)
        self.assertEqual(llama_bucket["input_tokens"], 20)

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


if __name__ == "__main__":
    unittest.main()
