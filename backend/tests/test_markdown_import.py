"""Markdown import (#4).

A user drops `.md` files into a project's `scenes/` folder and opens Import
documents; `list_loose_scenes` surfaces them, and `import_loose_scenes` appends
them at the manuscript root, normalising a raw front-matter-less file into a
canonical scene along the way. Loose scenes are their own read (#635), no longer
a field on the validation report.

These are pinning tests for the invariants the feature rests on:
- a file dropped while the app stayed open is *seen* (the loose-scenes read
  scans disk truth, not the warm node-index memo);
- a raw file gains a canonical id / heading-derived title / default entry type;
- a file that already carries valid front matter keeps its id and title;
- selective import touches only the requested files.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app


class MarkdownImportTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # `.resolve()` because Windows hands back the 8.3 short form and the
        # layer walk canonicalises (#356).
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Import Tests")
        self.client = TestClient(app)
        self.scenes_dir = self.root / "scenes"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ----- helpers ----------------------------------------------------------

    def _drop(self, name: str, text: str) -> Path:
        """Write a file straight into scenes/, as an external drop would."""
        path = self.scenes_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def _root_children(self):
        return self.service.read_structure().root.children

    def _root_titles(self) -> list[str]:
        return [child.title for child in self._root_children()]

    def _imported_node(self, title: str):
        # A fresh project already carries a default scene at the root, so imports
        # append after it — find the one under test by title rather than index.
        for child in self._root_children():
            if child.title == title:
                return child
        raise AssertionError(f"no root child titled {title!r} in {self._root_titles()}")

    # ----- discovery ---------------------------------------------------------

    def test_dropped_file_surfaces_as_loose_scene(self) -> None:
        self._drop("chapter-one.md", "# Chapter One\n\nThe tide came in.\n")
        # A loose scene is NOT an integrity problem — validate stays clean.
        self.assertTrue(self.service.validate_project().valid)
        loose = self.service.list_loose_scenes()
        self.assertEqual([s.id for s in loose], ["chapter-one"])
        self.assertEqual(loose[0].filename, "chapter-one.md")

    def test_a_registered_scene_is_not_loose(self) -> None:
        response = self.client.post("/api/scenes", json={"title": "Opening"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.service.list_loose_scenes(), [])

    # ----- import: normalise + register --------------------------------------

    def test_import_normalises_and_registers_raw_file(self) -> None:
        path = self._drop("loose.md", "# The Meeting\n\nThey met at dawn.\n")
        before = len(self._root_children())
        self.service.import_loose_scenes()

        self.assertEqual(len(self._root_children()), before + 1)
        node = self._imported_node("The Meeting")

        front, body = self.service._read_markdown_with_front_matter(path, strict=True)
        # The node references exactly the id the file now carries.
        self.assertEqual(node.scene_id, front["id"])
        self.assertEqual(front["title"], "The Meeting")
        self.assertEqual(front["entry_type"], "scene:scene")
        self.assertEqual(front["status"], "draft")
        self.assertIn("They met at dawn.", body)

        # Nothing loose remains after import.
        self.assertEqual(self.service.list_loose_scenes(), [])

    def test_import_titles_a_headingless_file_from_its_filename(self) -> None:
        self._drop("prologue.md", "Just prose, no heading.\n")
        self.service.import_loose_scenes()
        self.assertIn("prologue", self._root_titles())

    def test_import_preserves_existing_front_matter(self) -> None:
        self._drop(
            "kept.md",
            "---\n"
            "id: keeper\n"
            "title: Kept Title\n"
            "entry_type: scene:scene\n"
            "status: final\n"
            "metadata: {}\n"
            "---\n\n"
            "Body.\n",
        )
        self.service.import_loose_scenes()
        node = self._imported_node("Kept Title")
        self.assertEqual(node.scene_id, "keeper")

    def test_import_only_selected_ids(self) -> None:
        self._drop("a.md", "# A\n\nAlpha.\n")
        self._drop("b.md", "# B\n\nBeta.\n")
        # Raw files are keyed by their filename stem until import mints an id.
        self.service.import_loose_scenes(["a"])
        titles = self._root_titles()
        self.assertIn("A", titles)
        self.assertNotIn("B", titles)
        self.assertEqual([s.id for s in self.service.list_loose_scenes()], ["b"])

    def test_import_skips_a_malformed_file_and_lands_the_rest(self) -> None:
        # A single unimportable file must not abort the batch — the good files in
        # the same click still land, and the bad one is left untouched and loose.
        self._drop("good.md", "# Good One\n\nProse.\n")
        self._drop("bad.md", "---\nmetadata: not-a-mapping\n---\n\nBroken.\n")
        self.service.import_loose_scenes()

        self.assertIn("Good One", self._root_titles())
        loose_files = [s.filename for s in self.service.list_loose_scenes()]
        self.assertIn("bad.md", loose_files)
        self.assertNotIn("good.md", loose_files)
        # The skipped file was not rewritten.
        self.assertEqual(
            (self.scenes_dir / "bad.md").read_text(encoding="utf-8"),
            "---\nmetadata: not-a-mapping\n---\n\nBroken.\n",
        )

    # ----- HTTP surface ------------------------------------------------------

    def test_loose_scenes_read_endpoint_lists_dropped_files(self) -> None:
        self._drop("via-read.md", "# Read Scene\n\nseen by the read.\n")
        response = self.client.get("/api/structure/loose-scenes")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual([s["id"] for s in payload], ["via-read"])
        self.assertEqual(payload[0]["filename"], "via-read.md")

    def test_import_endpoint_appends_at_root(self) -> None:
        self._drop("via-route.md", "# Http Scene\n\nvia route.\n")
        response = self.client.post("/api/structure/import-loose", json={})
        self.assertEqual(response.status_code, 200, response.text)
        titles = [child["title"] for child in response.json()["root"]["children"]]
        self.assertIn("Http Scene", titles)


if __name__ == "__main__":
    unittest.main()
