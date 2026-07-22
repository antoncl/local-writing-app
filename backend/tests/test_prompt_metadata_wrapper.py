"""#28: a prompt's stored file drops the `metadata: {}` wrapper when empty.

A prompt has almost nothing to say about itself (title + entry_type is
essentially it) and its Jinja body is content, not metadata — so the empty
`metadata: {}` map is no longer written. A non-empty map is still written,
and reads tolerate the key being absent (it normalises back to {})."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import SavePromptEntryRequest


class PromptMetadataWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Prompt Metadata Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _raw_file(self, entry_id: str) -> str:
        path = self.service._path_for_node_id(entry_id, "prompt")
        return path.read_text(encoding="utf-8")

    def test_created_prompt_omits_empty_metadata(self) -> None:
        created = self.service.create_prompt_entry(
            type("R", (), {"title": "No Wrapper", "entry_type": "prompt:general"})()
        )
        raw = self._raw_file(created.id)
        self.assertNotIn("metadata:", raw)
        # Read path still works: absent key normalises to {}.
        self.assertEqual(self.service.read_prompt_entry(created.id).metadata, {})

    def test_saved_prompt_omits_empty_metadata(self) -> None:
        created = self.service.create_prompt_entry(
            type("R", (), {"title": "Saved Empty", "entry_type": "prompt:general"})()
        )
        self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Saved Empty",
                body="Hello {{ scene.title }}",
                base_revision=created.revision,
                entry_type="prompt:general",
                metadata={},
            ),
        )
        self.assertNotIn("metadata:", self._raw_file(created.id))

    def test_non_empty_metadata_is_still_written(self) -> None:
        created = self.service.create_prompt_entry(
            type("R", (), {"title": "Has Meta", "entry_type": "prompt:general"})()
        )
        self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Has Meta",
                body="Body",
                base_revision=created.revision,
                entry_type="prompt:general",
                metadata={"author_note": "keep me"},
            ),
        )
        raw = self._raw_file(created.id)
        self.assertIn("metadata:", raw)
        self.assertIn("author_note", raw)
        self.assertEqual(
            self.service.read_prompt_entry(created.id).metadata,
            {"author_note": "keep me"},
        )


if __name__ == "__main__":
    unittest.main()
