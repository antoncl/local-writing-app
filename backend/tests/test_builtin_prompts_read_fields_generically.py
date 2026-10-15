"""Built-in prompts read a node's fields generically, not by hard-coded id (#2511).

A user models their story through the schema: a field they add to a scene (a
beat list, the value at stake) must reach the model without any prompt naming
it. Draft scene once named `summary` and `dynamics` and nothing else, so a
scene's own design never arrived. A built-in reads fields through `fields()` +
`field_value()` — selected by `proposable` ("AI may write this field when
committing a brainstorm") — or through a shared snippet that does (Scene brief,
Project settings, Prose generation settings).

This guard fails on a new `<node>.metadata.<id>` / `'<id>' in <node>.metadata`
read in a built-in. The exceptions below are named, each with its reason; a new
one has to argue its case in its PR.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "app" / "builtin_library" / "prompts"

# `x.metadata.field`, `x.metadata["field"]`, `x.metadata.get("field")`,
# `'field' in x.metadata`.
_READS = (
    re.compile(r"\b\w+\.metadata\.(?!get\b|items\b|keys\b|values\b)(\w+)"),
    re.compile(r"\b\w+\.metadata\.get\(\s*[\"'](\w+)[\"']"),
    re.compile(r"\b\w+\.metadata\[\s*[\"'](\w+)[\"']\s*\]"),
    re.compile(r"[\"'](\w+)[\"']\s+in\s+\w+\.metadata\b"),
)

# (file, field) → why the prompt names the field.
EXCEPTIONS = {
    # A roleplay scene is played, not drafted to a design: Dynamics is the one
    # scene field read as stage direction, and a beat list would railroad it.
    ("roleplay.md", "dynamics"): "roleplay direction only",
    # Hand-rolled project settings that predate the "Project settings" snippet.
    ("roleplay.md", "tense"): "project settings, not yet the snippet",
    ("roleplay.md", "measurement_system"): "project settings, not yet the snippet",
    ("roleplay.md", "spelling"): "project settings, not yet the snippet",
    ("impersonate.md", "spelling"): "project settings, not yet the snippet",
}


def _hard_coded_reads() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(PROMPTS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for pattern in _READS:
            found.update((path.name, m.group(1)) for m in pattern.finditer(text))
    return found


class BuiltinPromptsReadFieldsGenericallyTests(unittest.TestCase):
    def test_no_built_in_names_a_field_it_should_read_generically(self) -> None:
        unexpected = sorted(_hard_coded_reads() - EXCEPTIONS.keys())
        self.assertEqual(
            unexpected, [],
            "a built-in reads these fields by id; read them through fields()/field_value() "
            "or a shared snippet (Scene brief, Project settings) instead",
        )

    def test_every_exception_is_still_needed(self) -> None:
        # A fixed exception is deleted, so the list only ever shrinks.
        self.assertEqual(sorted(EXCEPTIONS.keys() - _hard_coded_reads()), [])

    def test_the_guard_sees_a_hard_coded_read(self) -> None:
        # Mutation check: the patterns match the shape Draft scene used to have.
        text = ("{% if e.metadata.dynamics %}{{ e.metadata['beats'] }}{% if 'x' in e.metadata %}"
                '{{ e.metadata.get("y") }}{{ e.metadata.get(f.id) }}')
        hits = {m.group(1) for p in _READS for m in p.finditer(text)}
        self.assertEqual(hits, {"dynamics", "beats", "x", "y"})


if __name__ == "__main__":
    unittest.main()
