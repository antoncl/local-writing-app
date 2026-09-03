# The `field_contract` accumulator (ADR-0067 S1).
#
# "Which fields this prompt outputs" is authored Jinja, not a `commit.fields`
# list on the entry_type. A prompt registers the fields it will produce by
# looping the roster and storing each — `{% do field_contract.store(f) %}` — then
# renders the descriptor list with `{{ field_contract.render }}`. The registered
# set (`stored`) is read back at commit as the shape the model must return
# (ADR-0067 S2), so the contract shown at chat-start and the contract enforced at
# commit are the same authored set — they cannot drift.
#
# `render` is the ONE source of the per-field descriptor format (`- id (label) —
# type; …`); the extraction contract renders through it rather than re-deriving
# the shape inline. `store` takes a `fields()` descriptor dict verbatim, so the
# format tracks the roster the author already loops over.
from __future__ import annotations

from typing import Any


def _describe_field(f: dict[str, Any]) -> str:
    """One descriptor line for a `fields()` roster entry, e.g.
    ``- allegiance (Allegiance) — select; one of: order, chaos``. The item-shape
    clause for a `list` field mirrors the member descriptors so the model emits
    legal array items. Identical to the shape the extraction contract has always
    used — this is now its single source.

    ADR-0082 §2 / #1799: a `tag_vocabulary` key (a proposable tag-vocabulary
    `entity_ref_list`, stamped by `_fields()`) overrides the type clause to say
    the value is TITLES, not ids, and appends the "prefer existing" guidance
    plus the live vocabulary in the SAME line — so the instruction is
    actionable right where the model reads what to propose, not a separate
    paragraph it has to cross-reference."""
    tag_titles = f.get("tag_vocabulary")
    is_tag_field = tag_titles is not None
    type_clause = "tag titles — a JSON array of strings" if is_tag_field else f["type"]
    parts = [f"- {f['id']} ({f['label']}) — {type_clause}"]
    if f.get("options"):
        parts.append(f"; one of: {', '.join(f['options'])}")
    if f.get("description"):
        parts.append(f" — {f['description']}")
    items = f.get("items")
    if items:
        if f.get("item_scalar"):
            parts.append(f"; a JSON array of {items[0]['type']} values")
            if items[0].get("options"):
                parts.append(f", each one of: {', '.join(items[0]['options'])}")
        else:
            members = ", ".join(
                f"{m['key']} ({m['type']}"
                + (f"; one of: {', '.join(m['options'])}" if m.get("options") else "")
                + ")"
                for m in items
            )
            parts.append(f"; a JSON array of objects, each with keys: {members}")
    if is_tag_field:
        parts.append(
            " Tags are shared labels for grouping across entries. Prefer tags "
            "that already exist (listed below); propose a new one only if it "
            "would plausibly apply to other entries; propose at most two or "
            "three, never a keyword list."
        )
        parts.append(f" Existing tags: {', '.join(tag_titles)}." if tag_titles else " No tags exist yet.")
    return "".join(parts)


class FieldContract:
    """Per-render accumulator of the fields a prompt commits to producing.

    A prompt calls `store(f)` for each field it wants in the contract (a pure
    side effect via `{% do %}`); `render` emits their descriptor list; `stored`
    is the registered set the commit path reads as data. Deduped by field id and
    insertion-ordered — a field stored twice keeps its first descriptor and its
    first position, so a loop that revisits a field can't double it in the shape.
    One instance per render (registered in `register_helpers`), so it never leaks
    across renders — the same lifetime as the `used_nodes` slot.
    """

    def __init__(self) -> None:
        self._fields: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    def store(self, field: dict[str, Any]) -> str:
        """Register one `fields()` descriptor. Returns "" so `{% do %}` (or a
        stray `{{ }}`) emits nothing. Silently ignores a value without an `id`
        and a repeat of an already-stored id."""
        if not isinstance(field, dict):
            return ""
        field_id = field.get("id")
        if not isinstance(field_id, str) or field_id in self._seen:
            return ""
        self._seen.add(field_id)
        self._fields.append(field)
        return ""

    @property
    def stored(self) -> list[dict[str, Any]]:
        """The registered descriptors, in insertion order — read at commit to
        build and validate the JSON envelope (ADR-0067 S2)."""
        return list(self._fields)

    @property
    def render(self) -> str:
        """The descriptor list for the stored fields, one per line. Empty string
        when nothing was stored — the template supplies its own "(none)" copy,
        which is context-dependent (whether a body/title still applies)."""
        return "\n".join(_describe_field(f) for f in self._fields)
