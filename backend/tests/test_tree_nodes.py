"""The trees read from and written to the nodes themselves (ADR-0094 S1, #2175).

Each test is one step of the ADR's journey, or one of the rules that make it
hold: a move is a one-line write, placement is never content, the files are
the truth, and the index carries placement through every path it is built by.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import set_projects_root

from app.models import CreateSceneRequest, CreateStructureNodeRequest, SaveSceneRequest
from app.services.project.node_index_gate import node_index_gate
from app.services.project.tree_configs import MANUSCRIPT_TREE
from app.services.project_service import ProjectService


class TreeNodesTestCase(unittest.TestCase):
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

    def _container(self, title: str, entry_type: str = "manuscript:container", parent: str | None = None) -> str:
        document = self.service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type=entry_type, parent_id=parent)
        )
        return next(node.id for node in _walk(document.root) if node.title == title)

    def _path(self, node_id: str) -> Path:
        return self.service._path_for_node_id(node_id, "manuscript")

    def _children(self, parent_id: str | None) -> list[str]:
        root = self.service.read_structure().root
        node = root if parent_id is None else next(n for n in _walk(root) if n.id == parent_id)
        return [child.id for child in node.children]


class MoveTests(TreeNodesTestCase):
    def test_a_drag_changes_one_line_of_one_file(self) -> None:
        """Journey step 2: Chapter 3 above Chapter 2 is one file, one line."""
        one, two, three = (self._container(f"Chapter {n}") for n in (1, 2, 3))
        before = {path.name: path.read_bytes() for path in (self.root / "scenes").glob("*.md")}

        self.service.move_structure_node(three, "root", self._children(None).index(two) - 0)

        after = {path.name: path.read_bytes() for path in (self.root / "scenes").glob("*.md")}
        changed = [name for name in after if after[name] != before[name]]
        self.assertEqual(changed, [self._path(three).name])
        old = before[changed[0]].decode().splitlines()
        new = after[changed[0]].decode().splitlines()
        self.assertEqual([(a, b) for a, b in zip(old, new, strict=True) if a != b], [("rank: 4", "rank: 2.5")])
        order = self._children(None)
        self.assertLess(order.index(three), order.index(two))
        self.assertLess(order.index(one), order.index(three))

    def test_an_open_pane_saves_after_its_node_is_moved(self) -> None:
        """Journey step 2, second half: placement is not in the revision."""
        chapter = self._container("Chapter 1")
        scene_id = self.service.create_scene(CreateSceneRequest(title="Landing")).id
        opened = self.service.read_scene(scene_id)

        self.service.move_structure_node(scene_id, chapter, 0)

        saved = self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=opened.title,
                body="Typed after the move.",
                base_revision=opened.revision,
                status=opened.status,
                entry_type=opened.entry_type,
                metadata=opened.metadata,
            ),
        )
        self.assertEqual(saved.body.strip(), "Typed after the move.")
        self.assertEqual(self._children(chapter), [scene_id], "the save moved the scene back")

    def test_moving_into_a_leaf_or_own_descendant_is_refused(self) -> None:
        act = self._container("Act", "manuscript:container")
        chapter = self._container("Chapter", parent=act)
        scene_id = self.service.create_scene(CreateSceneRequest(title="Scene", parent_id=chapter)).id
        from app.services.project.errors import ProjectServiceError

        with self.assertRaises(ProjectServiceError):
            self.service.move_structure_node(act, chapter, 0)
        with self.assertRaises(ProjectServiceError):
            self.service.move_structure_node(chapter, scene_id, 0)

    def test_many_inserts_in_one_gap_stay_in_order(self) -> None:
        """Past the six-decimal limit the group renumbers; the order holds."""
        first, last = self._container("First"), self._container("Last")
        inserted = []
        for n in range(25):
            node = self._container(f"In {n}")
            self.service.move_structure_node(node, "root", self._children(None).index(first) + 1)
            inserted.append(node)
        order = self._children(None)
        at = order.index(first)
        self.assertEqual(order[at + 1 : at + 26], list(reversed(inserted)))
        self.assertEqual(order[at + 26], last)


class FilesAreTheTruthTests(TreeNodesTestCase):
    def test_a_scene_added_outside_the_app_lands_where_its_file_says(self) -> None:
        """Journey step 4."""
        chapter = self._container("Chapter 1")
        self.service.create_scene(CreateSceneRequest(title="Existing", parent_id=chapter))
        (self.root / "scenes" / "Dropped.md").write_text(
            "---\nid: manuscript_dropped01\ntitle: Dropped\nentry_type: manuscript:scene\n"
            f"parent: {chapter}\nstatus: draft\nmetadata: {{}}\n---\n\nFrom Explorer.\n",
            encoding="utf-8",
        )
        self.assertTrue(self.service.refresh_node_index_from_disk().changed)
        self.assertEqual(self._children(chapter)[-1], "manuscript_dropped01")

    def test_a_raw_file_dropped_in_can_be_placed_and_does_not_block_creation(self) -> None:
        """Review finding: a file with no front matter sat unranked at the end of
        the top level, and the next top-level create renumbered through it and
        crashed. It now gains a block and the create goes through."""
        (self.root / "scenes" / "Raw notes.md").write_text("Just prose, no front matter.\n", encoding="utf-8")
        self.service.refresh_node_index_from_disk()
        act = self._container("Act", "manuscript:container")
        order = self._children(None)
        self.assertEqual(order[-1], act)
        self.assertIn("Raw notes", order)
        raw = (self.root / "scenes" / "Raw notes.md").read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("---\nrank: "), raw)
        self.assertTrue(raw.endswith("Just prose, no front matter.\n"))
        self.service.move_structure_node("Raw notes", act, 0)
        self.assertEqual(self._children(act), ["Raw notes"])

    def test_a_chapter_deleted_outside_the_app_leaves_its_scenes_at_the_top_with_warnings(self) -> None:
        """Journey step 3."""
        chapter = self._container("Chapter 1")
        scene_id = self.service.create_scene(CreateSceneRequest(title="Orphan", parent_id=chapter)).id
        self._path(chapter).unlink()
        self.service.refresh_node_index_from_disk()

        self.assertIn(scene_id, self._children(None))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("Orphan" in warning and "top level" in warning for warning in warnings), warnings)

    def test_no_structure_file_and_no_missing_scene_error(self) -> None:
        scene_id = self.service.create_scene(CreateSceneRequest(title="Gone")).id
        self._path(scene_id).unlink()
        self.service.refresh_node_index_from_disk()
        report = self.service.validate_project()
        self.assertNotIn(scene_id, [n.id for n in _walk(self.service.read_structure().root)])
        self.assertFalse(any("missing scene" in error for error in report.errors), report.errors)


class PlacementIsNotContentTests(TreeNodesTestCase):
    def test_restoring_a_snapshot_never_moves_the_scene(self) -> None:
        """Journey step 11."""
        one, two = self._container("Chapter 1"), self._container("Chapter 2")
        scene_id = self.service.create_scene(CreateSceneRequest(title="Wanderer", parent_id=one)).id
        snapshot = self.service.capture_snapshot(scene_id)
        self.service.move_structure_node(scene_id, two, 0)

        self.service.restore_snapshot(scene_id, snapshot.id)

        self.assertEqual(self._children(two), [scene_id])
        self.assertEqual(self._children(one), [])

    def test_a_drag_does_not_suppress_the_next_session_snapshot(self) -> None:
        one, two = self._container("Chapter 1"), self._container("Chapter 2")
        scene_id = self.service.create_scene(CreateSceneRequest(title="Sleeper", parent_id=one)).id
        path = self._path(scene_id)
        # The author last saved a day ago.
        a_day_ago = path.stat().st_mtime - 24 * 3600
        os.utime(path, (a_day_ago, a_day_ago))
        self.service.move_structure_node(scene_id, two, 0)
        before = len(self.service.list_snapshots(scene_id).snapshots)

        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title, body="A new session.", status=scene.status,
                entry_type=scene.entry_type, metadata=scene.metadata,
            ),
        )
        self.assertEqual(len(self.service.list_snapshots(scene_id).snapshots), before + 1)


class PlacementKeysAreReservedTests(TreeNodesTestCase):
    def _add_field(self, field_id: str, entry_type: str) -> None:
        from app.models import MetadataFieldDefinition, UpsertMetadataFieldRequest

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                field_id=field_id,
                field=MetadataFieldDefinition(name=field_id.title(), type="text"),
                entry_type=entry_type,
            )
        )

    def test_a_tree_kind_cannot_carry_a_field_named_parent_or_rank(self) -> None:
        """ADR-0094 §1: on a tree node those keys are its placement."""
        from app.services.project.errors import ProjectServiceError

        for field_id in ("parent", "rank"):
            with self.assertRaises(ProjectServiceError) as raised:
                self._add_field(field_id, "manuscript:scene")
            self.assertEqual(raised.exception.status_code, 422)
            self.assertIn("where the node sits", raised.exception.message)

    def test_a_field_a_schema_already_had_is_a_warning_not_a_block(self) -> None:
        """Review finding: an existing field named `rank` on a tree kind must
        not make every unrelated schema save fail."""
        schema_path = self.root / "metadata.schema.yaml"
        import yaml

        data = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        data.setdefault("fields", {})["rank"] = {"name": "Rank", "type": "text"}
        data.setdefault("entry_types", {})["manuscript:scene"] = {"fields": ["rank"]}
        schema_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        node_index_gate.invalidate()

        self._add_field("mood", "manuscript:scene")  # an unrelated save goes through
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("cannot have a field named 'rank'" in w for w in warnings), warnings)

    def test_another_kind_may(self) -> None:
        self._add_field("rank", "lore:character")
        self.assertIn("rank", self.service.read_metadata_schema().entry_types["lore:character"].fields)


class IndexCarriesPlacementTests(TreeNodesTestCase):
    def test_a_warm_reopen_from_the_index_snapshot_keeps_the_tree(self) -> None:
        chapter = self._container("Chapter 1")
        scene_id = self.service.create_scene(CreateSceneRequest(title="Kept", parent_id=chapter)).id
        # Flush the snapshot, drop the memo, and reopen: the next build is
        # served from `.cache/node-index.json`.
        self.service.read_structure()
        node_index_gate.invalidate()
        reopened = ProjectService.opened_at(self.root)
        chapter_node = next(n for n in _walk(reopened.read_structure().root) if n.id == chapter)
        self.assertEqual([child.id for child in chapter_node.children], [scene_id])

    def test_the_tree_is_this_projects_own_nodes(self) -> None:
        tree = self.service._built_tree(self.root, MANUSCRIPT_TREE)
        self.assertEqual(tree.problems, [])
        ids = [node.id for node in _walk(tree.document.root) if node.id != "root"]
        self.assertTrue(all(node_id.startswith("manuscript_") for node_id in ids), ids)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


if __name__ == "__main__":
    unittest.main()
