"""Resolve a model's follow-up entry names to lore entries (ADR-0099 §4).

The extraction turn may name OTHER lore entries the conversation said should
change, by the name the conversation used. This module turns each name into an
entry id — exactly one lore entry whose title or alias matches, or the item is
dropped and counted. A follow-up is advice for the author to keep as a TODO, so
a name that can't be pinned to one entry is never guessed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import FollowUp
from app.services.ai.name_matcher import normalise_name

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


def lore_names(project: ProjectService) -> tuple[dict[str, set[str]], dict[str, str]]:
    """The lore roster's names: entry ids by normalised title/alias
    (``list_lore_entries`` — the same names the ADR-0091 mention scan uses), and
    each entry's title by id (the id when it has none). Shared by follow-ups and
    the flag extraction's note entries (ADR-0100)."""
    ids_by_name: dict[str, set[str]] = {}
    titles: dict[str, str] = {}
    for entry in project.list_lore_entries().entries:
        titles[entry.id] = entry.title or entry.id
        names = [entry.title] if entry.title else []
        aliases = entry.metadata.get("aliases")
        if isinstance(aliases, list):
            names.extend(str(alias) for alias in aliases if alias)
        for name in names:
            key = normalise_name(name)
            if key:  # a separator-only name ("-") names nothing (#2567)
                ids_by_name.setdefault(key, set()).add(entry.id)
    return ids_by_name, titles


def resolve_follow_ups(
    project: ProjectService, raw: list[dict[str, str]], committed_id: str | None
) -> tuple[list[FollowUp], int]:
    """``raw`` (parsed ``{"entry", "change", "why"}`` items) resolved against the
    lore roster's titles and aliases (`lore_names`), case- and
    whitespace-insensitively. Returns the
    resolved follow-ups and how many items were dropped: no match, a name two
    entries share, the committed entry itself, or a repeat of (entry, change)."""
    if not raw:
        return [], 0
    ids_by_name, titles = lore_names(project)
    resolved: list[FollowUp] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for item in raw:
        matches = ids_by_name.get(normalise_name(item["entry"]), set())
        if len(matches) != 1:
            dropped += 1
            continue
        entry_id = next(iter(matches))
        key = (entry_id, item["change"])
        if entry_id == committed_id or key in seen:
            dropped += 1
            continue
        seen.add(key)
        resolved.append(
            FollowUp(
                entry_id=entry_id,
                entry_name=titles[entry_id],
                change=item["change"],
                why=item["why"],
            )
        )
    return resolved, dropped
