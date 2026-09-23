"""#2142: `mask_emphasis_underscores` — the fix at the scan surface for
markdown emphasis underscores hiding names from the backend's positional
matcher (ADR-0075 §3's boundary class treats `_` as a name character, so
`_The Implant_` has no boundary and never matches).
"""

from __future__ import annotations

import pytest

from app.services.ai.name_matcher import (
    compile_name_matcher,
    mask_emphasis_underscores,
    scan_name_matcher,
)

MASKING_CASES = [
    (
        "single-word italics, both delimiters blanked",
        "(see _The Implant_)",
        "(see  The Implant )",
    ),
    (
        "strong (double-underscore) runs, both blanked",
        "a word __strong__ word",
        "a word   strong   word",
    ),
    (
        "snake_case stays untouched",
        "the snake_case identifier",
        "the snake_case identifier",
    ),
    (
        "a node id stays untouched",
        "ref lore_3071847c0f here",
        "ref lore_3071847c0f here",
    ),
    (
        "a leading underscore-italic at start of text",
        "_x_ marks the spot",
        " x  marks the spot",
    ),
    (
        "an isolated underscore between punctuation is left alone",
        "(_)",
        "(_)",
    ),
]


@pytest.mark.parametrize("name,text,expected", MASKING_CASES, ids=[c[0] for c in MASKING_CASES])
def test_masking_cases(name: str, text: str, expected: str) -> None:
    assert mask_emphasis_underscores(text) == expected


@pytest.mark.parametrize("name,text,expected", MASKING_CASES, ids=[c[0] for c in MASKING_CASES])
def test_masking_preserves_length(name: str, text: str, expected: str) -> None:
    assert len(mask_emphasis_underscores(text)) == len(text)


def test_masking_preserves_length_on_arbitrary_text() -> None:
    text = "He heard whispers of _The Deserter's Rumour_. Meanwhile snake_case __bold__ _."
    assert len(mask_emphasis_underscores(text)) == len(text)


def test_empty_string_stays_empty() -> None:
    assert mask_emphasis_underscores("") == ""


def test_scan_name_matcher_on_masked_text_finds_the_underscore_italicised_name() -> None:
    """Pins #2142: the raw text does NOT match (no boundary either side of
    `_The Deserter's Rumour_`), but the masked text does."""
    matcher = compile_name_matcher([("rumour_1", ["The Deserter's Rumour"])])
    raw = "He heard whispers of _The Deserter's Rumour_."
    masked = mask_emphasis_underscores(raw)

    assert scan_name_matcher(matcher, raw) == []
    hits = scan_name_matcher(matcher, masked)
    assert len(hits) == 1
    assert hits[0].entry_id == "rumour_1"
    assert hits[0].matched_text == "The Deserter's Rumour"
