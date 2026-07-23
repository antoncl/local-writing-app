"""When two field values are the same *as a reader sees them*.

Extracted from `snapshot_diff.py` when the drift report needed the identical
rule (#439). Its own module rather than an import between the two, because the
diff route now composes the drift report and the dependency would be a cycle.

One rule, one place: the compare view and the drift report must agree on what
counts as a change, or the same edit reports differently in two panes of one
gesture.
"""

from __future__ import annotations

from typing import Any


def same_rendered_value(was: Any, now: Any) -> bool:
    """Whether two field values are the same *as the rail renders them*.

    A missing key and an empty one are the same absence to a reader — the row
    reads "(none)" either way — so reporting a flip between them shows the
    author two identical-looking values and no way to reconcile them. They
    arrive different for ordinary reasons: healing a reference to a deleted node
    blanks it to `""` rather than removing it, and a scene saved before a field
    existed simply has no key.

    `0` and `False` are values, not absences, so the check is explicit about
    the empty containers rather than leaning on truthiness.
    """
    empty = (None, "", [], {})
    was_blank = any(was is candidate or was == candidate for candidate in empty)
    now_blank = any(now is candidate or now == candidate for candidate in empty)
    if was_blank or now_blank:
        return was_blank and now_blank
    return bool(was == now)


def display_value(value: Any) -> str:
    """One field value as a reader sees it.

    Here so that a *name* the report prints and a *value* it prints are produced
    by the same rule. The snapshot witness records an entity's title by reading
    it back out of the resolved state, and the intrinsic `title` can be retyped
    to a collection — at which point `str(value)` yields a Python repr
    (`"['Tom', 'Thomas']"`) and the report renders that as the entity's name.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(display_value(item) for item in value if item not in (None, ""))
    return str(value)
