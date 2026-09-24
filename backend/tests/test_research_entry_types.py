"""Research types are authorable like every other kind (#2174), and a note
moved in from lore is a note in the research tree (#2172).

Before #2174 the entry-type upsert checked the kind against a hand-spelled
list that left `research` off, so every save of a research type — a new
sub-type or an edit to a built-in — was refused with a 422, while the schema
panes listed the types as if they could be edited.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    EntryTypeDefinition,
    UpsertMetadataEntryTypeRequest,
)
from app.services.project.errors import ProjectServiceError


class ResearchEntryTypeUpsertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Research Types")
        self.layer_id = self.service._metadata_schema_layer_id(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _upsert(self, entry_type_id: str, definition: EntryTypeDefinition, *, allow_existing: bool = False):
        return self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self.layer_id,
                entry_type_id=entry_type_id,
                entry_type=definition,
                allow_existing=allow_existing,
            )
        )

    def test_a_research_sub_type_saves_and_resolves(self) -> None:
        schema = self._upsert(
            "research:source",
            EntryTypeDefinition(name="Source", kind="research", parent="research:note", fields=[]),
        )
        source = schema.entry_types["research:source"]
        self.assertEqual(source.kind, "research")
        self.assertEqual(source.parent, "research:note")

    def test_an_edit_to_a_built_in_research_type_saves(self) -> None:
        note = self.service.read_metadata_schema().entry_types["research:note"]
        schema = self._upsert(
            "research:note",
            EntryTypeDefinition(name=note.name, kind="research", parent=note.parent, fields=[], icon="flask"),
            allow_existing=True,
        )
        self.assertEqual(schema.entry_types["research:note"].icon, "flask")

    def test_an_unknown_kind_is_still_refused(self) -> None:
        with self.assertRaises(ProjectServiceError) as raised:
            self._upsert("widget:thing", EntryTypeDefinition(name="Thing", kind="widget", fields=[]))
        self.assertEqual(raised.exception.status_code, 422)


class MovedLoreNoteIsANoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Moved Note")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_tree_node_is_typed_research_note_and_takes_no_children(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Mills", entry_type="lore:note"))
        moved = self.service.move_lore_note_to_research(entry.id)

        node = next(child for child in moved.tree.root.children if child.scene_id == moved.note_id)
        self.assertEqual(node.type, "research:note")
        # A note is a leaf: create refuses to put anything under it (#2172 let it).
        with self.assertRaises(ProjectServiceError):
            self.service.create_research_node(
                CreateStructureNodeRequest(parent_id=node.id, title="Child", entry_type="research:note")
            )


if __name__ == "__main__":
    unittest.main()
