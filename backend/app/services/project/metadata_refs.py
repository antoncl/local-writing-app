"""One traversal over a node's metadata that finds every reference/tag value,
at any depth the schema permits (ADR-0081).

This is the single definition of *where references live* in a node's metadata: a
top-level ``entity_ref`` / ``entity_ref_list`` / ``tags`` field, or such a member
inside a ``list``-of-``item_group`` value. Every reference-lifecycle pass —
index/backlinks, delete-purge, read-side dangling-strip, title resolution —
consumes this instead of re-deriving its own ``metadata.items()`` walk, which is
exactly why they all used to stop at the top level (six re-derivations that each
independently forgot to descend). Define "at any depth" once, here, and no pass
can forget it.

Two forms, per ADR-0081 §1:

- :func:`iter_ref_occurrences` — **read**: yield each occurrence's value + the
  field (or member-as-field, carrying ``picker_config``) it lives under. For
  indexing and title lookup.
- :func:`rewrite_ref_occurrences` — **rewrite-in-place**: return a copy with each
  occurrence mapped by a transform, copy-on-write so a nested container is cloned
  only when a change actually lands in it (a read-path heal that changes nothing
  stays cheap). For delete-purge and dangling-strip.

:func:`occurrence_targets` turns one occurrence into the node ids it names (one
for ``entity_ref``, each item for ``entity_ref_list``), so the index's edge walk
and the AI structural hop (#2066, ADR-0089 §8) read a value the same way.

:func:`keyed_list_key` is the shape predicate of ADR-0089 §1 — a group-shaped
list whose item group has exactly one ``entity_ref`` member is keyed by that
member, one item per target — and :func:`dedupe_keyed_lists` is the collapse
the merge sweep applies when two items' targets merge onto one id (first wins).
Both live here so the save, the resolver, the sweep and the validator agree on
which member is the key.

Groups do not nest in groups (a ``GroupMember`` is a scalar/ref/tag field, never
another list/group), so the descent is exactly one level — bounded, not
open-ended.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from app.models.schema import GroupMember, MetadataFieldDefinition, MetadataSchema

# The metadata field types that hold a reference to another node — the values
# this traversal exists to find. `tags` retired (ADR-0082 slice 2b): a tag
# vocabulary is now an `entity_ref_list` field like any other, so it already
# rides through this same set — no separate type to carry along.
REF_FIELD_TYPES = ("entity_ref", "entity_ref_list")

# Sentinel: a transform returns this to leave an occurrence untouched (distinct
# from returning a new value that happens to equal the old one).
UNCHANGED: Any = object()


@dataclass(frozen=True)
class RefOccurrence:
    """One reference/tag value found in a node's metadata.

    ``field`` is the field the value lives under — for a group member it is the
    member viewed as a plain field (:func:`member_as_field`), so it carries the
    member's ``type`` and ``picker_config`` and the per-ref validators/matchers
    apply verbatim. ``member_key`` is ``None`` for a top-level field.
    """

    field_id: str
    member_key: str | None
    field: MetadataFieldDefinition
    value: Any


def member_as_field(member: GroupMember) -> MetadataFieldDefinition:
    """A group member viewed as a plain field definition, so the per-ref picker
    match / validators apply to a nested member exactly as to a top-level field."""
    return MetadataFieldDefinition(
        name=member.name or member.key,
        type=member.type,
        options=member.options,
        picker_config=member.picker_config,
    )


def ref_members(field: MetadataFieldDefinition) -> dict[str, MetadataFieldDefinition] | None:
    """The ref/tag members of a ``list``-of-``item_group`` field, keyed by member
    key, or ``None`` if the field is not a group-shaped list carrying any.

    Public so the *adjacency* passes (AI-context wrapping, lore-block rendering,
    promotion partition — ADR-0081 §4) share this one definition of *which
    members of a field are references* instead of each re-deriving the descent.

    ``item_scalar`` (the ``item_type`` sugar) stores flat scalars, not member
    maps, and its catalog excludes ref types today (ADR-0081 admits refs through
    named ``item_group`` members) — so those lists carry no occurrences here.
    """
    if field.type != "list" or field.item_scalar:
        return None
    members = field.item_members or []
    found = {m.key: member_as_field(m) for m in members if m.type in REF_FIELD_TYPES}
    return found or None


def keyed_list_key(field: MetadataFieldDefinition | None) -> str | None:
    """The key member of a reference-keyed list (ADR-0089 §1): a group-shaped
    ``list`` whose item group has exactly one ``entity_ref`` member. ``None``
    for every other field, including a group with two reference members (no
    member is *the* key) or with only an ``entity_ref_list`` member (a list
    cannot key an item)."""
    if field is None:
        return None
    members = ref_members(field)
    if members is None:
        return None
    keys = [key for key, member in members.items() if member.type == "entity_ref"]
    return keys[0] if len(keys) == 1 else None


def duplicate_item_keys(items: Any, key_member: str) -> list[str]:
    """The keys a reference-keyed list holds more than once, in first-seen
    order. Items without a key are not counted."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items if isinstance(items, list) else []:
        key = item.get(key_member) if isinstance(item, dict) else None
        if not isinstance(key, str) or not key:
            continue
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return duplicates


def dedupe_keyed_items(items: list[Any], key_member: str) -> list[Any]:
    """``items`` with every later item for an already-seen key dropped — the
    first wins. Items without a key pass through."""
    seen: set[str] = set()
    kept: list[Any] = []
    for item in items:
        key = item.get(key_member) if isinstance(item, dict) else None
        if isinstance(key, str) and key:
            if key in seen:
                continue
            seen.add(key)
        kept.append(item)
    return kept


def dedupe_keyed_lists(metadata: dict[str, Any], schema: MetadataSchema) -> bool:
    """Collapse duplicate keys in every reference-keyed list of ``metadata``,
    in place, first wins (ADR-0089 §1's merge rule). Returns whether anything
    changed. Applied after a reference rewrite, never on a plain read: two
    items that already share a key on disk are tolerated and reported by
    project validation, not silently dropped."""
    changed = False
    for field_id, value in list(metadata.items()):
        key_member = keyed_list_key(schema.fields.get(field_id))
        if key_member is None or not isinstance(value, list):
            continue
        deduped = dedupe_keyed_items(value, key_member)
        if len(deduped) != len(value):
            metadata[field_id] = deduped
            changed = True
    return changed


def iter_ref_occurrences(
    metadata: dict[str, Any], schema: MetadataSchema
) -> Iterator[RefOccurrence]:
    """Yield every reference/tag occurrence in ``metadata`` — top-level fields and
    ``item_group`` members alike. Read-only; the values are not copied."""
    for field_id, value in metadata.items():
        field = schema.fields.get(field_id)
        if field is None:
            continue
        if field.type in REF_FIELD_TYPES:
            yield RefOccurrence(field_id, None, field, value)
            continue
        members = ref_members(field)
        if members is None or not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            for member_key, member_field in members.items():
                if member_key in item:
                    yield RefOccurrence(field_id, member_key, member_field, item[member_key])


def occurrence_targets(occ: RefOccurrence) -> list[Any]:
    """The candidate target(s) one ref occurrence names — the single value for
    ``entity_ref``, each item for ``entity_ref_list``, nothing otherwise. Values
    are returned as stored: the caller decides what counts as an id."""
    if occ.field.type == "entity_ref":
        return [occ.value]
    if occ.field.type == "entity_ref_list" and isinstance(occ.value, list):
        return list(occ.value)
    return []


def rewrite_ref_occurrences(
    metadata: dict[str, Any],
    schema: MetadataSchema,
    transform: Callable[[RefOccurrence], Any],
) -> tuple[dict[str, Any], bool]:
    """Return a copy of ``metadata`` with each ref/tag occurrence replaced by
    ``transform(occurrence)`` (or left as-is when it returns :data:`UNCHANGED` or
    an equal value), plus whether anything changed.

    Copy-on-write: the top level is shallow-copied and a ``list`` value is deep-
    copied only the first time a change lands inside it, so an unchanged read-path
    heal never clones a nested container.
    """
    cleaned = dict(metadata)
    changed = False
    for field_id, value in metadata.items():
        field = schema.fields.get(field_id)
        if field is None:
            continue
        if field.type in REF_FIELD_TYPES:
            new_value = transform(RefOccurrence(field_id, None, field, value))
            if new_value is not UNCHANGED and new_value != value:
                cleaned[field_id] = new_value
                changed = True
            continue
        members = ref_members(field)
        if members is not None and isinstance(value, list):
            changed |= _rewrite_list_members(cleaned, field_id, value, members, transform)
    return cleaned, changed


def _rewrite_list_members(
    cleaned: dict[str, Any],
    field_id: str,
    value: list[Any],
    members: dict[str, MetadataFieldDefinition],
    transform: Callable[[RefOccurrence], Any],
) -> bool:
    """Rewrite the ref/tag members inside a ``list``-of-``item_group`` value.

    Copy-on-write: ``cleaned[field_id]`` is replaced by a deep copy of ``value``
    on the first change and mutated thereafter, so an unchanged list is never
    cloned. Returns whether anything changed.
    """
    changed = False
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        for member_key, member_field in members.items():
            if member_key not in item:
                continue
            old = item[member_key]
            new_value = transform(RefOccurrence(field_id, member_key, member_field, old))
            if new_value is UNCHANGED or new_value == old:
                continue
            if not changed:  # first change → take our private deep copy
                cleaned[field_id] = copy.deepcopy(value)
                changed = True
            cleaned[field_id][index][member_key] = new_value
    return changed
