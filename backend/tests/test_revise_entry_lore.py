"""ADR-0057 (#1016) + docs/design/context-caching.md §4: the create/revise
brainstorm *declares* lore use via `use_lore()` and emits **no** lore inline —
the backend selects, dedups, and places lore at send time, tiered
stable/volatile.

This guards two things:

- the gate still flips (`use_lore()` sets the invocation flag `build_preview`
  reads into `lore_enabled`), so a lore-enabled chat still gets lore; and
- the template does **not** bake lore back into the rendered prompt — the
  render-time-emission regression this fix removed (it caused a frozen, often
  uncached copy that double-counted against the send-path lore block).

The always-lore actually *reaching* the brainstorm is now a send-path behavior,
guarded in `test_lore_cache_blocks.py`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateLoreEntryRequest,
    SaveLoreEntryRequest,
    SaveProjectNodeRequest,
)
from app.services.ai.helpers import create_environment_for_project


class ReviseEntryLoreGateTests(unittest.TestCase):
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

    def _render(self, inputs: dict):
        """Render the builtin revise-entry template, returning (text, env). The
        env carries `lore_invoked` — the gate flag `build_preview` captures."""
        prompt = self.service.read_prompt_entry("builtin-revise-entry")
        env = create_environment_for_project(self.service)
        text = env.from_string(prompt.body).render(inputs=inputs)
        return text, env

    def test_create_render_flips_the_lore_gate(self) -> None:
        # use_lore() sets the invocation flag, so the chat becomes lore-enabled
        # even though nothing is rendered inline.
        _, env = self._render({"entry": "", "entry_type": "lore:character"})
        self.assertTrue(env.lore_invoked[0])

    def test_revise_render_flips_the_lore_gate(self) -> None:
        subject = self._make_note("Alderman Vane", body="A city councilman.")
        _, env = self._render({"entry": subject, "entry_type": ""})
        self.assertTrue(env.lore_invoked[0])

    def test_render_emits_no_lore_inline_even_with_an_always_note(self) -> None:
        # The regression guard: an always-policy world note must NOT be baked into
        # the rendered prompt. The backend places it at send time instead.
        self._make_note(
            "Premise",
            policy="always",
            body="Shapeshifters live hidden in the modern city.",
        )
        rendered, _ = self._render({"entry": "", "entry_type": "lore:character"})
        self.assertNotIn("## Established lore", rendered)
        self.assertNotIn("<lore>", rendered)
        self.assertNotIn("Shapeshifters live hidden", rendered)
        self.assertNotIn('name="Premise"', rendered)

    def test_create_seed_lists_body_with_its_description(self) -> None:
        # #1067: the create brainstorm seed must list `body` among the fields to
        # develop, carrying its delineating description — otherwise the model is
        # never told the entry has a body to write. (Regressed when #1063
        # excluded body from the field roster globally.)
        rendered, _ = self._render({"entry": "", "entry_type": "lore:character"})
        self.assertIn("these fields to develop", rendered)
        self.assertIn("body (Body)", rendered)  # enumerated in the field list
        self.assertIn("do not restate", rendered.lower())  # body's steering description

    def test_revise_render_shows_body_once_not_as_empty_field(self) -> None:
        # #1067: in revise mode the body is shown as the entry's own prose
        # (`e.body`), never ALSO as an empty `### Body (body)` long_text field
        # header — body is filtered from the long_text value display.
        subject = self._make_note("Alderman Vane", body="A city councilman.")
        rendered, _ = self._render({"entry": subject, "entry_type": ""})
        self.assertIn("A city councilman.", rendered)  # the real body prose, shown once
        self.assertNotIn("### Body (body)", rendered)  # not a duplicate empty field header

    def test_brainstorm_seed_does_not_inherit_manuscript_pov(self) -> None:
        # #1076: a first-person project must NOT push the metadata-field
        # brainstorm into first person. revise-entry pulls in the GENERAL project
        # settings (units/spelling/…), never the prose-generation POV/tense, so
        # the model develops descriptive fields free of the manuscript's POV.
        # Rendered WITH project context so the project-settings snippet is live
        # (the _render harness passes only `inputs`, leaving the snippet inert).
        current = self.service.read_project_node()
        self.service.save_project_node(
            SaveProjectNodeRequest(
                title=current.title,
                body="",
                entry_type=current.entry_type,
                metadata={"pov_mode": "first", "tense": "present", "measurement_system": "metric"},
            )
        )
        prompt = self.service.read_prompt_entry("builtin-revise-entry")
        env = create_environment_for_project(self.service)
        rendered = env.from_string(prompt.body).render(
            inputs={"entry": "", "entry_type": "lore:character"},
            project=self.service.current_project(),
        )
        self.assertIn("metric", rendered)  # general facts still reach the brainstorm
        self.assertNotIn("Narrative POV", rendered)  # but POV/tense do not
        self.assertNotIn("First person", rendered)


if __name__ == "__main__":
    unittest.main()
