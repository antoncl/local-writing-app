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
from mutation_helpers import save_scenes_with_mutations
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService


def _define_field(service: ProjectService, field_id: str, field_type: str, entry_type: str = "lore:character") -> None:
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
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
        self.service = open_test_project(self.root, "Mutation Validation Tests")
        _define_field(self.service, "rank", "number")
        self.char = self.service.create_lore_entry(
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

    def _authored(self, field: str, value: str, entity: str | None = None) -> None:
        """Author one legacy marker and move it into a set + anchor
        (ADR-0095), the way an existing project's scene would after
        migration — the position-free set save never blocks (§4), matching
        what the retired scene-marker save never blocked on either."""
        save_scenes_with_mutations(
            self.service, {self.scene_id: self._marker(field, value, entity)}
        )

    def _warnings(self) -> list[str]:
        return self.service.validate_project().warnings

    # --- saves never block ------------------------------------------------

    def test_bad_select_value_still_saves(self) -> None:
        self._authored("context_policy", "bogus")  # raises on failure

    def test_non_numeric_number_still_saves(self) -> None:
        self._authored("rank", "abc")

    def test_unknown_entity_still_saves(self) -> None:
        self._authored("rank", "5", entity="lore_ghost")

    def test_valid_marker_saves_with_no_warnings(self) -> None:
        self._authored("rank", "5")
        self.assertFalse([w for w in self._warnings() if "mutation" in w.lower()])

    # --- validate_project reports strays as warnings ---------------------

    def test_bad_select_value_is_a_warning(self) -> None:
        self._authored("context_policy", "bogus")
        self.assertTrue(any("context_policy" in w and "one of" in w for w in self._warnings()))

    def test_field_from_another_entry_type_is_a_warning(self) -> None:
        # `status` is a scene field, not a character field.
        self._authored("status", "draft")
        self.assertTrue(any("not defined for entry_type" in w for w in self._warnings()))

    def test_unknown_entity_is_a_warning(self) -> None:
        # A dead pin (ADR-0095 §2/§Verify): the entity no longer exists, so
        # the anchor's set contributes nothing and Verify names it.
        self._authored("rank", "5", entity="lore_ghost")
        self.assertTrue(any("entity no longer exists" in w for w in self._warnings()))

    def test_warnings_do_not_appear_in_errors(self) -> None:
        self._authored("context_policy", "bogus")
        report = self.service.validate_project()
        self.assertFalse(any("context_policy" in e for e in report.errors), report.errors)


if __name__ == "__main__":
    unittest.main()
