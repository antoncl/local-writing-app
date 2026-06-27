"""Roleplay Phase C: ai_invocations sidecar log + cost computed field.

The continuation/roleplay accept handler POSTs one invocation record per
accept; per-character cost and the scene-scoped `cost` computed field are
projections from the log.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app, service as global_service


class AIInvocationLogEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Invocation Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_empty_list_when_no_invocations_yet(self) -> None:
        response = self.client.get("/api/ai/invocations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"invocations": []})

    def test_append_persists_record_and_returns_with_id_and_ts(self) -> None:
        response = self.client.post(
            "/api/ai/invocations",
            json={
                "prompt_entry_id": "prompt_1",
                "prompt_entry_type": "continuation",
                "scene_id": "scene_1",
                "provider": "anthropic",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 200,
                    "cache_write_tokens": 0,
                    "output_tokens": 500,
                },
                "cost_usd": 0.0123,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("inv_"))
        self.assertTrue(body["ts"])
        self.assertEqual(body["scene_id"], "scene_1")
        self.assertEqual(body["model"], "claude-opus-4-7")
        self.assertEqual(body["usage"]["input_tokens"], 1000)
        self.assertAlmostEqual(body["cost_usd"], 0.0123, places=6)
        # File on disk.
        log_path = self.root / "ai_invocations.yaml"
        self.assertTrue(log_path.exists())

    def test_list_filters_by_scene_id(self) -> None:
        for scene_id in ("scene_a", "scene_a", "scene_b"):
            self.client.post(
                "/api/ai/invocations",
                json={"scene_id": scene_id, "cost_usd": 0.01},
            )
        response = self.client.get("/api/ai/invocations?scene_id=scene_a")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["invocations"]), 2)
        self.assertTrue(all(inv["scene_id"] == "scene_a" for inv in body["invocations"]))

    def test_list_filters_by_character_id(self) -> None:
        for character_id in ("lore_alice", "lore_bob", "lore_alice"):
            self.client.post(
                "/api/ai/invocations",
                json={
                    "scene_id": "scene_1",
                    "character_id": character_id,
                    "cost_usd": 0.005,
                },
            )
        response = self.client.get(
            "/api/ai/invocations?character_id=lore_alice"
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["invocations"]), 2)
        self.assertTrue(
            all(inv["character_id"] == "lore_alice" for inv in body["invocations"])
        )

    def test_appends_grow_existing_log_rather_than_overwrite(self) -> None:
        for cost in (0.01, 0.02, 0.03):
            self.client.post(
                "/api/ai/invocations",
                json={"scene_id": "scene_1", "cost_usd": cost},
            )
        body = self.client.get("/api/ai/invocations").json()
        self.assertEqual(len(body["invocations"]), 3)
        costs = sorted(inv["cost_usd"] for inv in body["invocations"])
        self.assertEqual(costs, [0.01, 0.02, 0.03])

    def test_malformed_log_records_are_skipped_gracefully(self) -> None:
        self.client.post(
            "/api/ai/invocations",
            json={"scene_id": "scene_1", "cost_usd": 0.04},
        )
        # Hand-corrupt one record in the YAML.
        path = self.root / "ai_invocations.yaml"
        import yaml as _yaml
        data = _yaml.safe_load(path.read_text(encoding="utf-8"))
        data["invocations"].append("not a dict")
        data["invocations"].append({"id": "missing required fields"})
        path.write_text(
            _yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
        )
        # The valid record still comes back; the bad ones are dropped.
        body = self.client.get("/api/ai/invocations").json()
        self.assertEqual(len(body["invocations"]), 1)


class CostComputedFieldTests(unittest.TestCase):
    """`cost` is the third computed-field function. Sums invocations whose
    scene_id matches the scene that's being computed."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Cost Computed Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self) -> str:
        """Create a scene and return its id."""
        response = self.client.post(
            "/api/scenes",
            json={"title": "Untitled scene"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def _read_scene(self, scene_id: str) -> dict:
        response = self.client.get(f"/api/scenes/{scene_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_cost_field_is_zero_when_no_invocations(self) -> None:
        scene_id = self._new_scene()
        scene = self._read_scene(scene_id)
        self.assertIn("cost", scene["computed_metadata"])
        self.assertEqual(scene["computed_metadata"]["cost"], 0.0)

    def test_cost_field_sums_invocations_for_this_scene(self) -> None:
        a = self._new_scene()
        b = self._new_scene()
        # Three for a, one for b.
        for cost in (0.01, 0.02, 0.005):
            self.client.post(
                "/api/ai/invocations",
                json={"scene_id": a, "cost_usd": cost},
            )
        self.client.post(
            "/api/ai/invocations",
            json={"scene_id": b, "cost_usd": 0.99},
        )
        scene_a = self._read_scene(a)
        scene_b = self._read_scene(b)
        self.assertAlmostEqual(
            scene_a["computed_metadata"]["cost"], 0.035, places=6
        )
        self.assertAlmostEqual(
            scene_b["computed_metadata"]["cost"], 0.99, places=6
        )

    def test_cost_field_skips_records_without_numeric_cost(self) -> None:
        scene_id = self._new_scene()
        for payload in (
            {"scene_id": scene_id, "cost_usd": 0.01},
            {"scene_id": scene_id, "cost_usd": None},
            {"scene_id": scene_id},  # cost_usd unset
        ):
            self.client.post("/api/ai/invocations", json=payload)
        scene = self._read_scene(scene_id)
        self.assertAlmostEqual(
            scene["computed_metadata"]["cost"], 0.01, places=6
        )


if __name__ == "__main__":
    unittest.main()
