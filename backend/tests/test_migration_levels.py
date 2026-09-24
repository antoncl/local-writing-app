"""Migration v13 (ADR-0094 §8/§10, #2176): each tree gets a level list, and
act / chapter / topic stop being built-ins — a layer that uses one keeps it as a
sub-type of the tree's container type.

The fixtures are v12 layers written by hand: placement already on the files,
`container_types` still in the manifest, no level list.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

from app.services.migration_levels import migrate_layer_levels
from app.services.migrations import ChainContext, read_project_version
from app.services.project_service import ProjectService


def _write_node(folder: Path, node_id: str, entry_type: str | None, parent: str | None, rank: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    front: dict[str, Any] = {"id": node_id, "title": node_id}
    if entry_type is not None:
        front["entry_type"] = entry_type
    if parent is not None:
        front["parent"] = parent
    front["rank"] = rank
    (folder / f"{node_id}.md").write_bytes(("---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\nProse.\n").encode())


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


class LevelsMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve()
        self.root = self.base / "series" / "book"
        self.root.mkdir(parents=True)
        self._manifest({"title": "Book", "schema_version": 12})

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _manifest(self, data: dict[str, Any], root: Path | None = None) -> None:
        _write_yaml((root or self.root) / "project.yaml", data)

    def _migrate(self, root: Path | None = None) -> dict[str, Any]:
        migrate_layer_levels(root or self.root, ChainContext())
        return _read_yaml((root or self.root) / "project.yaml")

    def _scene(self, node_id: str, entry_type: str | None, parent: str | None, rank: int) -> None:
        _write_node(self.root / "scenes", node_id, entry_type, parent, rank)

    def test_levels_are_seeded_from_the_containers_at_each_depth(self) -> None:
        self._manifest(
            {"title": "Book", "schema_version": 12, "manuscript_structure": {"container_types": ["manuscript:act"]}}
        )
        self._scene("a1", "manuscript:act", None, 1)
        self._scene("c1", "manuscript:chapter", "a1", 1)
        self._scene("c2", "manuscript:chapter", "a1", 2)
        self._scene("s1", "manuscript:scene", "c1", 1)

        manifest = self._migrate()

        self.assertEqual(
            manifest["manuscript_structure"],
            {
                "levels": [
                    {"name": "Act", "type": "manuscript:act"},
                    {"name": "Chapter", "type": "manuscript:chapter"},
                ]
            },
        )
        self.assertEqual(manifest["research_structure"], {"levels": [{"name": "Topic"}]})

    def test_the_used_types_become_sub_types_of_the_container(self) -> None:
        # The layer's own partial overlay survives under the full definition.
        _write_yaml(
            self.root / "metadata.schema.yaml",
            {"version": 1, "entry_types": {"manuscript:act": {"icon": "star", "fields": ["pov"]}}},
        )
        self._scene("a1", "manuscript:act", None, 1)
        self._scene("c1", "manuscript:chapter", "a1", 1)

        self._migrate()

        entry_types = _read_yaml(self.root / "metadata.schema.yaml")["entry_types"]
        self.assertEqual(
            entry_types["manuscript:act"],
            {"name": "Act", "icon": "star", "kind": "manuscript", "parent": "manuscript:container", "fields": ["pov"]},
        )
        self.assertEqual(entry_types["manuscript:chapter"]["parent"], "manuscript:container")
        self.assertNotIn("research:topic", entry_types)  # not used here

    def test_a_book_with_only_acts_keeps_a_chapter_level_on_the_container_type(self) -> None:
        self._scene("a1", "manuscript:act", None, 1)
        self._scene("s1", "manuscript:scene", "a1", 1)

        levels = self._migrate()["manuscript_structure"]["levels"]

        self.assertEqual(levels, [{"name": "Act", "type": "manuscript:act"}, {"name": "Chapter"}])

    def test_a_flat_layer_gets_the_defaults_and_no_schema_file(self) -> None:
        self._scene("s1", "manuscript:scene", None, 1)
        self._scene("s2", None, None, 2)  # no entry_type: a scene, as the index reads it

        manifest = self._migrate()

        self.assertEqual(manifest["manuscript_structure"]["levels"], [{"name": "Act"}, {"name": "Chapter"}])
        self.assertFalse((self.root / "metadata.schema.yaml").exists())

    def test_the_dominant_type_names_a_depth(self) -> None:
        # Two chapters and one interlude at depth 2: Chapter names the level.
        self._scene("a1", "manuscript:act", None, 1)
        self._scene("i1", "manuscript:chapter", "a1", 1)
        _write_yaml(
            self.root / "metadata.schema.yaml",
            {"entry_types": {"manuscript:interlude": {"name": "Interlude", "kind": "manuscript", "parent": "manuscript:chapter"}}},
        )
        self._scene("x1", "manuscript:interlude", "a1", 2)
        self._scene("i2", "manuscript:chapter", "a1", 3)

        levels = self._migrate()["manuscript_structure"]["levels"]

        self.assertEqual(levels[1], {"name": "Chapter", "type": "manuscript:chapter"})

    def test_research_topics_nest_to_one_topic_level_per_depth(self) -> None:
        notes = self.root / "research" / "notes"
        _write_node(notes, "t1", "research:topic", None, 1)
        _write_node(notes, "t2", "research:topic", "t1", 1)
        _write_node(notes, "n1", "research:note", "t2", 1)

        manifest = self._migrate()

        self.assertEqual(
            manifest["research_structure"]["levels"],
            [{"name": "Topic", "type": "research:topic"}, {"name": "Topic", "type": "research:topic"}],
        )
        topic = _read_yaml(self.root / "metadata.schema.yaml")["entry_types"]["research:topic"]
        self.assertEqual(topic["parent"], "research:container")

    def test_an_existing_level_list_is_kept_and_container_types_removed(self) -> None:
        self._manifest(
            {
                "title": "Book",
                "schema_version": 12,
                "manuscript_structure": {"container_types": ["x"], "levels": [{"name": "Part"}]},
            }
        )
        self._scene("a1", "manuscript:act", None, 1)

        manifest = self._migrate()

        self.assertEqual(manifest["manuscript_structure"], {"levels": [{"name": "Part"}]})

    def test_an_ancestor_definition_is_not_clobbered_and_names_the_level(self) -> None:
        series = self.root.parent
        self._manifest({"title": "Series", "schema_version": 12}, root=series)
        _write_yaml(
            series / "metadata.schema.yaml",
            {
                "entry_types": {
                    "manuscript:act": {
                        "name": "Book",
                        "icon": "crown",
                        "kind": "manuscript",
                        "parent": "manuscript:container",
                    },
                    # A scene sub-type the series defines is a scene in the book too.
                    "manuscript:battle": {"name": "Battle", "kind": "manuscript", "parent": "manuscript:scene"},
                }
            },
        )
        self._manifest({"title": "Book", "schema_version": 12, "inherits": [".."]})
        self._scene("a1", "manuscript:act", None, 1)
        self._scene("b1", "manuscript:battle", "a1", 1)

        levels = self._migrate()["manuscript_structure"]["levels"]

        self.assertFalse((self.root / "metadata.schema.yaml").exists())
        self.assertEqual(levels, [{"name": "Book", "type": "manuscript:act"}, {"name": "Chapter"}])

    def test_a_rerun_changes_nothing(self) -> None:
        self._scene("a1", "manuscript:act", None, 1)
        self._scene("c1", "manuscript:chapter", "a1", 1)
        self._migrate()
        manifest = (self.root / "project.yaml").read_bytes()
        schema = (self.root / "metadata.schema.yaml").read_bytes()

        self._migrate()

        self.assertEqual((self.root / "project.yaml").read_bytes(), manifest)
        self.assertEqual((self.root / "metadata.schema.yaml").read_bytes(), schema)


class LevelsMigrationOpenTests(unittest.TestCase):
    """The whole ladder on open: a v12 act/chapter book reads with levels."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "writing" / "book"
        ProjectService.created_at(self.root, "Book")
        for path in (self.root / "scenes").glob("*.md"):
            path.unlink()
        manifest = _read_yaml(self.root / "project.yaml")
        manifest.pop("manuscript_structure", None)
        manifest.pop("research_structure", None)
        manifest["schema_version"] = 12
        _write_yaml(self.root / "project.yaml", manifest)
        scenes = self.root / "scenes"
        _write_node(scenes, "manuscript_a1", "manuscript:act", None, 1)
        _write_node(scenes, "manuscript_c1", "manuscript:chapter", "manuscript_a1", 1)
        _write_node(scenes, "manuscript_s1", "manuscript:scene", "manuscript_c1", 1)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_tree_is_named_by_its_levels(self) -> None:
        service = ProjectService.opened_at(self.root)
        self.assertEqual(read_project_version(self.root), 13)

        document = service.read_structure()
        act = document.root.children[0]
        chapter = act.children[0]
        self.assertEqual((act.type, act.level, act.level_name), ("manuscript:act", 1, "Act"))
        self.assertEqual((chapter.level, chapter.level_name), (2, "Chapter"))
        self.assertIsNone(chapter.children[0].level)
        self.assertEqual([level.name for level in document.levels], ["Act", "Chapter"])
        # The migrated types keep their number — display and counter come down
        # the type chain from the container's base.
        self.assertEqual((act.computed_metadata.get("number"), chapter.computed_metadata.get("number")), (1, 1))
        # act is_a container now — an `is_a` test through the merged schema.
        self.assertIn("manuscript:container", service.entry_type_ancestry("manuscript:act"))


if __name__ == "__main__":
    unittest.main()
