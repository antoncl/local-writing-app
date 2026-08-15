"""ADR-0057 (#1016): the create/revise brainstorm surfaces `context_policy: always`
lore.

`revise-entry.md` now calls `relevant_lore()`, so the `always` wholesale union
(`helpers._always_included_lore_ids`) reaches the prompt. The regression this
guards: a create-character brainstorm ignored two `lore:note`s the writer had
marked Context policy = Always, because that template never called
`relevant_lore()` and so nothing surfaced the always union for it.

`relevant_lore()` is called bare — the `scene` arg (the mutation-resolution
anchor) defaults to None, which a brainstorm has no use for; the always union
resolves without it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.ai.helpers import create_environment_for_project


class ReviseEntryLoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Revise Entry Lore Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_note(self, title: str, *, policy: str | None = None, body: str = "") -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:note")
        )
        existing = self.service.read_lore_entry(created.id)
        metadata: dict[str, str] = {}
        if policy is not None:
            metadata["context_policy"] = policy
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata=metadata,
            ),
        )
        return created.id

    def _render(self, inputs: dict) -> str:
        # The context is intentionally minimal — no `scene` key — because the
        # template now calls `relevant_lore()` bare. That the render does not
        # raise on the missing `scene` is itself part of what this guards.
        prompt = self.service.read_prompt_entry("builtin-revise-entry")
        env = create_environment_for_project(self.service)
        return env.from_string(prompt.body).render(input=inputs)

    def _render_create(self) -> str:
        return self._render({"entry": "", "entry_type": "lore:character"})

    def test_always_note_appears_in_create_brainstorm(self) -> None:
        # The dogfooding symptom: an always-policy world note must reach a
        # create-character brainstorm even though it is never mentioned.
        self._make_note(
            "Feral Line: Urban Bestiary universe",
            policy="always",
            body="Shapeshifters live hidden in the modern city.",
        )
        rendered = self._render_create()
        self.assertIn("## Established lore", rendered)
        self.assertIn('name="Feral Line: Urban Bestiary universe"', rendered)
        self.assertIn("Shapeshifters live hidden", rendered)

    def test_always_note_appears_in_revise_mode(self) -> None:
        # The other template branch: revising an existing entry must also carry
        # the always union.
        self._make_note("Premise", policy="always", body="A short premise.")
        subject = self._make_note("Alderman Vane", body="A city councilman.")
        rendered = self._render({"entry": subject, "entry_type": ""})
        self.assertIn("## Established lore", rendered)
        self.assertIn('name="Premise"', rendered)

    def test_auto_note_not_dumped_when_unmentioned(self) -> None:
        # Only the always union (and scene-relevant lore) is surfaced — a plain
        # auto-policy note with no mention and no scene must NOT appear. The
        # brainstorm doesn't dump the whole lore library.
        self._make_note("Backstory dump", policy="auto", body="Long unrelated history.")
        rendered = self._render_create()
        self.assertNotIn("Backstory dump", rendered)
        self.assertNotIn("## Established lore", rendered)

    def test_no_lore_section_without_relevant_entries(self) -> None:
        # No always entries at all → no heading, no empty <lore> block.
        rendered = self._render_create()
        self.assertNotIn("## Established lore", rendered)
        self.assertNotIn("<lore>", rendered)


if __name__ == "__main__":
    unittest.main()
