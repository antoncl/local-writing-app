"""The layer walk stops at `projects_base_folder` (#326).

`settings.projects_base_folder` declares the shelf root — the longest possible
upward traversal, and `_validate_projects_base_folder` enforces exactly that when
a base folder is written. The read path used to exceed it: when the configured
base happened to equal `root.parent`, `_metadata_schema_base_folder` scanned for
the outermost ancestor carrying a `metadata.schema.yaml` and started the walk
there instead, so a stray schema file in a grandparent silently lengthened the
chain.

That matters beyond the schema, because `_project_layer_folders` is the single
walk behind the layered schema, the node index, and (from #312) AI policy.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.project_service import ProjectService


class LayerWalkBoundTests(unittest.TestCase):
    """Layout: <tmp>/shelf/universe/book, `book` is the project."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.shelf = Path(self.temp_dir.name) / "shelf"
        self.universe = self.shelf / "universe"
        self.root = self.universe / "book"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set_base(self, folder: Path) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(folder)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def _chain(self) -> list[str]:
        return [folder.name for folder in self.service._project_layer_folders(self.root)]

    def _write_schema(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.service._write_yaml(folder / "metadata.schema.yaml", {"version": 1})

    def test_walk_spans_root_to_configured_base_inclusive(self) -> None:
        self._set_base(self.shelf)

        self.assertEqual(self._chain(), ["shelf", "universe", "book"])

    def test_default_base_of_root_parent_yields_exactly_parent_and_root(self) -> None:
        # create_project defaults the base to root.parent; that is a two-layer
        # chain, not an invitation to look further up.
        self._set_base(self.universe)

        self.assertEqual(self._chain(), ["universe", "book"])

    def test_schema_file_above_the_base_does_not_lengthen_the_walk(self) -> None:
        # The regression #326 fixes: with base == root.parent, a metadata schema
        # in a grandparent used to become the start of the walk.
        self._set_base(self.universe)
        self._write_schema(self.shelf)

        self.assertEqual(self._chain(), ["universe", "book"])

    def test_schema_file_above_the_base_does_not_change_resolution(self) -> None:
        self._set_base(self.universe)
        before = self._chain()
        self._write_schema(self.shelf)
        self._write_schema(self.shelf.parent)

        self.assertEqual(self._chain(), before)

    def test_schema_file_inside_the_base_is_still_a_layer(self) -> None:
        # Narrowing the walk must not stop legitimate in-range layers working.
        self._set_base(self.shelf)
        self._write_schema(self.universe)

        self.assertIn("universe", self._chain())

    def test_no_base_folder_falls_back_to_the_project_alone(self) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest["settings"].pop("projects_base_folder", None)
        self.service._write_yaml(self.root / "project.yaml", manifest)

        self.assertIsNone(self.service._metadata_schema_base_folder(self.root))
        self.assertEqual(self._chain(), ["book"])

    def test_root_outside_the_base_falls_back_to_the_project_alone(self) -> None:
        elsewhere = Path(self.temp_dir.name) / "elsewhere"
        elsewhere.mkdir()
        self._set_base(elsewhere)

        self.assertEqual(self._chain(), ["book"])

    def test_base_equal_to_root_yields_the_root_alone(self) -> None:
        self._set_base(self.root)

        self.assertEqual(self._chain(), ["book"])

    def test_the_project_is_always_the_last_layer(self) -> None:
        # `_read_inherited_ai_settings` (#312) slices this list with [:-1] to get
        # "everything above me", so root-is-last is a contract, not a detail.
        for base in (self.shelf, self.universe, self.root):
            with self.subTest(base=base.name):
                self._set_base(base)
                folders = self.service._project_layer_folders(self.root)
                self.assertEqual(folders[-1], self.root)


if __name__ == "__main__":
    unittest.main()
