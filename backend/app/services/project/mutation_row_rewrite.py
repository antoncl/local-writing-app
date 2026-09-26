"""Row-level rewrites for mutation sets and overrides when the schema changes
(ADR-0095 §9).

A field rename, a field delete and an option rename/delete already rewrite
the `metadata` of every scene and lore file (`_rename_entry_metadata_key` /
`_remove_entry_metadata_key` / `_apply_option_value_changes`, `schema.py`)
over `_entry_markdown_paths` (`project_service.py:245`). A mutation-set row
and an override row (`MutationSetRow`, ADR-0089 §5's shared row shape) name a
field the same way and were never reached — this module is that reach, kept
out of `schema.py` (already near the file-size guard) as its own small,
schema-independent helper: it operates on raw front-matter `rows:` lists, not
parsed models, so it has no `ProjectService` dependency and no I/O of its own.

Both `mutation-sets/*.md` and `overrides/*.md` files store `rows:` as plain
front-matter (no prose body) via `_write_mutation_set_file` /
`_write_override_file`; rewriting the list in place and writing the front
matter straight back (the caller's `read`/`write`, i.e.
`_read_markdown_with_front_matter` / `_write_markdown_with_front_matter`)
keeps every file's shape exactly as it is, per ADR-0095 §9.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.services.project.lore_mutation_items import (
    KeyedList,
    member_path,
    split_member_path,
)
from app.services.project.lore_mutations import (
    COLLECTION_FIELD_TYPES,
    _split_collection_value,
)
from app.services.project.overrides import OVERRIDES_FOLDER

MUTATION_SETS_FOLDER = "mutation-sets"


def set_and_override_paths(root: Path) -> list[Path]:
    """Every mutation-set and override file in `root`'s own layer — the same
    reach `_rename_entry_metadata_key` has into scene/lore files, since the
    rename/delete callers only ever pass their own project's `root`."""
    return [
        *(root / MUTATION_SETS_FOLDER).glob("*.md"),
        *(root / OVERRIDES_FOLDER).glob("*.md"),
    ]


def _rewrite_row_field(
    row: dict[str, Any], old_field_id: str, new_field_id: str | None, keyed: dict[str, KeyedList]
) -> tuple[dict[str, Any] | None, bool]:
    """One row's rename/drop: `(new_row, changed)`; `new_row=None` means the
    row is dropped. Matches a plain `field == old_field_id` row and a
    keyed-list member-path row `old_field_id.<target>.<member>` the same way
    `split_member_path` reads a marker's token."""
    field = row.get("field")
    if not isinstance(field, str):
        return row, False
    if field == old_field_id:
        return (None if new_field_id is None else {**row, "field": new_field_id}), True
    split = split_member_path(field, keyed) if keyed else None
    if split is None:
        return row, False
    _, key, member = split
    if new_field_id is None:
        return None, True
    return {**row, "field": member_path(new_field_id, key, member)}, True


def rewrite_field_in_rows(
    rows: list[Any], old_field_id: str, new_field_id: str | None, keyed_lists: dict[str, KeyedList]
) -> tuple[list[Any], bool]:
    """Rename (`new_field_id` set) or drop (`new_field_id=None`) every row of
    `rows` naming `old_field_id`, plain or as a keyed-list member path.
    `keyed_lists` is `keyed_lists_from(schema)` read BEFORE the rename/delete
    (so it is still keyed by `old_field_id`, mirroring the schema state a
    member-path row on disk was written against)."""
    changed = False
    out: list[Any] = []
    scoped_keyed = {old_field_id: keyed_lists[old_field_id]} if old_field_id in keyed_lists else {}
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        new_row, row_changed = _rewrite_row_field(row, old_field_id, new_field_id, scoped_keyed)
        changed = changed or row_changed
        if new_row is not None:
            out.append(new_row)
    return out, changed


def _rewrite_option_row_value(
    op: str, value: str, *, is_collection: bool, rename: dict[str, str], valid: set[str]
) -> str | None:
    """One row's new `value`, or `None` to drop the row (an add/remove naming
    a removed option). A `replace` never drops — it clears (select) or narrows
    (multi_select's comma-joined members) instead, mirroring
    `_clean_option_value`."""
    if is_collection and op in ("add", "remove"):
        mapped = rename.get(value, value)
        return mapped if mapped in valid else None
    if is_collection and op == "replace":
        return ",".join(
            mapped
            for member in _split_collection_value(value)
            if (mapped := rename.get(member, member)) in valid
        )
    if not is_collection and op == "replace":
        mapped = rename.get(value, value)
        return mapped if mapped in valid else ""
    return value


def rewrite_option_values_in_rows(
    rows: list[Any], field_id: str, field_type: str, rename: dict[str, str], valid: set[str]
) -> tuple[list[Any], bool]:
    """Apply an option rename/delete to every row naming `field_id`, mirroring
    `_clean_option_value`'s rewrite of a stored metadata value:
    - a `replace` row on a non-collection field (a `select`) rewrites its
      value, or clears it to `""` when the option was removed;
    - an `add`/`remove` row on a collection field (`multi_select`) rewrites
      its single member, or the row is dropped when the option was removed;
    - a `replace` row on a collection field rewrites each comma-joined
      member, dropping any that is no longer valid.
    `rename` is the explicit old→new map; `valid` is the field's current
    option-value set.
    """
    changed = False
    out: list[Any] = []
    is_collection = field_type in COLLECTION_FIELD_TYPES
    for row in rows:
        field, value, op = (row.get("field"), row.get("value"), row.get("op")) if isinstance(row, dict) else (None, None, None)
        if field != field_id or not isinstance(value, str):
            out.append(row)
            continue
        new_value = _rewrite_option_row_value(op, value, is_collection=is_collection, rename=rename, valid=valid)
        if new_value is None:
            changed = True  # option removed: the add/remove row is dropped
            continue
        if new_value == value:
            out.append(row)
        else:
            out.append({**row, "value": new_value})
            changed = True
    return out, changed


def apply_row_rewrite_to_files(
    root: Path,
    rewrite: Callable[[list[Any]], tuple[list[Any], bool]],
    read: Callable[[Path], tuple[dict[str, Any], str]],
    write: Callable[[Path, dict[str, Any], str], None],
) -> None:
    """Walk every mutation-set and override file, apply `rewrite` to its
    `rows:` list, and write back only the files that changed. `read`/`write`
    are the front-matter round trip (`_read_markdown_with_front_matter` /
    `_write_markdown_with_front_matter`), passed in so this stays a pure
    helper with no `ProjectService` dependency."""
    for path in set_and_override_paths(root):
        front_matter, body = read(path)
        rows = front_matter.get("rows")
        if not isinstance(rows, list):
            continue
        new_rows, changed = rewrite(rows)
        if not changed:
            continue
        front_matter["rows"] = new_rows
        write(path, front_matter, body)


def rewrite_field_across_set_and_override_rows(
    root: Path,
    old_field_id: str,
    new_field_id: str | None,
    schema: Any,
    read: Callable[[Path], tuple[dict[str, Any], str]],
    write: Callable[[Path, dict[str, Any], str], None],
) -> None:
    """`schema.py`'s `rename_metadata_field` (`new_field_id` set) /
    `delete_metadata_field` (`new_field_id=None`) call this to extend
    `_rename_entry_metadata_key` / `_remove_entry_metadata_key`'s reach into
    every mutation-set and override row naming the field (ADR-0095 §9).
    `schema` must be read BEFORE the rename/delete, so a keyed-list
    member-path row is still matched against the field's pre-change id."""
    from app.services.project.lore_mutation_items import keyed_lists_from

    keyed_lists = keyed_lists_from(schema)
    apply_row_rewrite_to_files(
        root, lambda rows: rewrite_field_in_rows(rows, old_field_id, new_field_id, keyed_lists), read, write
    )
