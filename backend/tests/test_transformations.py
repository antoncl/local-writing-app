"""Transformation-set Node kind CRUD (#62). A reusable, body-less kind: an
ordered list of (field, op, value) rows + a target lore entry-type, stored in
front matter under `transformations/`. The entity is bound at apply time, so a
set is a template. Exercises the routes end-to-end.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as svc


class TransformationCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Transformation Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create(self, title: str, target: str, rows: list[dict]) -> dict:
        res = self.client.post(
            "/api/transformations",
            json={"title": title, "target_entry_type": target, "rows": rows},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_create_read_roundtrips_rows_and_target(self) -> None:
        created = self._create(
            "Full Moon",
            "character",
            [
                {"field": "title", "op": "replace", "value": "The Wolf"},
                {"field": "clues", "op": "add", "value": "fur"},
            ],
        )
        self.assertTrue(created["id"].startswith("transformation"))
        self.assertEqual(created["target_entry_type"], "character")
        self.assertEqual([r["field"] for r in created["rows"]], ["title", "clues"])
        self.assertEqual(created["rows"][1]["op"], "add")

        got = self.client.get(f"/api/transformations/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["rows"], created["rows"])

    def test_stored_body_less_under_transformations_folder(self) -> None:
        created = self._create("Promotion", "character", [{"field": "rank", "value": "Captain"}])
        files = list((self.root / "transformations").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        # Rows + target live in front matter; there is no prose body.
        self.assertIn("target_entry_type: character", text)
        self.assertIn("rank", text)
        del created

    def test_list_reports_row_count_and_target(self) -> None:
        self._create("Full Moon", "character", [{"field": "title", "value": "The Wolf"}])
        self._create("Relocate", "place", [{"field": "title", "value": "Ruins"}, {"field": "status", "value": "razed"}])
        listing = self.client.get("/api/transformations").json()["entries"]
        by_title = {e["title"]: e for e in listing}
        self.assertEqual(by_title["Full Moon"]["row_count"], 1)
        self.assertEqual(by_title["Relocate"]["row_count"], 2)
        self.assertEqual(by_title["Relocate"]["target_entry_type"], "place")

    def test_save_updates_rows(self) -> None:
        created = self._create("Full Moon", "character", [{"field": "title", "value": "The Wolf"}])
        res = self.client.put(
            f"/api/transformations/{created['id']}",
            json={
                "title": "Full Moon",
                "target_entry_type": "character",
                "rows": [
                    {"field": "title", "op": "replace", "value": "The Grey Wolf"},
                    {"field": "abilities", "op": "add", "value": "night vision"},
                ],
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(res.json()["rows"]), 2)
        self.assertEqual(res.json()["rows"][0]["value"], "The Grey Wolf")

    def test_delete_removes_the_set(self) -> None:
        created = self._create("Full Moon", "character", [{"field": "title", "value": "The Wolf"}])
        res = self.client.delete(f"/api/transformations/{created['id']}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["entries"], [])
        self.assertEqual(self.client.get(f"/api/transformations/{created['id']}").status_code, 404)

    def test_transformation_node_is_indexed_by_kind(self) -> None:
        created = self._create("Full Moon", "character", [{"field": "title", "value": "The Wolf"}])
        index = svc._build_node_index()
        entry = index.by_id.get(created["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, "transformation")


if __name__ == "__main__":
    unittest.main()
