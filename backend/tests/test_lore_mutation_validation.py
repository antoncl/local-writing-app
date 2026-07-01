"""Validation tests for mutation values (#53, #33).

A mutation value is a field value (ADR-0007): it must satisfy the target field's
constraints exactly as a base value does. Enforced on two paths that share one
scan — `save_scene` (a bad value is rejected 422 on save) and `validate_project`
(a bad value already on disk is reported).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as svc


def _marker(field: str, value: str, marker_id: str = "m1", entity: str = "lore_x") -> str:
    return f"<!-- mutate:entity={entity};field={field};value={value};id={marker_id} -->"


class MutationSaveValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Mutation Validation Tests")
        self.client = TestClient(app)
        created = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.assertEqual(created.status_code, 200, created.text)
        self.scene_id = created.json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _save(self, body: str):
        return self.client.put(
            f"/api/scenes/{self.scene_id}", json={"title": "Chapter One", "body": body}
        )

    # --- accepted --------------------------------------------------------

    def test_valid_select_value_saves(self) -> None:
        self.assertEqual(self._save(_marker("status", "revised")).status_code, 200)

    def test_number_string_is_coerced_and_saves(self) -> None:
        # target_word_count is a number field; "500" coerces and validates.
        self.assertEqual(self._save(_marker("target_word_count", "500")).status_code, 200)

    # --- rejected --------------------------------------------------------

    def test_select_value_outside_options_is_422(self) -> None:
        response = self._save(_marker("status", "bogus"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("one of", response.text)

    def test_non_numeric_number_value_is_422(self) -> None:
        response = self._save(_marker("target_word_count", "abc"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("must be a number", response.text)

    def test_unknown_field_is_422(self) -> None:
        response = self._save(_marker("nonexistent_field", "x"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("unknown field", response.text)

    def test_entity_ref_to_missing_entity_is_422(self) -> None:
        response = self._save(_marker("pov", "lore_does_not_exist"))
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_bad_marker_blocks_the_whole_save(self) -> None:
        # One invalid marker rejects the save; the body is not persisted.
        self._save(_marker("status", "bogus"))
        self.assertEqual(svc.read_scene(self.scene_id).body, "")


class MutationProjectValidationTests(unittest.TestCase):
    """validate_project reports a bad marker already on disk (written outside
    the save guard)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Project Validation Tests")
        self.client = TestClient(app)
        created = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.scene_id = created.json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_validate_project_flags_bad_marker_on_disk(self) -> None:
        path = svc._path_for_node_id(self.scene_id, "scene")
        # Append a marker with an invalid select value straight into the file,
        # bypassing save_scene's guard.
        path.write_text(path.read_text() + "\n" + _marker("status", "bogus"), encoding="utf-8")
        report = svc.validate_project()
        self.assertTrue(
            any("status" in err and "one of" in err for err in report.errors),
            report.errors,
        )


if __name__ == "__main__":
    unittest.main()
