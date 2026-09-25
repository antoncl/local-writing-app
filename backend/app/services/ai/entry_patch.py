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

from app.services.project.schema_definition_validation import single_concrete_target

__all__ = [
    "NON_PROPOSABLE_FIELD_IDS",
    "NON_PROPOSABLE_FIELD_TYPES",
    "diagnose_garbled_reply",
    "is_proposable_field",
    "parse_entry_patch_json",
    "tag_vocabulary_target",
]

# The fields the AI is never asked to propose, and never allowed to write, even
# if a value validates (ADR-0046 §4): references (no reliable way to name the
# right node id — a wrong ref is a silent mis-link) and computed values
# (derived, not stored). The identity `id`/`entry_type` are structural. `title`
# is deliberately NOT here — an AI-proposed rename is a legitimate, adoptable
# change (the review flips it and the save applies the rename).
#
# ADR-0082 §2 / #1797: a NARROW carve-out exists for `entity_ref_list` — see
# `tag_vocabulary_target` — so this set alone is no longer the whole story for
# that type; `is_proposable_field` consults both.
NON_PROPOSABLE_FIELD_TYPES = frozenset({"computed", "entity_ref", "entity_ref_list"})
NON_PROPOSABLE_FIELD_IDS = frozenset({"id", "entry_type"})


def tag_vocabulary_target(field: Any, schema: Any) -> str | None:
    """The `tag:*` entry_type FQN an `entity_ref_list` field's `picker_config`
    resolves to, when the field is a proposable tag vocabulary — `None`
    otherwise.

    ADR-0082 §2 / #1797: unlike an ordinary `entity_ref`/`entity_ref_list`
    (excluded above — no reliable way to name the right node id), a field
    whose `picker_config` sets `create_missing` and resolves
    (`single_concrete_target`) to exactly one concrete `tag:*` entry type has
    an unambiguous target: the AI proposes plain TITLES, exactly as a writer
    would type them into the picker. The validator resolves a title matching
    an EXISTING tag (case-insensitive, within the vocabulary) to its id;
    an unmatched title is left as a plain string, never minted at validation
    — minting is deferred to the author's ACCEPT (mirroring the picker's own
    `create_missing`, which mints on the user's click, not while a typed name
    is merely under consideration), so a proposal the author rejects leaves
    the vocabulary untouched. Never an id in the prompt or the proposal.

    The one place `is_proposable_field` and the prompt roster (`_fields` in
    `helpers.py`, which surfaces the vocabulary alongside the field) resolve
    this, so they can't disagree on what counts as tag-shaped. `schema` may be
    `None` (a caller with no schema in hand) — then this is always `None`,
    matching the old exclude-everything behaviour."""
    if schema is None or getattr(field, "type", None) != "entity_ref_list":
        return None
    picker_config = getattr(field, "picker_config", None)
    if picker_config is None or not picker_config.create_missing:
        return None
    target = single_concrete_target(picker_config, schema)
    if target is None or target[0] != "tag":
        return None
    return target[1]


def is_proposable_field(field_id: str, field: Any, schema: Any) -> bool:
    """Whether the AI may propose a value for ``field_id``.

    The single predicate both the prompt's field catalog and the
    validate-on-return path consult, so the two never disagree about what is
    proposable (ADR-0046 §4). Excludes references / computed values, the
    structural ``id`` / ``entry_type``, and ``hidden`` fields — a field hidden
    from the author should not be shown to the model, and a stray proposal for
    one is dropped rather than written. ``field`` is the resolved
    ``MetadataFieldDefinition`` (or ``None`` when the id is unknown).

    ``schema`` is REQUIRED (round 2, Y4) — it is what resolves the ADR-0082
    §2 tag-vocabulary carve-out below. It was briefly optional (default
    ``None``, degrading an entity_ref_list to always-excluded); made required
    so a future caller with no schema in hand fails loudly at the call site
    instead of silently under-reporting a tag-vocabulary field as
    non-proposable. Pass the resolved schema even where the caller doesn't
    otherwise need it — every current call site already has one.
    """
    if field is None:
        return False
    if field_id in NON_PROPOSABLE_FIELD_IDS:
        return False
    if field.type in NON_PROPOSABLE_FIELD_TYPES and tag_vocabulary_target(field, schema) is None:
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


def _patch_shaped_or_empty(obj: dict[str, Any]) -> dict[str, Any] | None:
    """``obj`` if it is legal to honor as a patch — empty (``{}``, "nothing
    changed") or carrying a ``body``/``fields`` key — else ``None``.

    A non-empty object with neither key is wrong-shaped (#2195): a flat reply
    like ``{"title": ..., "aliases": ...}`` parses as valid JSON but is not the
    contracted envelope, and silently honoring it produced an empty patch with
    no reported reason (nothing in it maps to a real field). Garbled here
    triggers the caller's one firm retry (`run_entry_patch_extraction`) instead.
    """
    if not obj or "body" in obj or "fields" in obj:
        return obj
    return None


def parse_entry_patch_json(raw: str) -> dict[str, Any] | None:
    """Return the patch object parsed from ``raw``, or ``None`` if garbled.

    Tolerant of the ways a chatty / cheap model wraps the object: a code fence,
    leading/trailing prose, and — crucially — *other* braces in that prose (an
    example object, markdown, an emoji). It scans for every balanced ``{`` … ``}``
    span (string-aware, so a ``}`` inside a JSON string doesn't close it), parses
    each, and prefers one shaped like a patch (carries ``body`` or ``fields``)
    over an incidental object. Returns ``None`` when no balanced object parses to
    a JSON *object* at all (pure prose, no JSON), OR when the only candidate(s)
    found are wrong-shaped — non-empty and carrying neither "body" nor "fields"
    (#2195) — the genuinely garbled conditions, which the caller reports and
    retries. A bare ``{}`` (whole reply, or prose-wrapped) always stays legal.
    """
    if not raw or not raw.strip():
        return None

    candidate = _strip_code_fence(raw)

    # The whole (fence-stripped) reply as a single object — the clean, common
    # case. When the entire reply is one object there is nothing else it could be
    # (any braces are inside it), so honor it if patch-shaped (or empty); this
    # also covers a bare "{}" ("nothing changed", per the contract).
    whole = _as_json_dict(candidate)
    if whole is None:
        # #2197: a model that ends the reply one closer short (`…"}` where `…"}}`
        # was due) — deterministically, so the firm retry reproduces it. Repair
        # only a reply that IS one object and ended outside a string.
        whole = _as_json_dict(_close_unbalanced(candidate))
    if whole is not None:
        return _patch_shaped_or_empty(whole)

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
    # No patch-shaped object. Honor a lone embedded EMPTY object (a prose-wrapped
    # "{}" = "no changes"); a lone non-empty, non-patch-shaped object is no
    # longer honored (#2195) — multiple objects, or one wrong-shaped one, are
    # both garbled.
    return _patch_shaped_or_empty(embedded[0]) if len(embedded) == 1 else None


def _wrong_shape_reason(obj: dict[str, Any]) -> str:
    """The "parses, but not an entry" reason for a non-empty object carrying
    neither "body" nor "fields" (#2195/#2200) — names up to 5 of its keys so
    the author can see what the model actually sent."""
    keys = ", ".join(list(obj.keys())[:5])
    return (
        'The reply is JSON but not an entry: it has neither "body" nor '
        f'"fields" (it has: {keys}).'
    )


def _diagnose_starts_with_brace(candidate: str) -> str:
    """`diagnose_garbled_reply` for a candidate whose fence-stripped text
    opens with ``{`` — mirrors `parse_entry_patch_json`'s "whole reply is one
    object" path, including its `_close_unbalanced` repair, so the reason
    matches what the parser actually tried."""
    whole = _as_json_dict(candidate)
    if whole is None:
        repaired = _close_unbalanced(candidate)
        whole = _as_json_dict(repaired) if repaired else None
    if whole is not None:
        # Parsed (possibly after repair) but wasn't patch-shaped — the only
        # way this path is reached with a non-None `whole`, since a
        # patch-shaped/empty result would have made `parse_entry_patch_json`
        # succeed rather than call this diagnostic at all.
        return _wrong_shape_reason(whole)
    # A leading object that closes before the reply ends (`{…} Hope this
    # helps`) is judged by the parser's embedded scan, not as broken JSON.
    end = _object_end(candidate, 0)
    if end is not None and candidate[end:].strip():
        return _diagnose_embedded(candidate)
    _, ends_in_string = _brackets_outside_strings(candidate)
    if ends_in_string:
        return "The reply is cut off inside a text value."
    try:
        json.loads(candidate)
    except json.JSONDecodeError as exc:
        return (
            f"The reply isn't valid JSON: {exc.msg} at character "
            f"{exc.pos + 1} of {len(candidate)}."
        )
    # Unreachable in practice — `_as_json_dict` above already failed to parse
    # `candidate`, so `json.loads` failing too is the expected path.
    return "The reply isn't valid JSON."


def _diagnose_embedded(candidate: str) -> str:
    """`diagnose_garbled_reply` for a candidate that isn't a single top-level
    object — mirrors `parse_entry_patch_json`'s embedded-object scan."""
    embedded = [
        obj
        for span in _balanced_object_spans(candidate)
        if (obj := _as_json_dict(span)) is not None
    ]
    patch_shaped = [obj for obj in embedded if "body" in obj or "fields" in obj]
    if len(patch_shaped) >= 2:
        return (
            "The reply holds several entry-shaped JSON objects, so it isn't "
            "clear which one is the answer."
        )
    non_patch = [obj for obj in embedded if obj not in patch_shaped]
    if len(non_patch) == 1 and non_patch[0]:
        return _wrong_shape_reason(non_patch[0])
    if len(non_patch) >= 2:
        return "The reply holds several JSON objects, none shaped like an entry."
    return "The reply contains no JSON object."


def diagnose_garbled_reply(raw: str) -> str:
    """A plain-English reason `parse_entry_patch_json(raw)` returned `None`
    (#2200) — shown alongside the raw reply itself (#2201) so an author sees
    both WHAT the model said and WHY it didn't land, instead of just a bare
    "nothing to commit" notice. Deliberately re-treads `parse_entry_patch_json`
    rather than have it return a reason directly, so the happy path (by far
    the common case) stays a plain `dict | None`."""
    if not raw or not raw.strip():
        return "The reply was empty."
    candidate = _strip_code_fence(raw)
    if candidate.startswith("{"):
        return _diagnose_starts_with_brace(candidate)
    return _diagnose_embedded(candidate)


_CLOSER = {"{": "}", "[": "]"}


def _close_unbalanced(text: str) -> str:
    """``text`` with its unclosed ``{``/``[`` closed in nesting order, or ``""``
    when it isn't repairable that way: it must open with ``{``, every closer it
    does carry must match, and it must end outside a string — a reply cut off
    mid-value stays garbled rather than adopting half a value. String-aware the
    same way `_object_end` is."""
    if not text.startswith("{"):
        return ""
    brackets, ends_in_string = _brackets_outside_strings(text)
    if ends_in_string:
        return ""
    stack: list[str] = []
    for c in brackets:
        if c in _CLOSER:
            stack.append(_CLOSER[c])
        elif not stack or stack.pop() != c:
            return ""
    return text + "".join(reversed(stack)) if stack else ""


def _brackets_outside_strings(text: str) -> tuple[list[str], bool]:
    """The ``{}[]`` characters of ``text`` that sit outside JSON string
    literals, in order, and whether ``text`` ends inside an unterminated
    string. ``\\`` escapes the next char inside a string."""
    brackets: list[str] = []
    in_str = False
    escaped = False
    for c in text:
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{}[]":
            brackets.append(c)
    return brackets, in_str


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
