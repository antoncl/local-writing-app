"""Lore check notes (#2490, ADR-0098): a check prompt answers with a list of
notes `{quote, problem, entry}` - places where the passage contradicts a lore
entry - instead of a replacement passage. Sibling of `line_edits.py`.

The route asks the provider for `NOTES_RESPONSE_SCHEMA` (honored where the
profile supports constrained output, ignored elsewhere), then reads the reply
back with the same tolerant JSON repair the entry-patch extraction uses. A note
naming an entry the run never sent is dropped and counted: the model can only
cite lore it was shown.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree

from app.models.ai import LineNote
from app.services.ai.entry_patch import load_json_object
from app.services.ai.providers import StreamDelta, StreamDone, StreamEvent

if TYPE_CHECKING:
    from app.services.ai.templates import RenderedTemplate

NOTES_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "problem": {"type": "string"},
                    "entry": {"type": "string"},
                },
                "required": ["quote", "problem", "entry"],
            },
        }
    },
    "required": ["notes"],
}

LINE_NOTES_TRUNCATED_ERROR = (
    "The reply was cut off before the notes finished — select less text "
    "or raise the output limit."
)
LINE_NOTES_UNREADABLE_ERROR = "The model's reply wasn't a readable list of notes."


def note_items(items: list, *, entry_required: bool) -> list[LineNote]:
    """The usable notes among ``items``: skipped when not an object, or a
    non-string/empty ``quote``, ``problem`` or (when ``entry_required``)
    ``entry``. Without ``entry_required`` an absent or non-string ``entry``
    reads as ``""`` (ADR-0100)."""
    notes: list[LineNote] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        quote, problem, entry = item.get("quote"), item.get("problem"), item.get("entry")
        if not entry_required and not isinstance(entry, str):
            entry = ""
        required = (quote, problem, entry) if entry_required else (quote, problem)
        if not all(isinstance(v, str) and v for v in required):
            continue
        notes.append(LineNote(quote=quote, problem=problem, entry=entry))
    return notes


def _read_notes(raw: str, *, entry_required: bool = True) -> tuple[list[LineNote], int] | None:
    """`(notes, skipped)` read from ``raw``, or ``None`` when it isn't a readable
    note list (no JSON object, or no ``notes`` array). Unusable items are skipped
    and counted rather than failing the list (see `note_items`)."""
    obj = load_json_object(raw)
    items = obj.get("notes") if obj is not None else None
    if not isinstance(items, list):
        return None
    notes = note_items(items, entry_required=entry_required)
    return notes, len(items) - len(notes)


def parse_line_notes(raw: str) -> list[LineNote] | None:
    """The notes in ``raw``, or ``None`` when it isn't a readable note list. An
    empty list is a valid answer ("nothing contradicts the lore")."""
    read = _read_notes(raw)
    return read[0] if read is not None else None


def read_line_notes_reply(
    content: str, *, truncated: bool, sent_ids: set[str]
) -> tuple[list[LineNote] | None, int, str | None]:
    """`(notes, dropped, error)` for a finished reply: a cut-off reply is never
    trusted, then the parse. `dropped` counts malformed items plus notes whose
    `entry` is not an id the run sent."""
    if truncated:
        return None, 0, LINE_NOTES_TRUNCATED_ERROR
    read = _read_notes(content)
    if read is None:
        return None, 0, LINE_NOTES_UNREADABLE_ERROR
    parsed, skipped = read
    kept = [n for n in parsed if n.entry in sent_ids]
    return kept, skipped + len(parsed) - len(kept), None


_OPENING_TAG = re.compile(r"<[^\s/>]+(\s[^>]*?)/?>")


def _block_name(xml: str) -> str | None:
    """The `name` attribute of a lore block's opening tag - the entry's name as
    the model was shown it (as of the scene, after mutations), not its stored
    title."""
    match = _OPENING_TAG.match(xml.lstrip())
    if match is None:
        return None
    try:
        name = ElementTree.fromstring(f"<x{match.group(1)}/>").get("name")
    except ElementTree.ParseError:
        return None
    return name or None


def checked_against(rendered: RenderedTemplate) -> list[dict[str, str]]:
    """Every lore entry the run sent - stable then volatile tier, in send order,
    de-duplicated - as `{"id", "name"}`, the name read from the entry's rendered
    lore block (the id when it has none)."""
    blocks = {**rendered.send_lore_volatile_entries, **rendered.send_lore_stable_entries}
    ids = list(dict.fromkeys([*rendered.send_lore_stable_ids, *rendered.send_lore_volatile_ids]))
    return [{"id": i, "name": _block_name(blocks.get(i, "")) or i} for i in ids]


class LineNotesStreamCollector:
    """Lore check notes over the streaming route: the note list is read whole,
    but riding the stream lets a client disconnect close the provider call.

    `tap` passes the provider events through while accumulating the text;
    `on_done` is the stream transform's finaliser hook and returns the fields
    merged onto the terminal `done` line: `notes`, `notes_dropped`,
    `checked_against`, plus `ok: false` + `error` when the reply is unusable.
    """

    def __init__(self, sent_ids: set[str], checked: list[dict[str, str]]) -> None:
        self._parts: list[str] = []
        self._sent_ids = sent_ids
        self._checked = checked

    def tap(self, events: Iterator[StreamEvent]) -> Iterator[StreamEvent]:
        for ev in events:
            if isinstance(ev, StreamDelta):
                self._parts.append(ev.text)
            yield ev

    def on_done(self, ev: StreamDone, _usage: object, _cost: object) -> dict[str, Any]:
        notes, dropped, error = read_line_notes_reply(
            "".join(self._parts), truncated=ev.truncated, sent_ids=self._sent_ids
        )
        done: dict[str, Any] = {
            "notes": [n.model_dump() for n in notes] if notes is not None else None,
            "notes_dropped": dropped,
            "checked_against": self._checked,
        }
        if error is not None:
            done.update(ok=False, error=error)
        return done
