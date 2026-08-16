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
    "is_proposable_field",
    "parse_entry_patch_json",
]

# The fields the AI is never asked to propose, and never allowed to write, even
# if a value validates (ADR-0046 §4): references (no reliable way to name the
# right node id — a wrong ref is a silent mis-link) and computed values
# (derived, not stored). The identity `id`/`entry_type` are structural. `title`
# is deliberately NOT here — an AI-proposed rename is a legitimate, adoptable
# change (the review flips it and the save applies the rename).
NON_PROPOSABLE_FIELD_TYPES = frozenset({"computed", "entity_ref", "entity_ref_list"})
NON_PROPOSABLE_FIELD_IDS = frozenset({"id", "entry_type"})


def is_proposable_field(field_id: str, field: Any) -> bool:
    """Whether the AI may propose a value for ``field_id``.

    The single predicate both the prompt's field catalog and the
    validate-on-return path consult, so the two never disagree about what is
    proposable (ADR-0046 §4). Excludes references / computed values, the
    structural ``id`` / ``entry_type``, and ``hidden`` fields — a field hidden
    from the author should not be shown to the model, and a stray proposal for
    one is dropped rather than written. ``field`` is the resolved
    ``MetadataFieldDefinition`` (or ``None`` when the id is unknown).
    """
    if field is None:
        return False
    if field_id in NON_PROPOSABLE_FIELD_IDS:
        return False
    if field.type in NON_PROPOSABLE_FIELD_TYPES:
        return False
    # ADR-0059 §E: a field can declare itself off-limits to AI authorship
    # (default True). `body` never reaches here — it enforces the flag at its
    # own top-level-key sites, not through this fields-object predicate.
    if not getattr(field, "ai_proposable", True):
        return False
    return not getattr(field, "hidden", False)


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

    Tolerant of the ways a chatty / cheap model wraps the object: a code fence,
    leading/trailing prose, and — crucially — *other* braces in that prose (an
    example object, markdown, an emoji). It scans for every balanced ``{`` … ``}``
    span (string-aware, so a ``}`` inside a JSON string doesn't close it), parses
    each, and prefers one shaped like a patch (carries ``body`` or ``fields``)
    over an incidental object. Returns ``None`` only when no balanced object
    parses to a JSON *object* — the genuinely garbled condition (pure prose, or
    no JSON at all), which the caller reports and retries.
    """
    if not raw or not raw.strip():
        return None

    candidate = _strip_code_fence(raw)

    # The whole (fence-stripped) reply as a single object — the clean, common
    # case. When the entire reply is one object there is nothing else it could be
    # (any braces are inside it), so honor it directly; this also covers a bare
    # "{}" ("nothing changed", per the contract).
    whole = _as_json_dict(candidate)
    if whole is not None:
        return whole

    # Prose around one or more objects: scan them out (string-aware) and pick the
    # patch. A patch carries "body" and/or "fields". `is not None`, not
    # truthiness, so a legitimate empty "{}" isn't dropped.
    embedded = [
        obj
        for span in _balanced_object_spans(candidate)
        if (obj := _as_json_dict(span)) is not None
    ]
    patch_shaped = [obj for obj in embedded if "body" in obj or "fields" in obj]
    if len(patch_shaped) == 1:
        return patch_shaped[0]
    if len(patch_shaped) >= 2:
        # The contract shows the shape, so a chatty model may emit a filled-in
        # example AND the real answer. We can't reliably tell which is the patch,
        # so report garbled and let the caller's firmer retry get a single object
        # — safer than silently adopting the example.
        return None
    # No patch-shaped object. Honor a lone embedded object (a prose-wrapped "{}" =
    # "no changes", or one slightly-misshapen object); multiple non-patch objects
    # are ambiguous → garbled.
    return embedded[0] if len(embedded) == 1 else None


def _as_json_dict(text: str) -> dict[str, Any] | None:
    """Parse ``text`` as JSON, returning it only if it is an object."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _object_end(text: str, start: int) -> int | None:
    """Index just past the ``}`` that balances the ``{`` at ``start``, or ``None``
    if it never closes. String-aware: braces inside a JSON string literal don't
    count, and ``\\`` escapes the next char, so a value like ``"a } b"`` can't
    truncate the object."""
    depth = 0
    in_str = False
    escaped = False
    for j in range(start, len(text)):
        c = text[j]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def _balanced_object_spans(text: str) -> list[str]:
    """Every top-level balanced ``{`` … ``}`` substring, in order of appearance.

    Nested objects are absorbed into their enclosing top-level span (a patch's
    ``fields`` map is one object, not two). An unbalanced ``{`` is skipped so a
    later well-formed object is still found. Linear over the string.
    """
    spans: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        end = _object_end(text, i)
        if end is None:
            i += 1
        else:
            spans.append(text[i:end])
            i = end
    return spans
