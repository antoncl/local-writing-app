"""Validate flags whole-body code-fenced lore, and the unwrap preview (#1628)."""
from __future__ import annotations

from metadata_validation_base import MetadataValidationBase

from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.project.errors import ProjectServiceError


class CodeFenceValidationTests(MetadataValidationBase):
    def _make_note(self, title: str, body: str) -> str:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:note")
        )
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=entry.revision,
                entry_type="lore:note",
                metadata={},
            ),
        )
        return entry.id

    def test_whole_body_markdown_fence_is_flagged_but_not_an_error(self) -> None:
        note_id = self._make_note("Shell", "```markdown\n# Shell\n\nA world note.\n```")

        validation = self.service.validate_project()

        flagged = {item.id: item for item in validation.code_fenced_bodies}
        self.assertIn(note_id, flagged)
        self.assertEqual(flagged[note_id].kind, "lore")
        self.assertEqual(flagged[note_id].title, "Shell")
        # Advisory, not an integrity error — the project still validates.
        self.assertTrue(validation.valid)
        self.assertEqual(validation.errors, [])

    def test_plain_prose_and_real_code_notes_are_not_flagged(self) -> None:
        self._make_note("Prose", "# Title\n\nOrdinary prose, no fence.")
        self._make_note("Snippet", "```python\nprint('a genuine code note')\n```")

        validation = self.service.validate_project()

        self.assertEqual(validation.code_fenced_bodies, [])

    def test_unwrap_preview_returns_the_inner_prose(self) -> None:
        note_id = self._make_note("Shell", "```markdown\n# Shell\n\nA world note.\n```")

        preview = self.service.preview_lore_code_fence_unwrap(note_id)

        self.assertEqual(preview, "# Shell\n\nA world note.")

    def test_unwrap_preview_409s_when_body_is_not_a_wrapping_fence(self) -> None:
        note_id = self._make_note("Prose", "# Title\n\nOrdinary prose.")

        with self.assertRaises(ProjectServiceError) as caught:
            self.service.preview_lore_code_fence_unwrap(note_id)
        self.assertEqual(caught.exception.status_code, 409)
