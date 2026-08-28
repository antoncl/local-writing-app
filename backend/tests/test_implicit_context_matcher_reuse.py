"""#1505: `_scene_prose_ids` now builds its `auto`-policy matcher ONCE per
call (via `_build_scene_matcher`) and scans each prose field/body text
against that one matcher — instead of the old per-field `_alias_match` call,
which recompiled the matcher from scratch on every field. Pure optimization;
this test pins the equivalence: the compile-once path must return the exact
same id set as unioning the old per-text `_alias_match` calls.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
)
from app.services.ai.lore_selection import _alias_match, _scene_prose_ids


class MatcherReuseEquivalenceTests(unittest.TestCase):
    """A scene with several lore mentions across body + a long_text field:
    `_scene_prose_ids` (compile-once) must match the union of per-text
    `_alias_match` calls (compile-per-call) exactly."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Matcher Reuse Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_lore(self, title: str, *, entry_type: str = "lore:character", body: str = "") -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type=entry_type)
        )
        existing = self.service.read_lore_entry(created.id)
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type=entry_type,
                metadata={"aliases": []},
            ),
        )
        return created.id

    def _add_scene_field(self, field_id: str, field_type: str) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id=field_id,
                field=MetadataFieldDefinition(name=field_id.title(), type=field_type),
                entry_type="manuscript:scene",
            )
        )

    def _make_scene(self, *, body: str, metadata: dict) -> str:
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:act")
        added = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Scene One", entry_type="manuscript:scene", parent_id=act.id
            )
        )
        scene_node = next(c for c in added.root.children if c.id == act.id).children[-1]
        scene_id = scene_node.scene_id
        existing = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=existing.title,
                body=body,
                base_revision=existing.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata=metadata,
            ),
        )
        return scene_id

    def test_compile_once_matches_union_of_per_text_alias_match(self) -> None:
        self._add_scene_field("description", "long_text")
        self._add_scene_field("notes", "long_text")
        honor = self._make_lore("Honor Harrington", body="Captain of a ship.")
        manticore = self._make_lore("Manticore", entry_type="lore:location", body="A star system.")
        nimitz = self._make_lore("Nimitz", body="A treecat.")
        # Never mentioned anywhere — a negative control.
        self._make_lore("Cassandra Doe", body="A minor character.")

        body = "Honor Harrington walked onto the bridge of the flagship."
        description = "The fleet made planetfall at Manticore under a red sky."
        notes = "Nimitz rode on her shoulder the whole time."
        scene_id = self._make_scene(
            body=body, metadata={"description": description, "notes": notes}
        )
        scene = self.service.read_scene(scene_id)

        # New compile-once path.
        compile_once_ids = _scene_prose_ids(self.service, scene)

        # Old per-text path: one `_alias_match` call per field, unioned —
        # exactly what `_scene_prose_ids` did before #1505.
        per_text_ids: set[str] = set()
        for text in (body, description, notes):
            per_text_ids |= _alias_match(self.service, text, scene=scene)

        self.assertEqual(compile_once_ids, per_text_ids)
        self.assertEqual(compile_once_ids, {honor, manticore, nimitz})


if __name__ == "__main__":
    unittest.main()
