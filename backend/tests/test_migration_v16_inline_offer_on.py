"""#2475 migration v16, end to end: opening a project at schema 15 gives its OWN
inline prompts an explicit `offer_on: [manuscript:scene]` — the scope they had
before inline prompts honoured `offer_on` — so nothing a writer authored drops
off the scene Revise menu. The pure function is covered in test_migrations.py;
this pins that the document pass actually reaches project-owned prompt files."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models.entries import CreatePromptEntryRequest, SavePromptEntryRequest
from app.models.schema import PromptContextStrategy, PromptOutput
from app.services.migrations import (
    CURRENT_VERSION,
    read_project_version,
    write_project_version,
)
from app.services.project_service import ProjectService


class InlinePromptOfferOnOpenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        service = ProjectService.created_at(self.root, "Book")
        self.inline_id = self._prompt(service, "My tighten", PromptOutput(handler="inline", destination="selection"))
        self.edits_id = self._prompt(service, "My edits", PromptOutput(handler="inline_edits"))
        self.chat_id = self._prompt(service, "My chat", None)
        self.targeted_id = self._prompt(
            service, "Lore only", PromptOutput(handler="inline", destination="selection"), offer_on=["lore:base"]
        )
        # Back to the pre-#2475 format: the project was last written at schema 15.
        write_project_version(self.root, 15)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _prompt(service: ProjectService, title: str, output: PromptOutput | None, offer_on: list[str] | None = None) -> str:
        created = service.create_prompt_entry(CreatePromptEntryRequest(title=title, entry_type="prompt:general"))
        service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title=title,
                body="{{ selection }}",
                base_revision=created.revision,
                entry_type="prompt:general",
                offer_on=offer_on or [],
                context_strategy=PromptContextStrategy(output=output) if output else None,
            ),
        )
        return created.id

    def test_opening_gives_owned_inline_prompts_the_scene_scope(self) -> None:
        service = ProjectService.opened_at(self.root)
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        self.assertEqual(service.read_prompt_entry(self.inline_id).offer_on, ["manuscript:scene"])
        self.assertEqual(service.read_prompt_entry(self.edits_id).offer_on, ["manuscript:scene"])
        # A conversation prompt keeps its empty offer_on (= offered nowhere, as before).
        self.assertEqual(service.read_prompt_entry(self.chat_id).offer_on, [])
        # A declared scope is the writer's choice and is never widened.
        self.assertEqual(service.read_prompt_entry(self.targeted_id).offer_on, ["lore:base"])


if __name__ == "__main__":
    unittest.main()
