"""Test helper for resolving built-in prompt ids by their stable human title."""

from __future__ import annotations


def builtin_prompt_id(service, title):
    """The minted id of the built-in prompt shown as `title` (built-in ids are
    now opaque uuids; tests refer to built-ins by their stable human title)."""
    for entry in service.list_prompt_entries().entries:
        if entry.title == title:
            return entry.id
    raise KeyError(f"no built-in prompt titled {title!r}")
