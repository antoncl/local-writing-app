"""Line edits (#2460): a revise prompt answers with a list of small reasoned
edits `{find, replace, reason}` instead of a replacement passage.

The route asks the provider for `LINE_EDITS_RESPONSE_SCHEMA` (honored where the
profile supports constrained output, ignored elsewhere), then reads the reply
back with the same tolerant JSON repair the entry-patch extraction uses.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.models.ai import LineEdit
from app.services.ai.entry_patch import load_json_object
from app.services.ai.providers import StreamDelta, StreamDone, StreamEvent

LINE_EDITS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["find", "replace", "reason"],
            },
        }
    },
    "required": ["edits"],
}

LINE_EDITS_TRUNCATED_ERROR = (
    "The reply was cut off before the edit list finished — select less text "
    "or raise the output limit."
)
LINE_EDITS_UNREADABLE_ERROR = "The model's reply wasn't a readable edit list."


def parse_line_edits(raw: str) -> list[LineEdit] | None:
    """The edits in ``raw``, or ``None`` when it isn't a readable edit list
    (no JSON object, or no ``edits`` array). An empty list is a valid answer
    ("nothing to change"). Unusable items are skipped rather than failing the
    list: not an object, a non-string/empty ``find``, a non-string ``replace``,
    or an edit that changes nothing."""
    obj = load_json_object(raw)
    items = obj.get("edits") if obj is not None else None
    if not isinstance(items, list):
        return None
    return edit_items(items)


def edit_items(items: list) -> list[LineEdit]:
    """The usable edits among ``items`` (the item rules of `parse_line_edits`)."""
    edits: list[LineEdit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        find, replace, reason = item.get("find"), item.get("replace"), item.get("reason", "")
        if not isinstance(find, str) or not find or not isinstance(replace, str):
            continue
        if find == replace:
            continue
        edits.append(LineEdit(find=find, replace=replace, reason=reason if isinstance(reason, str) else ""))
    return edits


def read_line_edits_reply(content: str, *, truncated: bool) -> tuple[list[LineEdit] | None, str | None]:
    """`(edits, error)` for a finished reply: a cut-off reply is never trusted
    (a repaired half-list would silently drop edits), then the parse."""
    if truncated:
        return None, LINE_EDITS_TRUNCATED_ERROR
    edits = parse_line_edits(content)
    if edits is None:
        return None, LINE_EDITS_UNREADABLE_ERROR
    return edits, None


class LineEditsStreamCollector:
    """Line edits over the streaming route (#2464): the edit list is read whole,
    but riding the stream lets a client disconnect close the provider call (the
    non-streaming route runs the sync provider call on a worker thread that
    nothing can cancel).

    `tap` passes the provider events through while accumulating the text;
    `on_done` is the stream transform's finaliser hook and returns the fields
    merged onto the terminal `done` line: `edits`, plus `ok: false` + `error`
    when the reply is unusable - the same rules as the non-streaming route.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []

    def tap(self, events: Iterator[StreamEvent]) -> Iterator[StreamEvent]:
        for ev in events:
            if isinstance(ev, StreamDelta):
                self._parts.append(ev.text)
            yield ev

    def on_done(self, ev: StreamDone, _usage: object, _cost: object) -> dict[str, Any]:
        edits, error = read_line_edits_reply("".join(self._parts), truncated=ev.truncated)
        done: dict[str, Any] = {"edits": [e.model_dump() for e in edits] if edits is not None else None}
        if error is not None:
            done.update(ok=False, error=error)
        return done
