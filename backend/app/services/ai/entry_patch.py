"""Parse an AI-committed entry patch out of a model's finalize reply.

ADR-0046 §4/§6.3: the brainstorm's commit turn returns a JSON object of the
shape ``{"body": <str>, "fields": {<field_id>: <value>}}``. The safety
guarantee is *validate-on-return* (done against the schema by the project
service, `validate_ai_entry_patch`), not constrained decoding — so this module
only has to turn a possibly-messy model reply into a Python dict, tolerantly.
A reply that cannot be read as a JSON object is *garbled*: the caller reports
that condition rather than silently writing nothing.

This is deliberately pure and provider-agnostic — no project, no schema — so it
is trivially testable and reused whatever produced the text.
"""
from __future__ import annotations

import json
from typing import Any

__all__ = [
    "NON_PROPOSABLE_FIELD_IDS",
    "NON_PROPOSABLE_FIELD_TYPES",
    "parse_entry_patch_json",
]

# The fields the AI is never asked to propose, and never allowed to write, even
# if a value validates (ADR-0046 §4): references (no reliable way to name the
# right node id — a wrong ref is a silent mis-link) and computed values
# (derived, not stored). The identity `id`/`entry_type` are structural. This is
# the single source both the prompt's field catalog and the validate-on-return
# path consult, so the two never disagree about what is proposable.
NON_PROPOSABLE_FIELD_TYPES = frozenset({"computed", "entity_ref", "entity_ref_list"})
NON_PROPOSABLE_FIELD_IDS = frozenset({"id", "entry_type"})


def _strip_code_fence(text: str) -> str:
    """Drop a single wrapping ```/```json fence if the whole reply is fenced.

    Models routinely wrap JSON in a fence despite being told not to; that is
    not garble, so we peel it. A reply with prose around a fenced block is
    handled by the brace-slice fallback in `parse_entry_patch_json`, not here.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    newline = stripped.find("\n")
    if newline == -1:
        return stripped
    # Everything after the opening ```lang line, up to a closing ``` if present.
    inner = stripped[newline + 1 :]
    fence_end = inner.rfind("```")
    if fence_end != -1:
        inner = inner[:fence_end]
    return inner.strip()


def parse_entry_patch_json(raw: str) -> dict[str, Any] | None:
    """Return the patch object parsed from ``raw``, or ``None`` if garbled.

    Tolerant of a wrapping code fence and of leading/trailing prose (falls back
    to the outermost ``{`` … ``}`` slice). Returns ``None`` when the result is
    not a JSON *object* — the caller treats that as the garbled condition.
    """
    if not raw or not raw.strip():
        return None

    candidate = _strip_code_fence(raw)

    for attempt in (candidate, _brace_slice(candidate)):
        if attempt is None:
            continue
        try:
            parsed = json.loads(attempt)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _brace_slice(text: str) -> str | None:
    """The substring from the first ``{`` to the last ``}``, if both exist."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
