"""ADR-0049 slice 1: the built-in Library resolves as a read-only ancestor
layer of shipped prompt nodes.

The Library is an app-owned floor beneath every project — the node analogue of
`default_schema.py` at the base of the schema merge. A fresh project sees the
shipped prompts (so `/roleplay` runs out of the box) without a single file
landing in its folders, and they are read-only in place: the only way to change
one is to clone it (slice 2). These tests pin resolve / no-clutter / read-only,
plus the temporary duplication lock (§7) between the bundled files and the
`default_body` they still shadow until slice 2 removes it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import SavePromptEntryRequest
from app.services.project.errors import ProjectServiceError

LIBRARY_IDS = {"builtin-roleplay", "builtin-revise-entry"}


class BuiltinLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Library Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _summaries(self) -> dict[str, object]:
        return {e.id: e for e in self.service.list_prompt_entries().entries}

    def test_library_prompts_resolve_in_a_fresh_project(self) -> None:
        entries = self._summaries()
        for lib_id in LIBRARY_IDS:
            self.assertIn(lib_id, entries, f"{lib_id} should resolve out of the box")
            self.assertEqual(entries[lib_id].source_layer_label, "Library")
        # And they read as inherited, not owned by the open project.
        own_layer_id = self.service._metadata_schema_layer_id(self.root)
        for lib_id in LIBRARY_IDS:
            self.assertNotEqual(entries[lib_id].source_layer_id, own_layer_id)

    def test_library_does_not_clutter_the_project_folder(self) -> None:
        """The core anti-requirement: shipped material is present but no file is
        written into the writer's folders."""
        # The prompts folder exists (scaffolded) but is empty of shipped files.
        self.assertEqual(list((self.root / "prompts").glob("*.md")), [])
        # Yet the shipped prompts resolve, and one reads back by id (runnable).
        self.assertTrue(set(self._summaries()) >= LIBRARY_IDS)
        roleplay = self.service.read_prompt_entry("builtin-roleplay")
        self.assertIn("character_thread", roleplay.body)

    def test_library_prompt_cannot_be_saved_in_place(self) -> None:
        before = self._library_path("builtin-roleplay").read_bytes()
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_prompt_entry(
                "builtin-roleplay",
                SavePromptEntryRequest(
                    title="Roleplay",
                    body="hijacked",
                    base_revision="",
                    entry_type="prompt:roleplay",
                    metadata={},
                ),
            )
        self.assertEqual(ctx.exception.status_code, 409)
        # The bundled app file is untouched — read-only by construction.
        self.assertEqual(self._library_path("builtin-roleplay").read_bytes(), before)

    def test_library_prompt_cannot_be_deleted(self) -> None:
        before = self._library_path("builtin-revise-entry").read_bytes()
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_prompt_entry("builtin-revise-entry")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self._library_path("builtin-revise-entry").read_bytes(), before)
        # Still listed after the refused delete.
        self.assertIn("builtin-revise-entry", self._summaries())

    def test_owned_prompt_coexists_with_the_library(self) -> None:
        created = self.service.create_prompt_entry(
            type("R", (), {"title": "Mine", "entry_type": "prompt:general"})()
        )
        entries = self._summaries()
        self.assertIn(created.id, entries)
        self.assertTrue(set(entries) >= LIBRARY_IDS)
        # The owned prompt is editable in place (the guard only bites inherited).
        own = self.service.read_prompt_entry(created.id)
        self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Mine",
                body="my body",
                base_revision=own.revision,
                entry_type="prompt:general",
                metadata={},
            ),
        )

    def test_bundled_files_match_the_schema_defaults(self) -> None:
        """Temporary-duplication lock (§7): until slice 2 removes `default_body`,
        the bundled Library node and the type default it shadows must stay in
        sync — otherwise 'create a new prompt of this type' and the Library would
        ship divergent bodies."""
        schema = self.service.read_metadata_schema()
        entries = self._summaries()
        pairs = [
            ("builtin-roleplay", "prompt:roleplay"),
            ("builtin-revise-entry", "prompt:revise:entry"),
        ]
        for lib_id, type_key in pairs:
            type_def = schema.entry_types[type_key]
            self.assertEqual(entries[lib_id].body.rstrip(), type_def.default_body.rstrip())
            got = [i.model_dump(exclude_none=True) for i in entries[lib_id].inputs]
            want = [i.model_dump(exclude_none=True) for i in type_def.default_inputs]
            self.assertEqual(got, want)

    def _library_path(self, entry_id: str) -> Path:
        return self.service._build_node_index().by_id[entry_id].path


if __name__ == "__main__":
    unittest.main()
