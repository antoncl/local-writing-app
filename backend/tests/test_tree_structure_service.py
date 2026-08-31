from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from app.models import StructureDocument, StructureNode
from app.services.tree_structure import (
    StructureCollector,
    StructureVisitor,
    TreeConfig,
    TreeStructureError,
    TreeStructureService,
)

MANUSCRIPT_CONFIG = TreeConfig(
    yaml_filename="manuscript.structure.yaml",
    root_title="Manuscript",
    leaf_ref_field="scene_id",
    leaf_subdir="scenes",
)

RESEARCH_CONFIG = TreeConfig(
    yaml_filename="research.structure.yaml",
    root_title="Research",
    leaf_ref_field="note_id",
    leaf_subdir="research/notes",
)


def _read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class TreeStructureServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- paths ----

    def test_paths_resolve_under_root(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        self.assertEqual(svc.yaml_path, self.root / "manuscript.structure.yaml")
        self.assertEqual(svc.leaf_dir, self.root / "scenes")

        research = TreeStructureService(self.root, RESEARCH_CONFIG)
        self.assertEqual(research.yaml_path, self.root / "research.structure.yaml")
        self.assertEqual(research.leaf_dir, self.root / "research" / "notes")

    # ---- read ----

    def test_read_missing_file_raises(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        with self.assertRaises(TreeStructureError):
            svc.read()

    def test_read_non_object_raises(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        svc.yaml_path.write_text("- a\n- b\n", encoding="utf-8")
        with self.assertRaises(TreeStructureError):
            svc.read()

    # ---- initialize ----

    def test_initialize_writes_root_only(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        svc.initialize()
        doc = svc.read()
        self.assertEqual(doc.root.id, "root")
        self.assertEqual(doc.root.type, "root")
        self.assertEqual(doc.root.title, "Manuscript")
        self.assertEqual(doc.root.children, [])

    def test_initialize_seeds_leaf_node(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        svc.initialize(
            leaf_node={
                "id": "node_1",
                "type": "scene",
                "title": "Opening",
                "scene_id": "scene_abc",
                "children": [],
            }
        )
        doc = svc.read()
        self.assertEqual(len(doc.root.children), 1)
        leaf = doc.root.children[0]
        self.assertEqual(leaf.scene_id, "scene_abc")
        self.assertEqual(leaf.title, "Opening")

    def test_initialize_uses_configured_root_title(self) -> None:
        svc = TreeStructureService(self.root, RESEARCH_CONFIG)
        svc.initialize()
        on_disk = _read_yaml(svc.yaml_path)
        self.assertEqual(on_disk["root"]["title"], "Research")

    # ---- field renaming on disk vs model ----

    def test_manuscript_writes_scene_id_on_disk(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        svc.initialize(
            leaf_node={
                "id": "node_1",
                "type": "scene",
                "title": "Opening",
                "scene_id": "scene_abc",
                "children": [],
            }
        )
        on_disk = _read_yaml(svc.yaml_path)
        leaf = on_disk["root"]["children"][0]
        self.assertIn("scene_id", leaf)
        self.assertEqual(leaf["scene_id"], "scene_abc")
        self.assertNotIn("note_id", leaf)

    def test_research_writes_note_id_on_disk(self) -> None:
        svc = TreeStructureService(self.root, RESEARCH_CONFIG)
        svc.initialize(
            leaf_node={
                "id": "node_1",
                "type": "note",
                "title": "Lancashire mill towns",
                "scene_id": "note_abc",  # caller still uses model field name
                "children": [],
            }
        )
        on_disk = _read_yaml(svc.yaml_path)
        leaf = on_disk["root"]["children"][0]
        self.assertIn("note_id", leaf)
        self.assertEqual(leaf["note_id"], "note_abc")
        self.assertNotIn("scene_id", leaf)

    def test_research_reads_note_id_into_model_scene_id(self) -> None:
        svc = TreeStructureService(self.root, RESEARCH_CONFIG)
        svc.yaml_path.write_text(
            yaml.safe_dump(
                {
                    "root": {
                        "id": "root",
                        "type": "root",
                        "title": "Research",
                        "children": [
                            {
                                "id": "n1",
                                "type": "note",
                                "title": "Mill",
                                "note_id": "note_xyz",
                                "children": [],
                            }
                        ],
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        doc = svc.read()
        self.assertEqual(doc.root.children[0].scene_id, "note_xyz")

    def test_round_trip_preserves_manuscript_field_name(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        svc.initialize(
            leaf_node={
                "id": "n1",
                "type": "scene",
                "title": "S",
                "scene_id": "s1",
                "children": [],
            }
        )
        doc = svc.read()
        svc.write(doc)
        on_disk = _read_yaml(svc.yaml_path)
        leaf = on_disk["root"]["children"][0]
        self.assertIn("scene_id", leaf)
        self.assertNotIn("note_id", leaf)

    def test_round_trip_preserves_research_field_name(self) -> None:
        svc = TreeStructureService(self.root, RESEARCH_CONFIG)
        svc.initialize(
            leaf_node={
                "id": "n1",
                "type": "note",
                "title": "N",
                "scene_id": "note_1",
                "children": [],
            }
        )
        doc = svc.read()
        svc.write(doc)
        on_disk = _read_yaml(svc.yaml_path)
        leaf = on_disk["root"]["children"][0]
        self.assertIn("note_id", leaf)
        self.assertNotIn("scene_id", leaf)

    # ---- transient stripping on write ----

    def test_write_strips_computed_metadata_status_color(self) -> None:
        svc = TreeStructureService(self.root, MANUSCRIPT_CONFIG)
        doc = StructureDocument(
            root=StructureNode(
                id="root",
                type="root",
                title="Manuscript",
                children=[
                    StructureNode(
                        id="n1",
                        type="scene",
                        title="S",
                        scene_id="s1",
                        status="draft",
                        color="forest",
                        computed_metadata={"number": 1},
                        children=[],
                    )
                ],
            )
        )
        svc.write(doc)
        on_disk = _read_yaml(svc.yaml_path)
        leaf = on_disk["root"]["children"][0]
        self.assertNotIn("status", leaf)
        self.assertNotIn("color", leaf)
        self.assertNotIn("computed_metadata", leaf)
        self.assertEqual(leaf["scene_id"], "s1")

    # ---- in-memory tree CRUD ----

    def _sample_document(self) -> StructureDocument:
        # root → A (container) → A1 (leaf), A2 (leaf)
        #     → B (leaf)
        return StructureDocument(
            root=StructureNode(
                id="root",
                type="root",
                title="Manuscript",
                children=[
                    StructureNode(
                        id="A",
                        type="act",
                        title="Act One",
                        children=[
                            StructureNode(
                                id="A1",
                                type="scene",
                                title="Open",
                                scene_id="s_a1",
                            ),
                            StructureNode(
                                id="A2",
                                type="scene",
                                title="Mid",
                                scene_id="s_a2",
                            ),
                        ],
                    ),
                    StructureNode(
                        id="B",
                        type="scene",
                        title="Standalone",
                        scene_id="s_b",
                    ),
                ],
            )
        )

    def test_find_node(self) -> None:
        doc = self._sample_document()
        self.assertEqual(TreeStructureService.find_node(doc, "A1").title, "Open")
        self.assertEqual(TreeStructureService.find_node(doc, "B").title, "Standalone")
        self.assertIsNone(TreeStructureService.find_node(doc, "missing"))

    def test_find_by_leaf_ref(self) -> None:
        doc = self._sample_document()
        # Resolves a node from its leaf ref (the model's scene_id), not its
        # structure-node id — the single primitive the manuscript and
        # research title/delete paths share.
        self.assertEqual(TreeStructureService.find_by_leaf_ref(doc, "s_a2").id, "A2")
        self.assertEqual(TreeStructureService.find_by_leaf_ref(doc, "s_b").title, "Standalone")
        # Container nodes carry no leaf ref, and unknown refs miss.
        self.assertIsNone(TreeStructureService.find_by_leaf_ref(doc, "A"))
        self.assertIsNone(TreeStructureService.find_by_leaf_ref(doc, "missing"))

    def test_find_parent(self) -> None:
        doc = self._sample_document()
        self.assertEqual(TreeStructureService.find_parent(doc, "A1").id, "A")
        self.assertEqual(TreeStructureService.find_parent(doc, "B").id, "root")
        self.assertIsNone(TreeStructureService.find_parent(doc, "root"))
        self.assertIsNone(TreeStructureService.find_parent(doc, "missing"))

    def test_collect_descendant_scene_ids_ordered(self) -> None:
        # ADR-0074 slice 4: reading order, not a set. From the root: A1, A2
        # (under act A, in stored order), then the standalone B.
        doc = self._sample_document()
        root = doc.root
        self.assertEqual(
            TreeStructureService.collect_descendant_scene_ids_ordered(root),
            ["s_a1", "s_a2", "s_b"],
        )
        # Rooted at a container (act A) → only its subtree, in order.
        act = TreeStructureService.find_node(doc, "A")
        self.assertEqual(
            TreeStructureService.collect_descendant_scene_ids_ordered(act),
            ["s_a1", "s_a2"],
        )
        # A leaf scene node yields itself; an empty container yields nothing.
        leaf = TreeStructureService.find_node(doc, "A1")
        self.assertEqual(
            TreeStructureService.collect_descendant_scene_ids_ordered(leaf), ["s_a1"]
        )
        empty = StructureNode(id="C", type="chapter", title="Empty", children=[])
        self.assertEqual(
            TreeStructureService.collect_descendant_scene_ids_ordered(empty), []
        )

    def test_extract_node_removes_and_returns(self) -> None:
        doc = self._sample_document()
        extracted = TreeStructureService.extract_node(doc, "A1")
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.id, "A1")
        self.assertIsNone(TreeStructureService.find_node(doc, "A1"))
        # A still has A2
        self.assertEqual(
            [c.id for c in TreeStructureService.find_node(doc, "A").children],
            ["A2"],
        )

    def test_extract_node_returns_none_for_missing(self) -> None:
        doc = self._sample_document()
        self.assertIsNone(TreeStructureService.extract_node(doc, "ghost"))
        self.assertIsNone(TreeStructureService.extract_node(doc, "root"))

    def test_insert_node_append_default(self) -> None:
        doc = self._sample_document()
        new_leaf = StructureNode(id="A3", type="scene", title="Close", scene_id="s_a3")
        a = TreeStructureService.find_node(doc, "A")
        TreeStructureService.insert_node(a, new_leaf)
        self.assertEqual([c.id for c in a.children], ["A1", "A2", "A3"])

    def test_insert_node_at_position(self) -> None:
        doc = self._sample_document()
        new_leaf = StructureNode(id="A0", type="scene", title="Pre", scene_id="s_a0")
        a = TreeStructureService.find_node(doc, "A")
        TreeStructureService.insert_node(a, new_leaf, position=0)
        self.assertEqual([c.id for c in a.children], ["A0", "A1", "A2"])

    def test_insert_node_position_overflow_appends(self) -> None:
        doc = self._sample_document()
        new_leaf = StructureNode(id="A9", type="scene", title="End", scene_id="s_a9")
        a = TreeStructureService.find_node(doc, "A")
        TreeStructureService.insert_node(a, new_leaf, position=999)
        self.assertEqual(a.children[-1].id, "A9")

    def test_contains_node(self) -> None:
        doc = self._sample_document()
        a = TreeStructureService.find_node(doc, "A")
        self.assertTrue(TreeStructureService.contains_node(a, "A1"))
        self.assertTrue(TreeStructureService.contains_node(a, "A"))
        self.assertFalse(TreeStructureService.contains_node(a, "B"))

    def test_collect_leaf_ids(self) -> None:
        doc = self._sample_document()
        self.assertEqual(
            TreeStructureService.collect_leaf_ids(doc.root),
            {"s_a1", "s_a2", "s_b"},
        )
        a = TreeStructureService.find_node(doc, "A")
        self.assertEqual(
            TreeStructureService.collect_leaf_ids(a),
            {"s_a1", "s_a2"},
        )

    def test_collect_descendant_ids(self) -> None:
        doc = self._sample_document()
        self.assertEqual(
            TreeStructureService.collect_descendant_ids(doc.root),
            {"root", "A", "A1", "A2", "B"},
        )

    def test_remove_node_by_id(self) -> None:
        doc = self._sample_document()
        removed = TreeStructureService.remove_node_by_id(doc.root, "A1")
        self.assertTrue(removed)
        self.assertIsNone(TreeStructureService.find_node(doc, "A1"))
        self.assertFalse(TreeStructureService.remove_node_by_id(doc.root, "ghost"))

    # ---- walk / visitor: the one traversal all read-only consumers ride (#493) ----

    def test_walk_is_depth_first_pre_order(self) -> None:
        doc = self._sample_document()
        seen: list[str] = []

        class _Recorder(StructureVisitor):
            def visit_node(
                self, node: StructureNode, ancestors: tuple[StructureNode, ...]
            ) -> None:
                seen.append(node.id)

        TreeStructureService.walk(doc.root, _Recorder())
        self.assertEqual(seen, ["root", "A", "A1", "A2", "B"])

    def test_walk_passes_root_first_ancestors(self) -> None:
        doc = self._sample_document()
        seen: dict[str, list[str]] = {}

        class _Recorder(StructureVisitor):
            def visit_node(
                self, node: StructureNode, ancestors: tuple[StructureNode, ...]
            ) -> None:
                seen[node.id] = [a.id for a in ancestors]

        TreeStructureService.walk(doc.root, _Recorder())
        self.assertEqual(seen["root"], [])
        self.assertEqual(seen["A"], ["root"])
        self.assertEqual(seen["A1"], ["root", "A"])
        self.assertEqual(seen["B"], ["root"])

    def test_walk_truthy_return_halts_and_skips_remainder(self) -> None:
        # Stopping at a container must not visit its children or later siblings.
        doc = self._sample_document()
        seen: list[str] = []

        class _StopAtAct(StructureVisitor):
            def visit_node(
                self, node: StructureNode, ancestors: tuple[StructureNode, ...]
            ) -> bool:
                seen.append(node.id)
                return node.id == "A"

        TreeStructureService.walk(doc.root, _StopAtAct())
        self.assertEqual(seen, ["root", "A"])

    def test_collect_includes_start_node_in_reading_order(self) -> None:
        doc = self._sample_document()
        self.assertEqual(
            [n.id for n in TreeStructureService.collect(doc.root)],
            ["root", "A", "A1", "A2", "B"],
        )

    def test_collect_skip_root_omits_start_node_only(self) -> None:
        doc = self._sample_document()
        self.assertEqual(
            [n.id for n in TreeStructureService.collect(doc.root, skip_root=True)],
            ["A", "A1", "A2", "B"],
        )
        act = TreeStructureService.find_node(doc, "A")
        self.assertEqual(
            [n.id for n in TreeStructureService.collect(act, skip_root=True)],
            ["A1", "A2"],
        )

    def test_structure_collector_records_every_node(self) -> None:
        doc = self._sample_document()
        collector = StructureCollector()
        TreeStructureService.walk(doc.root, collector)
        self.assertEqual(
            [n.id for n in collector.nodes], ["root", "A", "A1", "A2", "B"]
        )

    def test_walk_is_leaf_marks_nodes_terminal(self) -> None:
        # A leaf carrying children (malformed) is still visited, but is_leaf stops
        # the descent into its subtree — the plot-board layout's guarantee.
        doc = self._sample_document()
        a1 = TreeStructureService.find_node(doc, "A1")
        a1.children.append(
            StructureNode(id="A1x", type="scene", title="Stray", scene_id="s_a1x")
        )
        # Default walk has no leaf notion, so it descends into everything.
        self.assertIn("A1x", [n.id for n in TreeStructureService.collect(doc.root)])

        seen: list[str] = []

        class _Recorder(StructureVisitor):
            def visit_node(
                self, node: StructureNode, ancestors: tuple[StructureNode, ...]
            ) -> None:
                seen.append(node.id)

        TreeStructureService.walk(
            doc.root, _Recorder(), is_leaf=lambda n: n.type == "scene"
        )
        self.assertIn("A1", seen)  # the leaf itself is visited
        self.assertNotIn("A1x", seen)  # its subtree is not descended


if __name__ == "__main__":
    unittest.main()
