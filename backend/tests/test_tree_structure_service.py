"""The read-side helpers over a built tree (`TreeStructureService`): lookups and
the one walk every consumer rides. The tree itself is built from the nodes'
own placement (ADR-0094) — see `test_placement.py` and `test_tree_nodes.py`."""

from __future__ import annotations

import unittest

from app.models import StructureDocument, StructureNode
from app.services.tree_structure import (
    StructureCollector,
    StructureVisitor,
    TreeStructureService,
)


class TreeStructureServiceTests(unittest.TestCase):
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
