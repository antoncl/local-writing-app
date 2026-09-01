from __future__ import annotations

import unittest

from metadata_validation_base import MetadataValidationBase

from app.models import CreateStructureNodeRequest, SaveSceneRequest, StructureNode
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
        # S1's own "first" shadows the book default "third_omniscient" → an override.
        _resolve(root, {"S1": {"pov_mode": "first"}}, {"pov_mode": "third_omniscient"})
        self.assertEqual(
            _node(root, "S1").resolved_cascade["pov_mode"],
            {
                "value": "first",
                "source_id": "S1",
                "own": True,
                "overrides": True,
                "inherited_source_id": None,
            },
        )

    def test_own_value_overrides_the_nearest_ancestor(self) -> None:
        # The act sets third_limited; S1 sets its own third_close. That own value
        # SHADOWS the act, so it reports overrides + names the act (the nearest
        # setter), not the book default, as what a reset would fall back to (#1734).
        root = self._tree()
        _resolve(
            root,
            {"A": {"pov_mode": "third_limited"}, "S1": {"pov_mode": "third_close"}},
            {"pov_mode": "first"},
        )
        info = _node(root, "S1").resolved_cascade["pov_mode"]
        self.assertEqual(info["value"], "third_close")
        self.assertTrue(info["own"])
        self.assertTrue(info["overrides"])
        self.assertEqual(info["inherited_source_id"], "A")

    def test_inherits_from_nearest_ancestor(self) -> None:
        root = self._tree()
        # Both the act and the (nearer) chapter set it — the chapter wins.
        _resolve(root, {"A": {"pov_mode": "third_limited"}, "C": {"pov_mode": "third_close"}}, {})
        self.assertEqual(
            _node(root, "S1").resolved_cascade["pov_mode"],
            {
                "value": "third_close",
                "source_id": "C",
                "own": False,
                "overrides": False,
                "inherited_source_id": None,
            },
        )

    def test_falls_to_book_default(self) -> None:
        root = self._tree()
        _resolve(root, {}, {"pov_mode": "first"})
        self.assertEqual(
            _node(root, "S2").resolved_cascade["pov_mode"],
            {
                "value": "first",
                "source_id": None,
                "own": False,
                "overrides": False,
                "inherited_source_id": None,
            },
        )

    def test_unset_when_nothing_sets_it(self) -> None:
        root = self._tree()
        _resolve(root, {}, {})
        self.assertEqual(
            _node(root, "S2").resolved_cascade["pov"],
            {
                "value": None,
                "source_id": None,
                "own": False,
                "overrides": False,
                "inherited_source_id": None,
            },
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
        # pov is owned by the scene but NO ancestor/book sets it → set, not shadowing.
        self.assertEqual(
            s1.resolved_cascade["pov"],
            {
                "value": "char_bob",
                "source_id": "S1",
                "own": True,
                "overrides": False,
                "inherited_source_id": None,
            },
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

    def _set_pov_mode(self, scene_id: str, entry_type: str, value: str) -> None:
        s = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=s.title,
                body=s.body,
                base_revision=s.revision,
                entry_type=entry_type,
                metadata={**s.metadata, "pov_mode": value},
            ),
        )

    def _act_with_pov(self, value: str) -> StructureNode:
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act = next(
            n for n in TreeStructureService.collect(structure.root) if n.type == "manuscript:act"
        )
        self._set_pov_mode(act.scene_id, "manuscript:act", value)
        return act

    def test_freeze_pins_narration_on_first_prose(self) -> None:
        # The core §4 guarantee: writing prose freezes the inherited narration onto
        # the scene, so a later ancestor change no longer moves it — while an
        # unwritten sibling still follows.
        act_node = self._act_with_pov("third_limited")
        self.service.create_scene(self._make_create_scene("Written", parent_id=act_node.id))
        self.service.create_scene(self._make_create_scene("Unwritten", parent_id=act_node.id))

        root = self.service.read_structure().root
        written = next(n for n in TreeStructureService.collect(root) if n.title == "Written")

        # Write prose into 'Written' (no explicit pov_mode) → freezes the act's value.
        wscene = self.service.read_scene(written.scene_id)
        self.service.save_scene(
            written.scene_id,
            SaveSceneRequest(title=wscene.title, body="First prose.", base_revision=wscene.revision),
        )
        # Now move the act's pov_mode.
        self._set_pov_mode(act_node.scene_id, "manuscript:act", "third_omniscient")

        root = self.service.read_structure().root
        written = next(n for n in TreeStructureService.collect(root) if n.title == "Written")
        unwritten = next(n for n in TreeStructureService.collect(root) if n.title == "Unwritten")
        # Written scene keeps the frozen value (now its own); unwritten follows the act.
        self.assertEqual(written.resolved_cascade["pov_mode"]["value"], "third_limited")
        self.assertTrue(written.resolved_cascade["pov_mode"]["own"])
        self.assertEqual(unwritten.resolved_cascade["pov_mode"]["value"], "third_omniscient")
        self.assertFalse(unwritten.resolved_cascade["pov_mode"]["own"])

    def test_freeze_does_not_overwrite_an_explicit_own_value(self) -> None:
        # Writing prose while explicitly setting a different pov_mode keeps the
        # author's choice — the freeze is setdefault, not overwrite.
        act_node = self._act_with_pov("third_limited")
        self.service.create_scene(self._make_create_scene("S", parent_id=act_node.id))
        scene_node = next(
            n for n in TreeStructureService.collect(self.service.read_structure().root)
            if n.type == "manuscript:scene"
        )
        s = self.service.read_scene(scene_node.scene_id)
        self.service.save_scene(
            scene_node.scene_id,
            SaveSceneRequest(
                title=s.title, body="Prose.", base_revision=s.revision, metadata={"pov_mode": "first"}
            ),
        )
        scene = next(
            n for n in TreeStructureService.collect(self.service.read_structure().root)
            if n.type == "manuscript:scene"
        )
        self.assertEqual(scene.resolved_cascade["pov_mode"]["value"], "first")
        self.assertTrue(scene.resolved_cascade["pov_mode"]["own"])

    def test_empty_scene_is_not_frozen(self) -> None:
        # A scene with no prose keeps inheriting — no premature freeze.
        act_node = self._act_with_pov("third_limited")
        self.service.create_scene(self._make_create_scene("S", parent_id=act_node.id))
        root = self.service.read_structure().root
        act = next(n for n in TreeStructureService.collect(root) if n.type == "manuscript:act")
        scene = next(n for n in act.children if n.type == "manuscript:scene")
        self.assertFalse(scene.resolved_cascade["pov_mode"]["own"])
        self.assertEqual(scene.resolved_cascade["pov_mode"]["source_id"], act.id)

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

    def test_scene_inherits_narration_from_container(self) -> None:
        # A container (act) override folds to the scenes beneath it through the real
        # pipeline — proving scene_front carries CONTAINER own-metadata, not scenes'
        # only (the load-bearing assumption behind cascading at all).
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_node = next(
            n for n in TreeStructureService.collect(structure.root) if n.type == "manuscript:act"
        )
        act_scene = self.service.read_scene(act_node.scene_id)
        self.service.save_scene(
            act_node.scene_id,
            SaveSceneRequest(
                title=act_scene.title,
                body="",
                base_revision=act_scene.revision,
                entry_type="manuscript:act",
                metadata={"pov_mode": "third_limited"},
            ),
        )
        self.service.create_scene(self._make_create_scene("Scene X", parent_id=act_node.id))

        root = self.service.read_structure().root
        act = next(n for n in TreeStructureService.collect(root) if n.type == "manuscript:act")
        scene = next(n for n in act.children if n.type == "manuscript:scene")
        self.assertEqual(
            scene.resolved_cascade["pov_mode"],
            {
                "value": "third_limited",
                "source_id": act.id,
                "own": False,
                "overrides": False,
                "inherited_source_id": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
