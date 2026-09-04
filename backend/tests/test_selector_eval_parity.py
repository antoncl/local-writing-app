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
    (identity when a case's id isn't a key) — the test double for
    `NodeIndex.canonical_id` (ADR-0082 §5 / #1805).

    Mirrors `NodeIndex._walk_merge_chain` exactly (#1805 X6): a chain-walk that
    REVISITS an id already on ITS OWN path resolves the START id (`node_id`) to
    ITSELF, not to whichever id the walk last reached. That single rule covers
    both halves of production's two-step build (`_resolve_canonical` + the
    `canonical.get(id, id)` lookup): an in-cycle id is explicitly recorded as
    its own survivor, while a cycle-ADJACENT id (one whose chain merely walks
    INTO a cycle without being a member of it) is never recorded at all, so the
    lookup's identity fallback applies — a direct single-id query like this one
    gets the same net answer, `node_id`, in both sub-cases."""

    def canonical_id(node_id: str) -> str:
        seen: list[str] = [node_id]
        current = node_id
        while current in redirects:
            next_id = redirects[current]
            if next_id in seen:
                return node_id
            seen.append(next_id)
            current = next_id
        return current

    return canonical_id


_CANONICAL_ID = _make_canonical_id(_CORPUS.get("redirects") or {})


def _make_ref_fields(fields: dict[str, Any]) -> frozenset[str]:
    """The `entity_ref`/`entity_ref_list` keys in the corpus's `schema.fields`
    map — the test double for `preview.py`'s `_ref_fields` (#1805 X1)."""
    return frozenset(key for key, f in fields.items() if (f or {}).get("type") in ("entity_ref", "entity_ref_list"))


_REF_FIELDS = _make_ref_fields(_CORPUS["schema"].get("fields") or {})


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
        case["expr"], nodes, is_descendant=_IS_DESCENDANT, ref_fields=_REF_FIELDS, canonical_id=_CANONICAL_ID
    )
    assert result == case["expected"]


def test_corpus_is_non_trivial() -> None:
    # A guard against an empty/renamed corpus silently passing the gate.
    assert len(_CORPUS["cases"]) >= 12
