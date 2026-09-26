"""A group-MEMBER field's rename/delete/option-migration reach (#2239).

`mutation_row_rewrite.py` (ADR-0095 §9) extends a top-level field's rename /
delete / option migration into mutation-set and override rows, and covers a
reference-keyed LIST field's own id inside a member-path row
(`old_list_id.<target>.<member>` → `new_list_id.<target>.<member>`). It never
reached the case where the field being renamed/deleted/option-migrated is
itself a MEMBER of a group some list field uses as its item shape (ADR-0089
§1): the member's key inside every stored item, and the member half of a
member-path row / an encoded `add` item's value, kept the old id.

A group's members live in `schema.groups[group_id].members`, entirely apart
from `schema.fields` (:func:`groups_with_member` is how a rename/delete call
finds which groups declare a given field id as a member — read BEFORE the
change, same discipline `rewrite_field_across_set_and_override_rows` uses for
`keyed_lists_from`). Renaming or deleting the KEY member (the list's
`entity_ref`, ADR-0089 §1) is treated exactly like any other member here: the
key member's id is part of the group, not part of a member-path token, so it
needs the identical item-key / member-key rewrite everywhere it appears.

Pure helpers operate on plain dicts/lists (no I/O, no `ProjectService`
dependency), mirroring `mutation_row_rewrite.py`'s split; the `apply_*`
orchestrators take `root`, `read`/`write`, and the entry paths to walk, so
`schema.py` / `schema_groups.py` stay thin call sites.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.schema import GroupMember, MetadataSchema
from app.services.project.lore_mutation_items import (
    KeyedList,
    decode_item,
    encode_item,
    keyed_lists_from,
    member_path,
    split_member_path,
)
from app.services.project.mutation_row_rewrite import apply_row_rewrite_to_files

# ---------------------------------------------------------------------------
# Schema-shape lookups
# ---------------------------------------------------------------------------


def groups_with_member(schema: MetadataSchema, member_key: str) -> dict[str, GroupMember]:
    """Every group in `schema.groups` that declares `member_key` as a member,
    by group id — the answer `rename_metadata_field` / `delete_metadata_field`
    need to treat a field id as a group member too, not only a `schema.fields`
    entry. Read BEFORE the rename/delete, so this is still keyed by the field's
    pre-change id."""
    found: dict[str, GroupMember] = {}
    for group_id, group in schema.groups.items():
        for member in group.members:
            if member.key == member_key:
                found[group_id] = member
                break
    return found


def list_fields_using_group(schema: MetadataSchema, group_id: str) -> list[str]:
    """Every `list` field whose item shape is `group_id` (ADR-0089's nested
    consumption mode) — the fan-out from a group-member change to the list(s)
    it shapes."""
    return [
        field_id
        for field_id, field in schema.fields.items()
        if field.type == "list" and field.item_group == group_id
    ]


def rewrite_group_member_key_in_layer(
    layer_data: dict[str, Any], group_id: str, old_member: str, new_member: str | None
) -> bool:
    """The group's OWN declaration in one layer's raw YAML dict: rename
    (`new_member` set) or drop (`new_member=None`) the member entry keyed
    `old_member`. Returns whether anything changed.

    Carries the group's `identity` (ADR-0096 §1) along with its member: when
    `old_member` was the declared identity, a rename renames `identity` with
    it and a drop clears it — the same reach a rename/delete already gives
    every other member key."""
    groups = layer_data.get("groups")
    if not isinstance(groups, dict):
        return False
    group_data = groups.get(group_id)
    if not isinstance(group_data, dict):
        return False
    members = group_data.get("members")
    if not isinstance(members, list):
        return False
    changed = False
    new_members: list[Any] = []
    for member in members:
        if isinstance(member, dict) and member.get("key") == old_member:
            changed = True
            if new_member is None:
                continue
            member = {**member, "key": new_member}
        new_members.append(member)
    if changed:
        group_data["members"] = new_members
        if group_data.get("identity") == old_member:
            if new_member is None:
                group_data.pop("identity", None)
            else:
                group_data["identity"] = new_member
        groups[group_id] = group_data
        layer_data["groups"] = groups
    return changed


# ---------------------------------------------------------------------------
# Member key rename/delete: stored items
# ---------------------------------------------------------------------------


def rewrite_member_key_in_item(item: Any, old_member: str, new_member: str | None) -> tuple[Any, bool]:
    """One stored item dict with `old_member`'s key renamed (`new_member` set)
    or dropped (`new_member=None`). Non-dicts and items without the key pass
    through unchanged."""
    if not isinstance(item, dict) or old_member not in item:
        return item, False
    item = dict(item)
    value = item.pop(old_member)
    if new_member is not None:
        item[new_member] = value
    return item, True


def rewrite_member_key_in_items(items: Any, old_member: str, new_member: str | None) -> tuple[Any, bool]:
    if not isinstance(items, list):
        return items, False
    changed = False
    out: list[Any] = []
    for item in items:
        new_item, item_changed = rewrite_member_key_in_item(item, old_member, new_member)
        changed = changed or item_changed
        out.append(new_item)
    return out, changed


def apply_member_key_rewrite_to_entries(
    list_field_id: str,
    old_member: str,
    new_member: str | None,
    entry_paths: Iterable[Path],
    read: Callable[[Path], tuple[dict[str, Any], str]],
    write: Callable[[Path, dict[str, Any], str], None],
) -> None:
    """Every stored item of `list_field_id`, across `entry_paths`, with member
    `old_member` renamed/dropped (keeps item order)."""
    for path in entry_paths:
        front_matter, body = read(path)
        metadata = front_matter.get("metadata")
        if not isinstance(metadata, dict) or list_field_id not in metadata:
            continue
        new_items, changed = rewrite_member_key_in_items(metadata[list_field_id], old_member, new_member)
        if not changed:
            continue
        metadata[list_field_id] = new_items
        front_matter["metadata"] = metadata
        write(path, front_matter, body)


# ---------------------------------------------------------------------------
# Member key rename/delete: mutation-set / override rows
# ---------------------------------------------------------------------------


def _rewrite_member_row_field(
    row: dict[str, Any],
    list_field_id: str,
    old_member: str,
    new_member: str | None,
    keyed: dict[str, KeyedList],
) -> tuple[dict[str, Any] | None, bool]:
    """One row's rename/drop for a MEMBER key (not the list field's own id): a
    member-path row `list_field_id.<target>.old_member`, or an `add` row on
    `list_field_id` whose JSON value is an encoded item carrying `old_member`."""
    field = row.get("field")
    if not isinstance(field, str):
        return row, False
    if field == list_field_id and row.get("op") == "add" and isinstance(row.get("value"), str):
        item = decode_item(row["value"])
        if item is None or old_member not in item:
            return row, False
        new_item, changed = rewrite_member_key_in_item(item, old_member, new_member)
        return ({**row, "value": encode_item(new_item)} if changed else row), changed
    split = split_member_path(field, keyed) if keyed else None
    if split is None:
        return row, False
    matched_list, key, member = split
    if matched_list.field_id != list_field_id or member != old_member:
        return row, False
    if new_member is None:
        return None, True
    return {**row, "field": member_path(list_field_id, key, new_member)}, True


def rewrite_member_key_in_rows(
    rows: list[Any],
    list_field_id: str,
    old_member: str,
    new_member: str | None,
    keyed: dict[str, KeyedList],
) -> tuple[list[Any], bool]:
    changed = False
    out: list[Any] = []
    scoped_keyed = {list_field_id: keyed[list_field_id]} if list_field_id in keyed else {}
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        new_row, row_changed = _rewrite_member_row_field(row, list_field_id, old_member, new_member, scoped_keyed)
        changed = changed or row_changed
        if new_row is not None:
            out.append(new_row)
    return out, changed


def rewrite_member_key_across_set_and_override_rows(
    root: Path,
    list_field_id: str,
    old_member: str,
    new_member: str | None,
    schema: MetadataSchema,
    read: Callable[[Path], tuple[dict[str, Any], str]],
    write: Callable[[Path, dict[str, Any], str], None],
) -> None:
    """`schema` must be read BEFORE the member rename/delete, so a keyed-list
    member-path row is still matched against the member's pre-change id."""
    keyed = keyed_lists_from(schema)
    apply_row_rewrite_to_files(
        root,
        lambda rows: rewrite_member_key_in_rows(rows, list_field_id, old_member, new_member, keyed),
        read,
        write,
    )


def apply_member_rename_or_delete(
    root: Path,
    schema: MetadataSchema,
    old_member: str,
    new_member: str | None,
    group_ids: Iterable[str],
    entry_paths: Iterable[Path],
    read: Callable[[Path], tuple[dict[str, Any], str]],
    write: Callable[[Path, dict[str, Any], str], None],
) -> None:
    """Every list field shaped by one of `group_ids` (read from `schema`,
    BEFORE the change): stored items and mutation-set/override rows, member
    `old_member` renamed to `new_member` or dropped (`new_member=None`)."""
    entry_paths = list(entry_paths)
    list_field_ids: set[str] = set()
    for group_id in group_ids:
        list_field_ids.update(list_fields_using_group(schema, group_id))
    for list_field_id in list_field_ids:
        apply_member_key_rewrite_to_entries(list_field_id, old_member, new_member, entry_paths, read, write)
        rewrite_member_key_across_set_and_override_rows(
            root, list_field_id, old_member, new_member, schema, read, write
        )


# ---------------------------------------------------------------------------
# Member option rename/delete
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemberOptionChange:
    """One member's option rename/delete (ADR-0095 §9's top-level shape,
    scoped to a group member): `rename` is the explicit old->new map, `valid`
    the member's current option-value set, `is_collection` whether the member
    is a multi-valued type (only reachable through L2-flattening — a nested
    item_group member is never `multi_select` — but this stays general)."""

    rename: dict[str, str]
    valid: set[str]
    is_collection: bool


def _clean_member_value(value: Any, change: MemberOptionChange) -> Any:
    """Mirrors `ProjectService._clean_option_value` for one member's value: a
    collection member de-duplicates; a scalar member clears to `""` when
    invalid."""
    if change.is_collection:
        if not isinstance(value, list):
            return value
        out: list[Any] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                out.append(item)
                continue
            mapped = change.rename.get(item, item)
            if mapped not in change.valid or mapped in seen:
                continue
            seen.add(mapped)
            out.append(mapped)
        return out
    if isinstance(value, str):
        mapped = change.rename.get(value, value)
        return mapped if mapped in change.valid else ""
    return value


def rewrite_member_option_values_in_items(
    items: Any, member_key: str, change: MemberOptionChange
) -> tuple[Any, bool]:
    if not isinstance(items, list):
        return items, False
    changed = False
    out: list[Any] = []
    for item in items:
        if isinstance(item, dict) and member_key in item:
            old_value = item[member_key]
            new_value = _clean_member_value(old_value, change)
            if new_value != old_value:
                item = {**item, member_key: new_value}
                changed = True
        out.append(item)
    return out, changed


def apply_member_option_rewrite_to_entries(
    list_field_id: str,
    member_key: str,
    change: MemberOptionChange,
    entry_paths: Iterable[Path],
    read: Callable[[Path], tuple[dict[str, Any], str]],
    write: Callable[[Path, dict[str, Any], str], None],
) -> None:
    for path in entry_paths:
        front_matter, body = read(path)
        metadata = front_matter.get("metadata")
        if not isinstance(metadata, dict) or list_field_id not in metadata:
            continue
        new_items, changed = rewrite_member_option_values_in_items(metadata[list_field_id], member_key, change)
        if not changed:
            continue
        metadata[list_field_id] = new_items
        front_matter["metadata"] = metadata
        write(path, front_matter, body)


def _rewrite_member_option_row(
    row: dict[str, Any],
    list_field_id: str,
    member_key: str,
    change: MemberOptionChange,
    keyed: dict[str, KeyedList],
) -> tuple[dict[str, Any] | None, bool]:
    field = row.get("field")
    if not isinstance(field, str):
        return row, False
    if field == list_field_id and row.get("op") == "add" and isinstance(row.get("value"), str):
        item = decode_item(row["value"])
        if item is None or member_key not in item:
            return row, False
        old_value = item[member_key]
        new_value = _clean_member_value(old_value, change)
        if new_value == old_value:
            return row, False
        new_item = {**item, member_key: new_value}
        return {**row, "value": encode_item(new_item)}, True
    split = split_member_path(field, keyed) if keyed else None
    if split is None:
        return row, False
    matched_list, _key, member = split
    # A member-path record is only ever `replace` (ADR-0089 §1's grammar table);
    # add/remove address the whole item, handled by the `add`-row branch above.
    if matched_list.field_id != list_field_id or member != member_key or row.get("op") != "replace":
        return row, False
    value = row.get("value")
    if not isinstance(value, str):
        return row, False
    new_value = _clean_member_value(value, change)
    if new_value == value:
        return row, False
    return {**row, "value": new_value}, True


def rewrite_member_option_values_in_rows(
    rows: list[Any],
    list_field_id: str,
    member_key: str,
    change: MemberOptionChange,
    keyed: dict[str, KeyedList],
) -> tuple[list[Any], bool]:
    changed = False
    out: list[Any] = []
    scoped_keyed = {list_field_id: keyed[list_field_id]} if list_field_id in keyed else {}
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        new_row, row_changed = _rewrite_member_option_row(row, list_field_id, member_key, change, scoped_keyed)
        changed = changed or row_changed
        if new_row is not None:
            out.append(new_row)
    return out, changed


def apply_member_option_migration(
    root: Path,
    schema: MetadataSchema,
    group_id: str,
    member_key: str,
    change: MemberOptionChange,
    entry_paths: Iterable[Path],
    read: Callable[[Path], tuple[dict[str, Any], str]],
    write: Callable[[Path, dict[str, Any], str], None],
) -> None:
    """Every list field shaped by `group_id`: an option rename/delete on its
    member `member_key` applied to stored item values and the matching rows
    (member-path `replace` + encoded `add` items), mirroring
    `_apply_option_value_changes`'s top-level reach (ADR-0095 §9)."""
    entry_paths = list(entry_paths)
    keyed = keyed_lists_from(schema)
    for list_field_id in list_fields_using_group(schema, group_id):
        apply_member_option_rewrite_to_entries(list_field_id, member_key, change, entry_paths, read, write)
        apply_row_rewrite_to_files(
            root,
            lambda rows, lf=list_field_id: rewrite_member_option_values_in_rows(rows, lf, member_key, change, keyed),
            read,
            write,
        )
