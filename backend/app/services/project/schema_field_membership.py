"""A field's entry-type MEMBERSHIP, apart from its DEFINITION (#2276, #2277).

A field is defined in one schema layer (`fields.<id>`), but an entry type lists
it (`entry_types.<type>.fields`) in whichever layer declares or overlays that
type — often a lower one: a series defines `truth`, the book's own character
type lists it. A write that removes or renames the definition must therefore
rewrite the listing in every layer that can see it, not just the defining one.

These helpers edit one layer's raw YAML data in place, across ALL its entry
types.
"""

from __future__ import annotations

from typing import Any


def _field_lists(layer_data: dict[str, Any]) -> list[tuple[dict[str, Any], list[Any]]]:
    entry_types = layer_data.get("entry_types")
    if not isinstance(entry_types, dict):
        return []
    return [
        (entry_type_data, entry_type_data["fields"])
        for entry_type_data in entry_types.values()
        if isinstance(entry_type_data, dict) and isinstance(entry_type_data.get("fields"), list)
    ]


def strip_field_membership(layer_data: dict[str, Any], field_id: str) -> None:
    """Drop `field_id` from every entry type's `fields` in this layer."""
    for entry_type_data, fields_list in _field_lists(layer_data):
        if field_id in fields_list:
            entry_type_data["fields"] = [candidate for candidate in fields_list if candidate != field_id]


def rename_field_membership(layer_data: dict[str, Any], old_field_id: str, new_field_id: str) -> None:
    """Replace `old_field_id` with `new_field_id` in every entry type's
    `fields` in this layer, keeping order and never listing a field twice."""
    for entry_type_data, fields_list in _field_lists(layer_data):
        if old_field_id not in fields_list:
            continue
        replaced: list[Any] = []
        for candidate in fields_list:
            next_field_id = new_field_id if candidate == old_field_id else candidate
            if next_field_id not in replaced:
                replaced.append(next_field_id)
        entry_type_data["fields"] = replaced
