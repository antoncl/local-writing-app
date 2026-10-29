"""Where a node's metadata stores free text the writer typed (ADR-0085
Amendment 2) — the one definition search and replace share.

A **text slot** is a string value held verbatim in front matter under a field
the schema types as ``text`` / ``long_text``: a top-level field, one item of a
``list`` whose item shape is a text scalar (the ``item_type`` sugar), or a text
member of one ``list``-of-``item_group`` item. Its path is the key sequence that
reaches it — ``("summary",)``, ``("follow_ups", 2)``, ``("beats", 1, "note")``.

Everything else in metadata is not a slot: a reference stores an id (search
matches its *resolved title*, which is not stored text), a select/tag stores a
vocabulary value, and a group's identity member stores a minted id. Those stay
find-only; a slot is what replace may rewrite.

Groups do not nest in groups, so a path is at most three keys deep — the same
bounded descent `metadata_refs.py` makes for references.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from typing import Any

from app.models.schema import MetadataFieldDefinition, MetadataSchema

TEXT_FIELD_TYPES = ("text", "long_text")

MetadataPath = tuple[str | int, ...]


def iter_text_slots(metadata: dict[str, Any], schema: MetadataSchema) -> Iterator[tuple[MetadataPath, str]]:
    """Yield ``(path, value)`` for every text slot in ``metadata``, in field
    order then item order. Values that are not strings (a hand-edited file
    holding a number under a text field) are not slots."""
    for field_id, value in metadata.items():
        field = schema.fields.get(field_id)
        if field is None:
            continue
        if field.type in TEXT_FIELD_TYPES:
            if isinstance(value, str):
                yield (field_id,), value
        elif field.type == "list" and isinstance(value, list):
            yield from _list_text_slots(field_id, field, value)


def _list_text_slots(
    field_id: str, field: MetadataFieldDefinition, items: list[Any]
) -> Iterator[tuple[MetadataPath, str]]:
    members = field.item_members or []
    if field.item_scalar:
        if members and members[0].type in TEXT_FIELD_TYPES:
            for index, item in enumerate(items):
                if isinstance(item, str):
                    yield (field_id, index), item
        return
    text_keys = [m.key for m in members if m.type in TEXT_FIELD_TYPES and m.key != field.item_identity]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for key in text_keys:
            member_value = item.get(key)
            if isinstance(member_value, str):
                yield (field_id, index, key), member_value


def with_text_slots(metadata: dict[str, Any], values: Mapping[MetadataPath, str | None]) -> dict[str, Any]:
    """A deep copy of ``metadata`` with each slot path set to its new value.
    Every path must be one ``iter_text_slots`` yielded for this metadata."""
    updated = copy.deepcopy(metadata)
    for path, value in values.items():
        container: Any = updated
        for key in path[:-1]:
            container = container[key]
        container[path[-1]] = value
    return updated


def without_text_slots(metadata: dict[str, Any], schema: MetadataSchema) -> dict[str, Any]:
    """``metadata`` with every text slot blanked to ``None`` — what is left is
    the find-only remainder search still reports as plain metadata hits (the
    value iterator skips ``None`` at every depth)."""
    slots = {path: None for path, _ in iter_text_slots(metadata, schema)}
    return with_text_slots(metadata, slots) if slots else metadata


def slot_label(path: MetadataPath) -> str:
    """A slot's display label in a hit excerpt — ``summary``,
    ``follow_ups[2]``, ``beats[1].note`` — the bracket form search already
    uses for list items."""
    label = str(path[0])
    for key in path[1:]:
        label += f"[{key}]" if isinstance(key, int) else f".{key}"
    return label
