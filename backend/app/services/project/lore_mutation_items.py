"""Relationship items follow the mutation rules (ADR-0089 §1–§3).

A group-shaped ``list`` field whose item group has exactly one ``entity_ref``
member is a **reference-keyed list**: that member is the item's key, and a list
holds one item per target. Its items are mutated with the ordinary marker
grammar (ADR-0001) in three record shapes, every value url-encoded as any
marker value is:

=====================  ==================================  =======  =====================================
writer's intent        ``field=`` token                    ``op=``  ``value=`` (url-decoded)
=====================  ==================================  =======  =====================================
an item starts here    the list field                      add      the whole item, a JSON object
a member changes       ``<field>.<target id>.<member>``    replace  the member's value
an item ends here      the list field                      remove   the target id
=====================  ==================================  =======  =====================================

Presence is **positional per key** (the amendment to ADR-0009): among the
records live at a position, the latest-started ``add`` or ``remove`` for a key
decides whether the item exists there, and an ``add`` resets the key's member
records — a ``replace`` started before it does not apply to the new item.
Member records resolve as scalar fields do (latest-started live ``replace``
wins). A whole-list ``replace`` is not a record of this class: the resolver
ignores it and project validation warns, because the grammar's default op on a
list would silently erase every item (a reset is a set of removes). The
folded value of the list field is its items — member paths never leave the
resolver (``effective_state``'s widened contract, ADR-0089 §3).

The shape predicate (:func:`~app.services.project.metadata_refs.keyed_list_key`)
lives with the one reference traversal so every pass agrees on which member is
the key; this module holds the record grammar and the fold.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.models.schema import MetadataFieldDefinition
from app.services.project.metadata_refs import keyed_list_key, member_as_field

# Member types for which an empty record value IS a value (a cleared text);
# for every other type an empty value unsets the member, since "" is not a
# number, a boolean, an option or a reference.
_TEXT_MEMBER_TYPES = frozenset({"text", "long_text"})


class MutationRecord(Protocol):
    """What a record offers the grammar and the fold — a scene marker
    (`MutationMarker`) and an override row (`MutationSetRow`) alike, which is
    what makes ADR-0089 §5's "one record grammar for markers and overrides"
    literal: the same classification and the same fold read both."""

    op: str
    value: str


@dataclass(frozen=True)
class KeyedList:
    """One reference-keyed list field: its id, the key member's key, and every
    member viewed as a plain field (for value validation and coercion)."""

    field_id: str
    key_member: str
    member_fields: dict[str, MetadataFieldDefinition]


def keyed_lists_from(schema: Any) -> dict[str, KeyedList]:
    """Every reference-keyed list the schema declares, by field id."""
    out: dict[str, KeyedList] = {}
    for field_id, field in (getattr(schema, "fields", None) or {}).items():
        key_member = keyed_list_key(field)
        if key_member is None:
            continue
        members = {member.key: member_as_field(member) for member in (field.item_members or [])}
        out[field_id] = KeyedList(field_id=field_id, key_member=key_member, member_fields=members)
    return out


def member_path(field_id: str, key: str, member: str) -> str:
    """The ``field=`` token of a member record."""
    return f"{field_id}.{key}.{member}"


def split_member_path(token: str, keyed: Mapping[str, KeyedList]) -> tuple[KeyedList, str, str] | None:
    """Parse a member record's token into ``(list, target id, member key)``, or
    ``None`` when it does not address a reference-keyed list. The list's id is
    matched as the longest declared prefix; ids and member keys carry no dots,
    so the remainder splits at its last dot."""
    for field_id in sorted(keyed, key=len, reverse=True):
        prefix = field_id + "."
        if not token.startswith(prefix):
            continue
        key, dot, member = token[len(prefix) :].rpartition(".")
        if not dot or not key or not member:
            return None
        return keyed[field_id], key, member
    return None


def encode_item(item: Mapping[str, Any]) -> str:
    """An item as an ``add`` record's value (before url-encoding): a compact,
    key-sorted JSON object, so equal items encode identically."""
    return json.dumps(dict(item), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def decode_item(value: str) -> dict[str, Any] | None:
    """The item an ``add`` record carries, or ``None`` when the value is not a
    JSON object."""
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def item_key(item: Any, key_member: str) -> str | None:
    """An item's key — the key member's value when it is a non-empty string.
    An item without one (a purged target, ADR-0089 §9) has no key and no
    record can address it."""
    if not isinstance(item, dict):
        return None
    key = item.get(key_member)
    return key if isinstance(key, str) and key else None


@dataclass(frozen=True)
class ItemRecord:
    """One live record addressing a reference-keyed list, classified: the key
    it addresses (``None`` when undecodable or a whole-list replace), the
    member for a member record, and the decoded item for an ``add``."""

    marker: MutationRecord
    key: str | None = None
    member: str | None = None
    item: dict[str, Any] | None = None


def list_record(keyed: KeyedList, marker: MutationRecord) -> ItemRecord:
    """Classify a record whose token is the list field itself."""
    if marker.op == "add":
        item = decode_item(marker.value)
        return ItemRecord(marker, key=item_key(item, keyed.key_member), item=item)
    if marker.op == "remove":
        key = marker.value.strip()
        return ItemRecord(marker, key=key or None)
    return ItemRecord(marker)  # whole-list replace: ignored (§2)


def member_record(marker: MutationRecord, key: str, member: str) -> ItemRecord:
    """Classify a record whose token is a member path."""
    return ItemRecord(marker, key=key, member=member)


def fold_keyed_items(
    base_items: Any,
    keyed: KeyedList,
    records: list[ItemRecord],
    coerce: Callable[[str, str], Any],
    canonical: Callable[[str], str] = lambda key: key,
) -> list[Any]:
    """The items a reference-keyed list holds at a position: the base items with
    the live ``records`` applied in start order.

    ``records`` must be the records live at the position, sorted by start.
    Keys are matched through ``canonical`` (the node index's ``canonical_id``),
    so a record written against an id later merged away still finds its item.
    Base duplicates of a key are tolerated: the first wins. A base item with no
    key (or that is not a map) passes through untouched. ``coerce`` turns a
    member record's string value into the member type's native value.
    """
    slots = _base_slots(base_items, keyed, canonical)
    for record in records:
        if record.key is not None:
            _apply_item_record(slots, keyed, record, coerce, canonical(record.key))
    return list(slots.values())


def _base_slots(base_items: Any, keyed: KeyedList, canonical: Callable[[str], str]) -> dict[str, Any]:
    """The base items by (canonical) key, first wins, copied so the fold can
    edit them; an item without a key gets a slot no record can address."""
    slots: dict[str, Any] = {}
    for index, item in enumerate(base_items if isinstance(base_items, list) else []):
        key = item_key(item, keyed.key_member)
        if key is None:
            slots[f"\x00{index}"] = dict(item) if isinstance(item, dict) else item
            continue
        key = canonical(key)
        if key in slots:
            continue
        copied = dict(item)
        copied[keyed.key_member] = key
        slots[key] = copied
    return slots


def _apply_item_record(
    slots: dict[str, Any], keyed: KeyedList, record: ItemRecord, coerce: Callable[[str, str], Any], key: str
) -> None:
    """One live record onto the slots: an `add` (re)places the item for its key
    — an existing key keeps its place, a new one appends — a `remove` drops it,
    a member `replace` edits the item present at this point. Anything else
    (a whole-list replace, an op on a member path) is ineffective."""
    op = record.marker.op
    if op == "add" and record.member is None and record.item is not None:
        item = dict(record.item)
        item[keyed.key_member] = key
        slots[key] = item
    elif op == "remove" and record.member is None:
        slots.pop(key, None)
    elif op == "replace" and record.member is not None:
        _replace_member(slots.get(key), keyed, record, coerce)


def _replace_member(item: Any, keyed: KeyedList, record: ItemRecord, coerce: Callable[[str, str], Any]) -> None:
    member_field = keyed.member_fields.get(record.member or "")
    if item is None or member_field is None or record.member == keyed.key_member:
        return  # ineffective: no item at this position, or not a member
    if record.marker.value == "" and member_field.type not in _TEXT_MEMBER_TYPES:
        item.pop(record.member, None)
    else:
        item[record.member] = coerce(record.marker.value, member_field.type)
