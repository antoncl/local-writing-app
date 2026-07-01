"""Validation tests for mutation values (#53, #33).

A mutation value is a field value (ADR-0007): it must target a real lore entity,
name a field defined for that entity's entry_type, and satisfy that field's
constraints — exactly as a base value does. Enforced on three paths that share
one scan — `save_scene` (PUT), `update_mutation` (PATCH), and `validate_project`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as svc
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)


def _define_field(field_id: str, field_type: str, entry_type: str = "character") -> None:
    layers = svc.read_metadata_schema_layers()
    svc.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=field_id.title(), type=field_type),
            entry_type=entry_type,
        )
    )


class MutationSaveValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Mutation Validation Tests")
        # Real character + a couple of character-scoped fields to mutate against.
        _define_field("rank", "number")
        _define_field("mentor", "entity_ref")
        self.char = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Rey", entry_type="character")
        ).id
        self.client = TestClient(app)
        self.scene_id = self.client.post("/api/scenes", json={"title": "Chapter One"}).json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _marker(self, field: str, value: str, entity: str | None = None, marker_id: str = "m1") -> str:
        return (
            f"<!-- mutate:entity={entity or self.char};field={field};"
            f"value={value};id={marker_id} -->"
        )

    def _save(self, body: str):
        return self.client.put(
            f"/api/scenes/{self.scene_id}", json={"title": "Chapter One", "body": body}
        )

    # --- accepted --------------------------------------------------------

    def test_valid_select_value_saves(self) -> None:
        # context_policy is a built-in select on lore entries.
        self.assertEqual(self._save(self._marker("context_policy", "manual_only")).status_code, 200)

    def test_number_string_is_coerced_and_saves(self) -> None:
        self.assertEqual(self._save(self._marker("rank", "5")).status_code, 200)

    def test_intrinsic_title_saves(self) -> None:
        self.assertEqual(self._save(self._marker("title", "Master%20Rey")).status_code, 200)

    # --- rejected --------------------------------------------------------

    def test_select_value_outside_options_is_422(self) -> None:
        response = self._save(self._marker("context_policy", "bogus"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("one of", response.text)

    def test_non_numeric_number_value_is_422(self) -> None:
        response = self._save(self._marker("rank", "abc"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("must be a number", response.text)

    def test_unknown_field_is_422(self) -> None:
        response = self._save(self._marker("nonexistent_field", "x"))
        self.assertEqual(response.status_code, 422, response.text)

    def test_field_from_another_entry_type_is_422(self) -> None:
        # `status` is a scene field, not a character field — parity with base
        # metadata validation (ADR-0007).
        response = self._save(self._marker("status", "draft"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("not defined for entry_type", response.text)

    def test_unknown_entity_is_422(self) -> None:
        response = self._save(self._marker("rank", "5", entity="lore_ghost"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("unknown lore entity", response.text)

    def test_entity_ref_to_missing_entity_is_422(self) -> None:
        response = self._save(self._marker("mentor", "lore_does_not_exist"))
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_bad_marker_blocks_the_whole_save(self) -> None:
        self._save(self._marker("context_policy", "bogus"))
        self.assertEqual(svc.read_scene(self.scene_id).body, "")


class MutationProjectValidationTests(unittest.TestCase):
    """validate_project reports a bad marker already on disk (written outside
    the save guard)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Project Validation Tests")
        self.char = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Rey", entry_type="character")
        ).id
        self.client = TestClient(app)
        self.scene_id = self.client.post("/api/scenes", json={"title": "Chapter One"}).json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_validate_project_flags_bad_marker_on_disk(self) -> None:
        path = svc._path_for_node_id(self.scene_id, "scene")
        marker = (
            f"<!-- mutate:entity={self.char};field=context_policy;value=bogus;id=m1 -->"
        )
        path.write_text(path.read_text() + "\n" + marker, encoding="utf-8")
        report = svc.validate_project()
        self.assertTrue(
            any("context_policy" in err and "one of" in err for err in report.errors),
            report.errors,
        )


if __name__ == "__main__":
    unittest.main()
