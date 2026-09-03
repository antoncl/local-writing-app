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

# The metadata field types that hold a reference to another node or a tag vocab
# entry — the values this traversal exists to find. `tags` rides along (slice 3
# consumes it for canonicalise/rename); ref-only passes filter by `field.type`.
REF_FIELD_TYPES = ("entity_ref", "entity_ref_list", "tags")

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


def _ref_members(field: MetadataFieldDefinition) -> dict[str, MetadataFieldDefinition] | None:
    """The ref/tag members of a ``list``-of-``item_group`` field, keyed by member
    key, or ``None`` if the field is not a group-shaped list carrying any.

    ``item_scalar`` (the ``item_type`` sugar) stores flat scalars, not member
    maps, and its catalog excludes ref types today (ADR-0081 admits refs through
    named ``item_group`` members) — so those lists carry no occurrences here.
    """
    if field.type != "list" or field.item_scalar:
        return None
    members = field.item_members or []
    ref_members = {m.key: member_as_field(m) for m in members if m.type in REF_FIELD_TYPES}
    return ref_members or None


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
        ref_members = _ref_members(field)
        if ref_members is None or not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            for member_key, member_field in ref_members.items():
                if member_key in item:
                    yield RefOccurrence(field_id, member_key, member_field, item[member_key])


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
        ref_members = _ref_members(field)
        if ref_members is not None and isinstance(value, list):
            changed |= _rewrite_list_members(cleaned, field_id, value, ref_members, transform)
    return cleaned, changed


def _rewrite_list_members(
    cleaned: dict[str, Any],
    field_id: str,
    value: list[Any],
    ref_members: dict[str, MetadataFieldDefinition],
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
        for member_key, member_field in ref_members.items():
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
