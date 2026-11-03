"""Roleplay beat-marker validation (ADR-0070 Amendment 1, decision 8) — the
advisory pass `validate_project` runs over every manuscript scene body.

A beat is an open marker `<!-- character:id=X -->` and a close marker
`<!-- /character -->`; they pair in document order. A marker without its
partner attributes nothing (text is never silently reattributed), so each
orphan is reported here as a warning — never an error, as for mutation anchors.
"""

from __future__ import annotations

import re
from typing import Any

_BEAT_MARKER = re.compile(
    r"<!--\s*character:id=(?P<open>[A-Za-z0-9_-]+)\s*-->"
    r"|<!--\s*/character(?:;internal=\S*?)?\s*-->"
)


def orphan_beat_markers(body: str) -> tuple[list[str], int]:
    """`(character ids of open markers with no close, count of close markers
    with no open)` for a scene body. An open pairs with the next close, provided
    no other open marker comes first."""
    orphan_opens: list[str] = []
    orphan_closes = 0
    pending: str | None = None
    for match in _BEAT_MARKER.finditer(body):
        char_id = match.group("open")
        if char_id is not None:
            if pending is not None:
                orphan_opens.append(pending)
            pending = char_id
        elif pending is not None:
            pending = None
        else:
            orphan_closes += 1
    if pending is not None:
        orphan_opens.append(pending)
    return orphan_opens, orphan_closes


class BeatMarkerValidationMixin:
    """Composed onto `ProjectService`; reads scene files through its siblings."""

    def _validate_beat_markers(self, node_index: Any) -> list[str]:
        """One warning per orphan beat marker, across every manuscript scene."""
        by_id = getattr(node_index, "by_id", {})
        warnings: list[str] = []
        for entry in sorted((e for e in by_id.values() if e.kind == "manuscript"), key=lambda e: e.id):
            try:
                _, body = self._read_markdown_with_front_matter(entry.path)  # type: ignore[attr-defined]
            except OSError:
                continue
            opens, closes = orphan_beat_markers(body)
            name = entry.title or entry.id
            for char_id in opens:
                who = by_id.get(char_id)
                warnings.append(
                    f"Scene '{name}': a beat for {(who.title if who else '') or char_id} has no end marker."
                )
            warnings.extend(f"Scene '{name}': an end marker has no beat." for _ in range(closes))
        return warnings
