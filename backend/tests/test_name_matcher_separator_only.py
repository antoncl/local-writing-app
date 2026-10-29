"""#2567: a separator-only name ("-") normalises to "" and once compiled into
an empty alternative. `finditer` stepped past each empty match, but every one
mapped back to the offending entry — a phantom hit in practically any text.
Mirrors `implicitContextMatcher.separator.test.ts`.
"""

from __future__ import annotations

from app.services.ai.name_matcher import (
    NameMatch,
    compile_name_matcher,
    scan_name_matcher,
)


def test_separator_only_alias_adds_no_phantom_hit() -> None:
    matcher = compile_name_matcher([("honor_1", ["Honor", "-", "--", "- -"])])
    hits = scan_name_matcher(matcher, "Honor met the admiral.")
    assert hits == [NameMatch(0, 5, "honor_1", "Honor")]


def test_only_separator_names_compile_to_an_empty_matcher() -> None:
    matcher = compile_name_matcher([("dash_1", ["-", "--"])])
    assert matcher.name_to_id == {}
    assert scan_name_matcher(matcher, "any text at all") == []
