"""ADR-0075 §5 — the FE/BE parity gate.

Drives the backend's pure positional matcher (`_compile_name_matcher` /
`_scan_name_matcher` in `app.services.ai.helpers`) against the hand-authored
oracle at `spec/implicit-context-corpus.json`, shared with the frontend's
vitest counterpart. Both suites assert against the SAME corpus — neither
regenerates it from a matcher (see the corpus file's `_comment`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.ai.name_matcher import (
    _norm,
    compile_name_matcher,
    normalise_name,
    scan_name_matcher,
)

CORPUS_PATH = Path(__file__).resolve().parents[2] / "spec" / "implicit-context-corpus.json"


def _load_cases() -> list[dict[str, Any]]:
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return data["cases"]


CASES = _load_cases()


def test_normalise_name_is_the_matchers_own_norm() -> None:
    """ADR-0091 §2: `normalise_name` (the public alias `change_candidates.py`
    imports for the outbound Propagate matcher) must be literally this
    module's own dedup/lookup key — never a second implementation that could
    drift from the §5 parity surface this file drives."""
    assert normalise_name is _norm


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_corpus_case(case: dict[str, Any]) -> None:
    entries = [(entity["id"], [entity["title"], *entity["aliases"]]) for entity in case["entities"]]
    matcher = compile_name_matcher(entries)
    hits = scan_name_matcher(matcher, case["text"])

    actual = sorted(
        ((h.entry_id, h.start, h.end, h.matched_text) for h in hits),
        key=lambda t: t[1],
    )
    expected = sorted(
        ((e["id"], e["start"], e["end"], e["matchedText"]) for e in case["expected"]),
        key=lambda t: t[1],
    )
    assert actual == expected
