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
