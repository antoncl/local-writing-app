from __future__ import annotations

import unittest

from metadata_validation_base import MetadataValidationBase

from app.models import SaveSceneRequest, StructureNode
from app.services.project.computed_metadata import _CascadeResolver
from app.services.tree_structure import TreeStructureService


def _resolve(root: StructureNode, own: dict[str, dict], book_default: dict) -> None:
    resolver = _CascadeResolver(
        ["pov_mode", "pov"], lambda n: own.get(n.id, {}), book_default
    )
    TreeStructureService.walk(root, resolver)


def _node(root: StructureNode, node_id: str) -> StructureNode:
    return next(n for n in TreeStructureService.collect(root) if n.id == node_id)


class CascadeResolverTests(unittest.TestCase):
    """The fold, in isolation (ADR-0079): own → nearest ancestor → book default →
    unset, per field, with provenance."""

    def _tree(self) -> StructureNode:
        # root → A (act) → C (chapter) → S1, S2 (scenes)
        return StructureNode(
            id="root",
            type="root",
            title="Book",
            children=[
                StructureNode(
                    id="A",
                    type="manuscript:act",
                    title="Act 1",
                    scene_id="a",
                    children=[
                        StructureNode(
                            id="C",
                            type="manuscript:chapter",
                            title="Ch 1",
                            scene_id="c",
                            children=[
                                StructureNode(id="S1", type="manuscript:scene", title="S1", scene_id="s1"),
                                StructureNode(id="S2", type="manuscript:scene", title="S2", scene_id="s2"),
                            ],
                        )
                    ],
                )
            ],
        )

    def test_own_value_wins(self) -> None:
        root = self._tree()
        _resolve(root, {"S1": {"pov_mode": "first"}}, {"pov_mode": "third_omniscient"})
        self.assertEqual(
            _node(root, "S1").resolved_cascade["pov_mode"],
            {"value": "first", "source_id": "S1", "own": True},
        )

    def test_inherits_from_nearest_ancestor(self) -> None:
        root = self._tree()
        # Both the act and the (nearer) chapter set it — the chapter wins.
        _resolve(root, {"A": {"pov_mode": "third_limited"}, "C": {"pov_mode": "third_close"}}, {})
        self.assertEqual(
            _node(root, "S1").resolved_cascade["pov_mode"],
            {"value": "third_close", "source_id": "C", "own": False},
        )

    def test_falls_to_book_default(self) -> None:
        root = self._tree()
        _resolve(root, {}, {"pov_mode": "first"})
        self.assertEqual(
            _node(root, "S2").resolved_cascade["pov_mode"],
            {"value": "first", "source_id": None, "own": False},
        )

    def test_unset_when_nothing_sets_it(self) -> None:
        root = self._tree()
        _resolve(root, {}, {})
        self.assertEqual(
            _node(root, "S2").resolved_cascade["pov"],
            {"value": None, "source_id": None, "own": False},
        )

    def test_per_field_independence(self) -> None:
        # pov_mode inherited from the act; pov owned by the scene — separate chains.
        root = self._tree()
        _resolve(
            root,
            {"A": {"pov_mode": "third_limited"}, "S1": {"pov": "char_bob"}},
            {"pov_mode": "first"},
        )
        s1 = _node(root, "S1")
        self.assertEqual(s1.resolved_cascade["pov_mode"]["source_id"], "A")
        self.assertFalse(s1.resolved_cascade["pov_mode"]["own"])
        self.assertEqual(
            s1.resolved_cascade["pov"], {"value": "char_bob", "source_id": "S1", "own": True}
        )

    def test_empty_string_reads_as_unset(self) -> None:
        # An empty pov_mode ("") is not an override — it inherits.
        root = self._tree()
        _resolve(root, {"C": {"pov_mode": "third_close"}, "S1": {"pov_mode": ""}}, {})
        resolved = _node(root, "S1").resolved_cascade["pov_mode"]
        self.assertEqual(resolved["value"], "third_close")
        self.assertEqual(resolved["source_id"], "C")


class NarrationCascadeIntegrationTests(MetadataValidationBase):
    """The fold through the real read_structure / save_scene pipeline."""

    def _scene_node(self, root: StructureNode, scene_id: str) -> StructureNode:
        return next(n for n in TreeStructureService.collect(root) if n.scene_id == scene_id)

    def test_read_structure_stamps_own_narration(self) -> None:
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body="Prose.",
                base_revision=scene.revision,
                metadata={"pov_mode": "third_close"},
            ),
        )
        root = self.service.read_structure().root
        node = self._scene_node(root, self.scene_id)
        self.assertIsNotNone(node.resolved_cascade)
        pov_mode = node.resolved_cascade["pov_mode"]
        self.assertEqual(pov_mode["value"], "third_close")
        self.assertTrue(pov_mode["own"])
        self.assertEqual(pov_mode["source_id"], node.id)
        # pov is declared cascading but set nowhere → resolved-but-unset.
        self.assertIn("pov", node.resolved_cascade)


if __name__ == "__main__":
    unittest.main()
