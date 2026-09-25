"""Migration v12 (ADR-0094 §10, #2175): the structure yaml files become each
node's own `parent` / `rank`.

The fixture is a v11 project built by hand — files without placement, the two
tree files, a view that persisted a tree id, and a nested child project that
must not be touched — covering what the yaml allowed and the files cannot say:
a duplicate listing, a leaf whose file is gone, a topic with no file, and a
note typed `note` (#2172) with a child under it.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from app.services.migration_tree_placement import migrate_layer_tree_placement
from app.services.migrations import CURRENT_VERSION, ChainContext, read_project_version
from app.services.project_service import ProjectService

ACT, CHAPTER, S1, S2 = "manuscript_act0000001", "manuscript_ch00000001", "manuscript_s100000001", "manuscript_s200000001"
N1, N2 = "note_n1000000001", "note_n2000000001"
NODE_ACT, NODE_CH, NODE_S1, NODE_S2 = "node_a000000001", "node_c000000001", "node_1000000001", "node_2000000001"
NODE_GONE, NODE_DUP = "node_d000000001", "node_e000000001"
NODE_TOPIC, NODE_N1, NODE_N2, NODE_BAD = "node_f000000001", "node_f000000002", "node_f000000003", "node_f000000004"


def _write_node(folder: Path, node_id: str, title: str, entry_type: str, status: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    front = {"id": node_id, "title": title, "entry_type": entry_type}
    if status:
        front["status"] = "draft"
    front["metadata"] = {}
    path = folder / f"{title}.md"
    path.write_bytes(("---\n" + yaml.safe_dump(front, sort_keys=False).strip() + "\n---\n\nProse.\n").encode())
    return path


def _front(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])


class TreePlacementMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "writing" / "book"
        ProjectService.created_at(self.root, "Book")
        # Start from a v11 folder: no placement on any file, the two tree files.
        for path in (self.root / "scenes").glob("*.md"):
            path.unlink()
        scenes = self.root / "scenes"
        self.paths = {
            ACT: _write_node(scenes, ACT, "Act One", "manuscript:act"),
            CHAPTER: _write_node(scenes, CHAPTER, "Chapter One", "manuscript:chapter"),
            S1: _write_node(scenes, S1, "Landing", "manuscript:scene"),
            S2: _write_node(scenes, S2, "Arrival", "manuscript:scene"),
        }
        notes = self.root / "research" / "notes"
        self.paths[N1] = _write_node(notes, N1, "Mills", "research:note", status=False)
        self.paths[N2] = _write_node(notes, N2, "Canals", "research:note", status=False)
        self._write_trees()
        # A view that persisted a tree id, and a nested child project whose
        # files mention the same id — the child is its own layer, untouched.
        (self.root / "views").mkdir(exist_ok=True)
        (self.root / "views" / "Draft.md").write_text(
            f"---\nid: view_x\nui:\n  collapsed:\n  - {NODE_ACT}\n  - {NODE_ACT}/{NODE_CH}\n---\n", encoding="utf-8"
        )
        child = self.root / "spinoff"
        child.mkdir()
        (child / "project.yaml").write_text("title: Spinoff\n", encoding="utf-8")
        (child / "notes.md").write_text(f"mentions {NODE_ACT}\n", encoding="utf-8")
        manifest = yaml.safe_load((self.root / "project.yaml").read_text(encoding="utf-8"))
        manifest["schema_version"] = 11
        (self.root / "project.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_trees(self) -> None:
        manuscript = {
            "root": {"id": "root", "type": "root", "title": "Manuscript", "children": [
                {"id": NODE_ACT, "type": "manuscript:act", "title": "Act One", "scene_id": ACT, "children": [
                    {"id": NODE_CH, "type": "manuscript:chapter", "title": "Chapter One", "scene_id": CHAPTER,
                     "children": [
                         {"id": NODE_S1, "type": "manuscript:scene", "title": "Landing", "scene_id": S1, "children": []},
                         {"id": NODE_GONE, "type": "manuscript:scene", "title": "Gone",
                          "scene_id": "manuscript_gone000001", "children": []},
                         {"id": NODE_S2, "type": "manuscript:scene", "title": "Arrival", "scene_id": S2, "children": []},
                     ]},
                ]},
                # A second listing of Landing, at the top: the first stands.
                {"id": NODE_DUP, "type": "manuscript:scene", "title": "Landing", "scene_id": S1, "children": []},
            ]}
        }
        research = {
            "root": {"id": "root", "type": "root", "title": "Research", "children": [
                {"id": NODE_TOPIC, "type": "research:topic", "title": "Industry", "children": [
                    {"id": NODE_BAD, "type": "note", "title": "Mills", "note_id": N1, "children": [
                        {"id": NODE_N2, "type": "research:note", "title": "Canals", "note_id": N2, "children": []},
                    ]},
                ]},
            ]}
        }
        for name, tree in (("manuscript.structure.yaml", manuscript), ("research.structure.yaml", research)):
            (self.root / name).write_text(yaml.safe_dump(tree, sort_keys=False), encoding="utf-8")

    def _open(self) -> ProjectService:
        return ProjectService.opened_at(self.root)

    def test_the_tree_reads_as_before_and_the_yaml_is_gone(self) -> None:
        """Journey step 1."""
        service = self._open()
        # The ladder runs to its end on open (v12, then every later step,
        # each a no-op past its own change on this fixture).
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        self.assertFalse((self.root / "manuscript.structure.yaml").exists())
        self.assertFalse((self.root / "research.structure.yaml").exists())

        root = service.read_structure().root
        self.assertEqual([child.id for child in root.children], [ACT])
        act = root.children[0]
        self.assertEqual([child.id for child in act.children], [CHAPTER])
        # Gone is dropped (no file); the duplicate listing did not move Landing.
        self.assertEqual([child.id for child in act.children[0].children], [S1, S2])

    def test_placement_is_written_into_each_file(self) -> None:
        self._open()
        self.assertEqual(_front(self.paths[ACT]).get("rank"), 1)
        self.assertNotIn("parent", _front(self.paths[ACT]))
        self.assertEqual(_front(self.paths[CHAPTER])["parent"], ACT)
        self.assertEqual((_front(self.paths[S1])["parent"], _front(self.paths[S1])["rank"]), (CHAPTER, 1))
        self.assertEqual((_front(self.paths[S2])["parent"], _front(self.paths[S2])["rank"]), (CHAPTER, 2))
        # Every other byte is as it was: the body is untouched.
        self.assertTrue(self.paths[S1].read_text(encoding="utf-8").endswith("\n---\n\nProse.\n"))

    def test_a_topic_gets_a_file_and_a_note_typed_note_keeps_its_child_after_it(self) -> None:
        service = self._open()
        root = service.read_research_structure().root
        self.assertEqual(len(root.children), 1)
        topic = root.children[0]
        self.assertEqual(topic.title, "Industry")
        self.assertTrue(topic.id.startswith("note_"))
        self.assertTrue(service._path_for_node_id(topic.id, "research").exists())
        # Mills (typed `note` by #2172) is a leaf; Canals was under it and now
        # sits under the topic right after it.
        self.assertEqual([child.id for child in topic.children], [N1, N2])

    def test_persisted_tree_ids_are_rewritten_in_this_layer_only(self) -> None:
        self._open()
        view = (self.root / "views" / "Draft.md").read_text(encoding="utf-8")
        self.assertNotIn("node_", view)
        self.assertIn(f"{ACT}/{CHAPTER}", view)
        self.assertIn(NODE_ACT, (self.root / "spinoff" / "notes.md").read_text(encoding="utf-8"))

    def test_a_rerun_after_a_crash_mints_no_duplicate(self) -> None:
        """The yaml is deleted last; a crash before that re-runs the step."""
        saved = {name: (self.root / name).read_text(encoding="utf-8")
                 for name in ("manuscript.structure.yaml", "research.structure.yaml")}
        migrate_layer_tree_placement(self.root, ChainContext())
        for name, text in saved.items():
            (self.root / name).write_text(text, encoding="utf-8")
        migrate_layer_tree_placement(self.root, ChainContext())

        topics = [p for p in (self.root / "research" / "notes").glob("*.md") if "Industry" in p.read_text(encoding="utf-8")]
        self.assertEqual(len(topics), 1)
        self.assertEqual(_front(self.paths[S2])["rank"], 2)


class LegacyFileTests(unittest.TestCase):
    def test_a_file_with_no_id_is_found_by_its_stem_and_keeps_its_place(self) -> None:
        """Review finding: the live index names a legacy file by its stem, and
        a v11 tree file pointed at it by that name."""
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "book"
            (root / "scenes").mkdir(parents=True)
            _write_node(root / "scenes", CHAPTER, "Chapter One", "manuscript:chapter")
            (root / "scenes" / "Old draft.md").write_text("Legacy prose.\n", encoding="utf-8")
            tree = {"root": {"id": "root", "type": "root", "title": "Manuscript", "children": [
                {"id": NODE_CH, "type": "manuscript:chapter", "title": "Chapter One", "scene_id": CHAPTER, "children": [
                    {"id": NODE_S1, "type": "manuscript:scene", "title": "Old draft", "scene_id": "Old draft", "children": []},
                ]},
            ]}}
            (root / "manuscript.structure.yaml").write_text(yaml.safe_dump(tree), encoding="utf-8")
            migrate_layer_tree_placement(root, ChainContext())
            legacy = (root / "scenes" / "Old draft.md").read_text(encoding="utf-8")
            self.assertEqual(legacy, f"---\nparent: {CHAPTER}\nrank: 1\n---\nLegacy prose.\n")


class NoTreeFilesTests(unittest.TestCase):
    def test_a_layer_without_tree_files_is_left_alone(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "series"
            root.mkdir()
            (root / "notes.md").write_text("node_a000000001\n", encoding="utf-8")
            migrate_layer_tree_placement(root, ChainContext())
            self.assertEqual((root / "notes.md").read_text(encoding="utf-8"), "node_a000000001\n")
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
