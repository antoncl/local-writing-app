"""The level list (ADR-0094 §7, #2176): containers are named by their depth,
numbered by it, and cannot be made or moved past its end; a list change that
would rename containers already in the tree is asked about first.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from layer_fixtures import set_projects_root

from app.models import (
    CreateStructureNodeRequest,
    StructureLevel,
    UpdateProjectSettingsRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate
from app.services.project.tree_configs import MANUSCRIPT_TREE
from app.services.project_service import ProjectService


class LevelsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        set_projects_root(self.base)
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        node_index_gate.invalidate()
        self.temp_dir.cleanup()

    def _add(self, title: str, parent: str | None = None, entry_type: str = "manuscript:container") -> str:
        document = self.service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type=entry_type, parent_id=parent)
        )
        return next(node.id for node in _walk(document.root) if node.title == title)

    def _node(self, node_id: str):
        return next(node for node in _walk(self.service.read_structure().root) if node.id == node_id)

    def _set_levels(self, levels: list[dict], force: bool = False) -> None:
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(
                manuscript_levels=[StructureLevel.model_validate(level) for level in levels], force_levels=force
            )
        )

    def _number(self, node_id: str) -> object:
        return self._node(node_id).computed_metadata.get("number")


class NamingTests(LevelsTestCase):
    def test_a_new_project_has_one_container_type_named_by_depth(self) -> None:
        act = self._add("One")
        chapter = self._add("Two", act)
        self.assertEqual((self._node(act).level, self._node(act).level_name), (1, "Act"))
        self.assertEqual((self._node(chapter).level, self._node(chapter).level_name), (2, "Chapter"))
        self.assertEqual(self._node(chapter).type, "manuscript:container")

    def test_adding_a_level_makes_room_for_a_deeper_container(self) -> None:
        act = self._add("One")
        chapter = self._add("Two", act)
        with self.assertRaises(ProjectServiceError) as refused:
            self._add("Three", chapter)
        self.assertEqual(refused.exception.status_code, 422)

        self._set_levels([{"name": "Act"}, {"name": "Chapter"}, {"name": "Sequence"}])

        sequence = self._add("Three", chapter)
        self.assertEqual(self._node(sequence).level_name, "Sequence")

    def test_a_move_that_would_push_a_container_past_the_list_is_refused(self) -> None:
        act_one, act_two = self._add("One"), self._add("Two")
        self._add("Chapter", act_two)
        with self.assertRaises(ProjectServiceError) as refused:
            # Act Two (height 2) under Act One would put its chapter at depth 3.
            self.service.move_structure_node(act_two, act_one, 0)
        self.assertEqual(refused.exception.status_code, 422)
        # A scene may go anywhere a container is.
        scene = self._add("Scene", act_one, entry_type="manuscript:scene")
        self.assertIsNone(self._node(scene).level)

    def test_a_container_past_the_list_is_named_by_the_last_level_with_a_warning(self) -> None:
        act = self._add("One")
        chapter = self._add("Two", act)
        self._set_levels([{"name": "Act"}, {"name": "Chapter"}, {"name": "Sequence"}])
        deep = self._add("Three", chapter)
        self._set_levels([{"name": "Act"}, {"name": "Chapter"}], force=True)

        self.assertEqual((self._node(deep).level, self._node(deep).level_name), (3, "Chapter"))
        warnings = self.service._tree_placement_warnings(self.root, MANUSCRIPT_TREE)
        self.assertTrue(any("'Three'" in warning for warning in warnings), warnings)


class NumberingTests(LevelsTestCase):
    def _two_acts_of_two(self) -> tuple[list[str], list[str]]:
        acts = [self._add("Rising"), self._add("Falling")]
        chapters = [self._add(f"Ch {a}{c}", act) for a, act in enumerate(acts) for c in range(2)]
        return acts, chapters

    def test_numbers_restart_in_each_parent_by_default(self) -> None:
        acts, chapters = self._two_acts_of_two()
        self.assertEqual([self._number(act) for act in acts], [1, 2])
        self.assertEqual([self._number(chapter) for chapter in chapters], [1, 2, 1, 2])

    def test_continuous_numbering_runs_on_through_the_tree(self) -> None:
        acts, chapters = self._two_acts_of_two()
        self._set_levels([{"name": "Act"}, {"name": "Chapter", "numbering": "continuous"}])
        self.assertEqual([self._number(chapter) for chapter in chapters], [1, 2, 3, 4])
        self.assertEqual([self._number(act) for act in acts], [1, 2])

    def test_a_container_that_shows_no_number_takes_none(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else {}
        schema = schema or {"version": 1}
        schema.setdefault("entry_types", {})["manuscript:prologue"] = {
            "name": "Prologue",
            "kind": "manuscript",
            "parent": "manuscript:container",
            "display_template": "{title}",
        }
        schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
        node_index_gate.invalidate()

        prologue = self._add("Prologue", entry_type="manuscript:prologue")
        act = self._add("Beginning")
        self.assertEqual(self._node(prologue).level_name, "Act")
        self.assertEqual(self._number(act), 1)  # the prologue took no act's number


class LevelValidationTests(LevelsTestCase):
    def _refused(self, levels: list[dict], force: bool = False) -> int:
        with self.assertRaises(ProjectServiceError) as refused:
            self._set_levels(levels, force)
        return refused.exception.status_code

    def test_an_empty_list_a_blank_name_or_a_foreign_type_is_invalid(self) -> None:
        self.assertEqual(self._refused([]), 422)
        self.assertEqual(self._refused([{"name": "  "}]), 422)
        self.assertEqual(self._refused([{"name": "Act", "type": "manuscript:scene"}]), 422)
        self.assertEqual(self._refused([{"name": "Act", "type": "research:container"}]), 422)
        self.assertEqual(self._refused([{"name": "Act", "type": "manuscript:missing"}]), 422)

    def test_renaming_a_level_in_place_is_not_asked_about(self) -> None:
        act = self._add("One")
        self._set_levels([{"name": "Part"}, {"name": "Chapter"}])
        self.assertEqual(self._node(act).level_name, "Part")

    def test_a_change_that_renames_containers_is_asked_first_then_forced(self) -> None:
        act = self._add("One")
        chapter = self._add("Two", act)
        # Removing Act would name the act "Chapter" and leave the chapter past the end.
        self.assertEqual(self._refused([{"name": "Chapter"}]), 409)
        self.assertEqual(self._node(act).level_name, "Act")  # nothing written

        self._set_levels([{"name": "Chapter"}], force=True)

        self.assertEqual(self._node(act).level_name, "Chapter")
        self.assertEqual(self._node(chapter).level, 2)

    def test_a_list_with_no_containers_to_rename_saves_without_asking(self) -> None:
        self._set_levels([{"name": "Book"}])
        manifest = yaml.safe_load((self.root / "project.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manuscript_structure"]["levels"], [{"name": "Book"}])


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


if __name__ == "__main__":
    unittest.main()
