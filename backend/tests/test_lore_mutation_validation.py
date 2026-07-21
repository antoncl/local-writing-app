"""Advisory validation tests for mutation values (#53, #33).

A mutation value is a field value (ADR-0007), but validation is **advisory** — a
bad value NEVER blocks a scene save (that would be user-hostile). Saves always
succeed; `validate_project` surfaces strays as warnings. The authoring UI's typed
widgets keep values well-formed at the source.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)
from app.runtime import service as svc


def _define_field(field_id: str, field_type: str, entry_type: str = "lore:character") -> None:
    layers = svc.read_metadata_schema_layers()
    svc.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=field_id.title(), type=field_type),
            entry_type=entry_type,
        )
    )


class MutationAdvisoryValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        svc.__init__()
        svc.create_project(self.root, "Mutation Validation Tests")
        _define_field("rank", "number")
        self.char = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Rey", entry_type="lore:character")
        ).id
        self.client = TestClient(app)
        self.scene_id = self.client.post("/api/scenes", json={"title": "Chapter One"}).json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _marker(self, field: str, value: str, entity: str | None = None) -> str:
        return (
            f"<!-- mutate:entity={entity or self.char};field={field};value={value};id=m1 -->"
        )

    def _save(self, body: str):
        return self.client.put(
            f"/api/scenes/{self.scene_id}", json={"title": "Chapter One", "body": body}
        )

    def _warnings(self) -> list[str]:
        return svc.validate_project().warnings

    # --- saves never block ------------------------------------------------

    def test_bad_select_value_still_saves(self) -> None:
        self.assertEqual(self._save(self._marker("context_policy", "bogus")).status_code, 200)

    def test_non_numeric_number_still_saves(self) -> None:
        self.assertEqual(self._save(self._marker("rank", "abc")).status_code, 200)

    def test_unknown_entity_still_saves(self) -> None:
        self.assertEqual(self._save(self._marker("rank", "5", entity="lore_ghost")).status_code, 200)

    def test_valid_marker_saves_with_no_warnings(self) -> None:
        self.assertEqual(self._save(self._marker("rank", "5")).status_code, 200)
        self.assertFalse([w for w in self._warnings() if "mutation" in w])

    # --- validate_project reports strays as warnings ---------------------

    def test_bad_select_value_is_a_warning(self) -> None:
        self._save(self._marker("context_policy", "bogus"))
        self.assertTrue(any("context_policy" in w and "one of" in w for w in self._warnings()))

    def test_field_from_another_entry_type_is_a_warning(self) -> None:
        # `status` is a scene field, not a character field.
        self._save(self._marker("status", "draft"))
        self.assertTrue(any("not defined for entry_type" in w for w in self._warnings()))

    def test_unknown_entity_is_a_warning(self) -> None:
        self._save(self._marker("rank", "5", entity="lore_ghost"))
        self.assertTrue(any("unknown lore entity" in w for w in self._warnings()))

    def test_warnings_do_not_appear_in_errors(self) -> None:
        self._save(self._marker("context_policy", "bogus"))
        report = svc.validate_project()
        self.assertFalse(any("context_policy" in e for e in report.errors), report.errors)


if __name__ == "__main__":
    unittest.main()
