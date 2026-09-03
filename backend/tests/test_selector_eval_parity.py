"""Backend half of the cross-runtime selector-evaluator parity gate.

Runs the shared corpus (`spec/selector-eval-corpus.json`) through the Python
`evaluate_selector_membership`. The frontend half
(`frontend/src/lib/views/selectorEvalParity.test.ts`) runs the SAME corpus
through `evaluateView`. Both must return each case's `expected` verbatim, so the
two evaluators cannot silently drift — the picker's live count and the AI's
actual context stay one truth (ADR-0074 slice 5). Add a case here and the
frontend gate must reproduce it too, and vice versa.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.ai.selector_eval import (
    SelectorNode,
    evaluate_selector_membership,
    selector_references,
)

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "spec" / "selector-eval-corpus.json"
_CORPUS = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def _make_is_descendant(entry_types: dict[str, Any]):
    def is_descendant(entry_type: str, target: str) -> bool:
        seen: set[str] = set()
        current: str | None = entry_type
        while current is not None and current not in seen:
            if current == target:
                return True
            seen.add(current)
            current = (entry_types.get(current) or {}).get("parent")
        return False

    return is_descendant


_IS_DESCENDANT = _make_is_descendant(_CORPUS["schema"]["entry_types"])


def _make_canonical_id(redirects: dict[str, str]):
    """A merged-tag redirect follower built from the corpus's `redirects` map
    (identity when a case's id isn't a key), chain-walked to its end — the test
    double for `NodeIndex.canonical_id` (ADR-0082 §5 / #1805)."""

    def canonical_id(node_id: str) -> str:
        seen: set[str] = set()
        current = node_id
        while current in redirects and current not in seen:
            seen.add(current)
            current = redirects[current]
        return current

    return canonical_id


_CANONICAL_ID = _make_canonical_id(_CORPUS.get("redirects") or {})


@pytest.mark.parametrize("case", _CORPUS["cases"], ids=lambda c: c["name"])
def test_selector_eval_parity(case: dict[str, Any]) -> None:
    # Node-side references are canonicalised by the CALLER (`preview.py`'s
    # `_canonical_references`), not by `evaluate_selector_membership` itself —
    # this mirrors that here so the corpus exercises the same contract.
    nodes = [
        SelectorNode(
            n["id"],
            n["entry_type"],
            frozenset(_CANONICAL_ID(ref) for ref in selector_references(n.get("metadata"))),
            n.get("metadata") or {},
        )
        for n in case["nodes"]
    ]
    result = evaluate_selector_membership(
        case["expr"], nodes, is_descendant=_IS_DESCENDANT, canonical_id=_CANONICAL_ID
    )
    assert result == case["expected"]


def test_corpus_is_non_trivial() -> None:
    # A guard against an empty/renamed corpus silently passing the gate.
    assert len(_CORPUS["cases"]) >= 12
