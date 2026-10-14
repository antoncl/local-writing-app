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

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from app.models.ai import LineNote
from app.services.ai.entry_patch import load_json_object
from app.services.ai.helpers import _attr_or_item, _safe_read_node
from app.services.ai.providers import StreamDelta, StreamDone, StreamEvent

if TYPE_CHECKING:
    from app.services.ai.templates import RenderedTemplate
    from app.services.project_service import ProjectService

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


def parse_line_notes(raw: str) -> list[LineNote] | None:
    """The notes in ``raw``, or ``None`` when it isn't a readable note list (no
    JSON object, or no ``notes`` array). An empty list is a valid answer
    ("nothing contradicts the lore"). Unusable items are skipped rather than
    failing the list: not an object, or a non-string/empty ``quote``,
    ``problem`` or ``entry``."""
    obj = load_json_object(raw)
    items = obj.get("notes") if obj is not None else None
    if not isinstance(items, list):
        return None
    notes: list[LineNote] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        quote, problem, entry = item.get("quote"), item.get("problem"), item.get("entry")
        if not all(isinstance(v, str) and v for v in (quote, problem, entry)):
            continue
        notes.append(LineNote(quote=quote, problem=problem, entry=entry))
    return notes


def _count_items(raw: str) -> int:
    obj = load_json_object(raw)
    items = obj.get("notes") if obj is not None else None
    return len(items) if isinstance(items, list) else 0


def read_line_notes_reply(
    content: str, *, truncated: bool, sent_ids: set[str]
) -> tuple[list[LineNote] | None, int, str | None]:
    """`(notes, dropped, error)` for a finished reply: a cut-off reply is never
    trusted, then the parse. `dropped` counts malformed items plus notes whose
    `entry` is not an id the run sent."""
    if truncated:
        return None, 0, LINE_NOTES_TRUNCATED_ERROR
    parsed = parse_line_notes(content)
    if parsed is None:
        return None, 0, LINE_NOTES_UNREADABLE_ERROR
    kept = [n for n in parsed if n.entry in sent_ids]
    return kept, _count_items(content) - len(kept), None


def checked_against(project: ProjectService, rendered: RenderedTemplate) -> list[dict[str, str]]:
    """Every lore entry the run sent - stable then volatile tier, in send order,
    de-duplicated - as `{"id", "name"}`, the name being the entry's title (what
    the lore block's `name=` attribute carries; the id when it has none)."""
    ids = list(dict.fromkeys([*rendered.send_lore_stable_ids, *rendered.send_lore_volatile_ids]))
    out: list[dict[str, str]] = []
    for entry_id in ids:
        entry = _safe_read_node(project, entry_id)
        title = _attr_or_item(entry, "title") if entry is not None else None
        out.append({"id": entry_id, "name": title if isinstance(title, str) and title else entry_id})
    return out


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
