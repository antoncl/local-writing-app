"""Summary-field fallback rule for an entry type (#2008).

`summary_fields` lets an entry type NOMINATE which fields form its summary —
what a list row's detail line, a reference peek card, and the AI's reference
qualifier (`lore_block.py`) show. When a type nominates nothing, the fallback
picks the first few present scalar values in schema order, so every type
still shows something useful without every author having to opt in.

Pure — no I/O, no project/service dependency — so both the AI lore-block
renderer and any future UI-facing endpoint can call it against an already-
resolved `MetadataSchema` and a plain metadata dict. The one place a caller
might want I/O — naming the target of a nominated `entity_ref`/
`entity_ref_list` field — is taken by INJECTION: `summary_values` accepts an
optional `resolve_title` callback rather than reading anything itself.

IMPORTANT: `frontend/src/lib/utils/summaryFields.ts` mirrors this rule for the
UI (list rows, reference peek cards) — including the same injection shape
(its `resolveTitle` callback is the frontend twin of `resolve_title`). The two
must change together — a drift between them means a row's detail line and
the AI's reference qualifier disagree on what a node's "summary" is.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import EntryTypeDefinition, MetadataSchema

# Field types the fallback (no explicit nomination) draws from: plain scalars
# a reader can skim in a detail line. Excludes `long_text` (too long for a
# line), `entity_ref`/`entity_ref_list` (a relationship, not a summary scalar
# for the UNNOMINATED heuristic to guess at — an EXPLICIT nomination of one
# still renders, via the `resolve_title` injection below), `list` (structured,
# not a scalar), `color` (a swatch, not informative text), and `computed`
# (derived bookkeeping).
SUMMARY_SCALAR_TYPES = frozenset({"text", "number", "boolean", "select", "multi_select", "date"})

# How many fallback fields the no-nomination heuristic picks.
_FALLBACK_COUNT = 3


def _value_present(value: Any) -> bool:
    """Whether a metadata value counts as "present" for summary purposes —
    not None, not an empty string/list/dict. Mirrors `_is_empty_value` in
    `lore_block.py` but kept local: this module has no dependency on `ai/`."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    return True


def summary_field_keys(
    entry_type: EntryTypeDefinition | None,
    schema: MetadataSchema,
    metadata: Mapping[str, Any],
) -> list[str]:
    """The field keys that make up `entry_type`'s summary, in display order.

    A non-empty `summary_fields` nomination wins outright: its keys, in
    nomination order, keeping only the ones that are still real fields in
    `schema.fields` (an unknown/stale key is skipped silently rather than
    erroring — this is a display fallback, not a validator).

    With no nomination, the fallback is the first `_FALLBACK_COUNT` keys of
    the type's (effective, inheritance-resolved) `fields`, in schema order,
    whose field type is in `SUMMARY_SCALAR_TYPES` and whose value in
    `metadata` is present.
    """
    if entry_type is None:
        return []
    nominated = entry_type.summary_fields
    if nominated:
        return [key for key in nominated if key in schema.fields]
    keys: list[str] = []
    for field_id in entry_type.fields:
        if len(keys) >= _FALLBACK_COUNT:
            break
        field = schema.fields.get(field_id)
        if field is None or field.type not in SUMMARY_SCALAR_TYPES:
            continue
        # The identity triple (title/id/entry_type) lives on the node, not in
        # metadata, and a field the type hides is hidden here too — neither is
        # a summary of anything.
        if field.intrinsic or _effective_hidden(entry_type, field, field_id):
            continue
        if not _value_present(metadata.get(field_id)):
            continue
        keys.append(field_id)
    return keys


def _effective_hidden(entry_type: EntryTypeDefinition, field: Any, field_id: str) -> bool:
    """A field's effective hidden flag for this type: the type's override wins
    (true OR false) over the field def's default — the rule
    `effectiveFieldHidden` applies on the frontend."""
    override = entry_type.field_overrides.get(field_id)
    override_hidden = getattr(override, "hidden", None) if override is not None else None
    if isinstance(override_hidden, bool):
        return override_hidden
    return bool(getattr(field, "hidden", False))


def _effective_label(entry_type: EntryTypeDefinition, schema: MetadataSchema, field_id: str) -> str:
    """A field's effective label for this type: the type's field override
    label if set, else the field's own `name`."""
    override = entry_type.field_overrides.get(field_id)
    if override is not None and override.label:
        return override.label
    field = schema.fields.get(field_id)
    return field.name if field is not None else field_id


def _render_value(
    schema: MetadataSchema,
    field_id: str,
    value: Any,
    resolve_title: Callable[[str], str | None] | None,
) -> str:
    """Render one present metadata value to display text: select/multi_select
    map through their option labels, booleans to Yes/No, an `entity_ref`/
    `entity_ref_list` through `resolve_title` (falling back to the raw id(s)
    when no resolver is given — the module stays I/O-free by default), other
    lists join by ", ", everything else stringifies."""
    field = schema.fields.get(field_id)
    field_type = field.type if field is not None else ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field_type in ("select", "multi_select") and field is not None and field.options:
        labels = {opt.value: (opt.label or opt.value) for opt in field.options}
        if isinstance(value, list):
            return ", ".join(labels.get(item, str(item)) for item in value)
        return labels.get(value, str(value))
    if field_type == "entity_ref":
        rid = str(value)
        return (resolve_title(rid) if resolve_title else None) or rid
    if field_type == "entity_ref_list":
        items = value if isinstance(value, list) else [value]
        return ", ".join(((resolve_title(str(item)) if resolve_title else None) or str(item)) for item in items)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def summary_values(
    entry_type: EntryTypeDefinition | None,
    schema: MetadataSchema,
    metadata: Mapping[str, Any],
    resolve_title: Callable[[str], str | None] | None = None,
) -> list[tuple[str, str, str]]:
    """`(key, effective label, rendered text)` for each key `summary_field_keys`
    resolves, skipping any whose value in `metadata` is absent.

    `resolve_title`, when given, names the target of a nominated
    `entity_ref`/`entity_ref_list` field (id → title, or `None` if it can't be
    read) — injected rather than read directly, so this module stays pure.
    With no resolver, a ref renders its raw id(s), same as before this hook
    existed."""
    results: list[tuple[str, str, str]] = []
    for field_id in summary_field_keys(entry_type, schema, metadata):
        value = metadata.get(field_id)
        if not _value_present(value):
            continue
        label = _effective_label(entry_type, schema, field_id)
        results.append((field_id, label, _render_value(schema, field_id, value, resolve_title)))
    return results
