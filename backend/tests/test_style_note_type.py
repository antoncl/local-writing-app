"""The Style note sub-type and the built-in style builder (ADR-0101 Amendment 2, #2627).

The type only decides where *Build a style note* is offered and what the writer sees as a
style note. No prose prompt reads it: a style note reaches the prose because the writer sets
it to Always include, and a plain note with the same text works the same.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

import app
from app.services.project.default_entry_types import DEFAULT_ENTRY_TYPES

PROMPTS = Path(app.__file__).parent / "builtin_library" / "prompts"
BUILDER = PROMPTS / "build-a-style-note.md"


def front_matter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n", 2)[1])


class StyleNoteTypeTests(unittest.TestCase):
    def test_style_note_is_a_note_with_nothing_of_its_own(self) -> None:
        style = DEFAULT_ENTRY_TYPES["lore:style_note"]
        self.assertEqual(style["parent"], "lore:note")
        self.assertEqual(style["kind"], "lore")
        self.assertEqual(style["fields"], [])

    def test_the_builder_is_offered_on_and_creates_a_style_note(self) -> None:
        front = front_matter(BUILDER)
        self.assertEqual(front["title"], "Build a style note")
        self.assertEqual(front["offer_on"], ["lore:style_note"])
        self.assertIn('else "lore:style_note"', BUILDER.read_text(encoding="utf-8"))
        inputs = {i["name"]: i for i in front["inputs"]}
        self.assertTrue(inputs["entry_type"]["hidden"])
        self.assertFalse(inputs["entry"]["required"])

    def test_the_builder_reaches_plain_notes_made_before_the_sub_type(self) -> None:
        # `type` is an exact match and `descendants_of` takes the type and its sub-types
        # (models_views.py), so only descendants_of of lore:note offers both.
        inputs = {i["name"]: i for i in front_matter(BUILDER)["inputs"]}
        for name in ("entry", "inherited"):
            with self.subTest(input=name):
                self.assertEqual(inputs[name]["target"]["sources"][0]["expr"], {"descendants_of": "lore:note"})

    def test_no_other_built_in_names_the_type(self) -> None:
        # A tripwire, not a proof: it catches a prompt that selects or branches on
        # lore:style_note by name, which would make the type more than an offer site.
        for path in sorted(PROMPTS.glob("*.md")):
            if path == BUILDER:
                continue
            with self.subTest(prompt=path.name):
                self.assertIsNone(re.search(r"style_note", path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()


class BuilderOpeningTests(unittest.TestCase):
    """The builder ends with a user turn of its own, so Send works on an empty composer
    and the model opens by saying what to paste."""

    def setUp(self) -> None:
        from tempfile import TemporaryDirectory

        from project_fixtures import open_test_project

        self.temp_dir = TemporaryDirectory()
        self.service = open_test_project(Path(self.temp_dir.name).resolve() / "project", "Builder Tests")
        self.source = BUILDER.read_text(encoding="utf-8").split("---\n", 2)[2]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _messages(self, inputs: dict) -> list[tuple[str, str]]:
        from app.services.ai.preview import PreviewRequest, build_preview

        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.source, target_scene_id="", session_id=None,
                inputs=inputs, text_before="", text_after="", commit=False,
            ),
        )
        return [(m.role, m.text.strip()) for m in rendered.messages if m.text.strip()]

    def test_a_new_note_opens_on_a_user_turn(self) -> None:
        messages = self._messages({"entry": "", "inherited": [], "entry_type": ""})
        self.assertEqual(messages[-1], ("user", "I'd like to build a style note."))
        self.assertIn("If the author hasn't pasted any yet, open by saying", messages[0][1])

    def test_a_revision_names_the_note(self) -> None:
        from app.models import CreateLoreEntryRequest

        note = self.service.create_lore_entry(CreateLoreEntryRequest(title="House style", entry_type="lore:style_note"))
        messages = self._messages({"entry": note.id, "inherited": [], "entry_type": ""})
        self.assertEqual(messages[-1], ("user", "I'd like to revise the style note House style."))
