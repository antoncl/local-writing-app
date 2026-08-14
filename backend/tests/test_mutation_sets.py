"""Mutation-set Node kind CRUD (#62). A reusable, body-less kind: an
ordered list of (field, op, value) rows + a target lore entry-type, stored in
front matter under `mutation-sets/`. The entity is bound at apply time, so a
set is a template. Exercises the routes end-to-end.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateMutationSetEntryRequest, MutationSetRow


class MutationSetCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Mutation Set Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create(self, title: str, target: str, rows: list[dict]) -> dict:
        res = self.client.post(
            "/api/mutation-sets",
            json={"title": title, "target_entry_type": target, "rows": rows},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_create_read_roundtrips_rows_and_target(self) -> None:
        created = self._create(
            "Full Moon",
            "lore:character",
            [
                {"field": "title", "op": "replace", "value": "The Wolf"},
                {"field": "clues", "op": "add", "value": "fur"},
            ],
        )
        self.assertTrue(created["id"].startswith("mutation_set"))
        self.assertEqual(created["target_entry_type"], "lore:character")
        self.assertEqual([r["field"] for r in created["rows"]], ["title", "clues"])
        self.assertEqual(created["rows"][1]["op"], "add")

        got = self.client.get(f"/api/mutation-sets/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["rows"], created["rows"])

    def test_stored_body_less_under_mutation_sets_folder(self) -> None:
        created = self._create("Promotion", "lore:character", [{"field": "rank", "value": "Captain"}])
        files = list((self.root / "mutation-sets").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        # Rows + target live in front matter; there is no prose body.
        self.assertIn("target_entry_type: lore:character", text)
        self.assertIn("rank", text)
        del created

    def test_list_reports_row_count_and_target(self) -> None:
        self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        self._create("Relocate", "lore:location", [{"field": "title", "value": "Ruins"}, {"field": "status", "value": "razed"}])
        listing = self.client.get("/api/mutation-sets").json()["entries"]
        by_title = {e["title"]: e for e in listing}
        self.assertEqual(by_title["Full Moon"]["row_count"], 1)
        self.assertEqual(by_title["Relocate"]["row_count"], 2)
        self.assertEqual(by_title["Relocate"]["target_entry_type"], "lore:location")

    def test_save_updates_rows(self) -> None:
        created = self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        res = self.client.put(
            f"/api/mutation-sets/{created['id']}",
            json={
                "title": "Full Moon",
                "target_entry_type": "lore:character",
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
        created = self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        res = self.client.delete(f"/api/mutation-sets/{created['id']}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["entries"], [])
        self.assertEqual(self.client.get(f"/api/mutation-sets/{created['id']}").status_code, 404)

    def test_mutation_set_node_is_indexed_by_kind(self) -> None:
        created = self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        index = self.service._build_node_index()
        entry = index.by_id.get(created["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, "mutation_set")


class MutationSetEntityPinTests(unittest.TestCase):
    """The optional entity pin (ADR-0055 §3): a `target_entity` `entity_ref`
    stored in `metadata` (not the top-level front matter that carries
    target_entry_type/rows), so it rides the kind-neutral edge machinery — a
    set→subject reverse edge and reference-integrity — while a reusable
    (un-pinned) set stays byte-identical to today's."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Pin Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_character(self, node_id: str, title: str = "Mira") -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.root / "lore" / f"{node_id}.md",
            {"id": node_id, "title": title, "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

    def _set_file(self) -> Path:
        files = list((self.root / "mutation-sets").glob("*.md"))
        self.assertEqual(len(files), 1)
        return files[0]

    def test_pin_roundtrips_through_metadata(self) -> None:
        self._write_character("mira")
        created = self.client.post(
            "/api/mutation-sets",
            json={
                "title": "Becomes a werewolf",
                "target_entry_type": "lore:character",
                "target_entity": "mira",
                "rows": [{"field": "title", "value": "The Wolf"}],
            },
        ).json()
        self.assertEqual(created["target_entity"], "mira")
        self.assertEqual(
            self.client.get(f"/api/mutation-sets/{created['id']}").json()["target_entity"], "mira"
        )
        self.assertEqual(
            self.client.get("/api/mutation-sets").json()["entries"][0]["target_entity"], "mira"
        )
        # The pin lives in `metadata`; rows/target stay top-level.
        text = self._set_file().read_text(encoding="utf-8")
        self.assertIn("target_entity: mira", text)
        self.assertIn("target_entry_type: lore:character", text)

    def test_reusable_set_writes_no_metadata_block(self) -> None:
        created = self.client.post(
            "/api/mutation-sets",
            json={
                "title": "Any promotion",
                "target_entry_type": "lore:character",
                "rows": [{"field": "rank", "value": "Captain"}],
            },
        ).json()
        self.assertEqual(created["target_entity"], "")
        # omit_empty_metadata keeps an un-pinned set's file free of a metadata block.
        self.assertNotIn("metadata:", self._set_file().read_text(encoding="utf-8"))

    def test_pin_emits_a_set_to_subject_reverse_edge(self) -> None:
        self._write_character("mira")
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Werewolf",
                target_entry_type="lore:character",
                target_entity="mira",
                rows=[MutationSetRow(field="title", value="The Wolf")],
            )
        )
        reverse = self.service._build_node_index().edges_by_dst.get("mira", [])
        self.assertIn(created.id, [edge.src for edge in reverse])
        self.assertIn("target_entity", [edge.field_id for edge in reverse])

    def test_deleting_the_pinned_entity_purges_the_pin(self) -> None:
        self._write_character("mira")
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Werewolf",
                target_entry_type="lore:character",
                target_entity="mira",
                rows=[MutationSetRow(field="title", value="The Wolf")],
            )
        )
        set_path = self._set_file()
        self.assertIn("target_entity: mira", set_path.read_text(encoding="utf-8"))

        self.service.delete_lore_entry("mira")

        # Reference-integrity (ADR-0055 §3): the pin is purged like any other
        # metadata entity_ref, not left silently dangling. Rows survive.
        purged = self.service.read_mutation_set_entry(created.id)
        self.assertEqual(purged.target_entity, "")
        self.assertEqual([row.field for row in purged.rows], ["title"])
        self.assertNotIn("mira", set_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
