"""v16→v17: a roleplay beat is bracketed by two markers and its interiority rides
the close marker (ADR-0070 Amendment 1, decision 9).

Before: `<!-- character:id=X;internal=ENC -->text<!-- /character -->`, one span
per paragraph, each carrying a copy of the interiority. After:
`<!-- character:id=X -->text<!-- /character;internal=ENC -->`, one beat per
reply, the interiority stored once. A pure body transform, so it is a
`DocumentMigration` and a restored snapshot reaches it too (ADR-0071 §7).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from app.services.migrations import MigratableDocument

# One span in either generation of the format. The text stops at any other
# character marker, so a NEW-format beat (open without `;internal=`, close WITH
# it) never matches and a migrated body is left as it is.
_SPAN = re.compile(
    r"<!--\s*character:id=(?P<id>[A-Za-z0-9_-]+)(?:;internal=(?P<enc>\S*?))?\s*-->"
    r"(?P<text>(?:(?!<!--\s*/?character[:;\s-])[\s\S])*?)"
    r"<!--\s*/character\s*-->"
)


class _Beat(NamedTuple):
    char_id: str
    enc: str
    start: int
    end: int
    # Each merged span's text, with the original separator between neighbours.
    pieces: tuple[str, ...]
    originals: int


def _render(beat: _Beat, body: str) -> str:
    if beat.originals == 1 and not beat.enc:
        return body[beat.start : beat.end]  # already a new-format beat
    close = f"<!-- /character;internal={beat.enc} -->" if beat.enc else "<!-- /character -->"
    return f"<!-- character:id={beat.char_id} -->{''.join(beat.pieces)}{close}"


def bracket_beats(body: str) -> str:
    """`body` with every old-format beat span rewritten as a bracketed beat."""
    beats: list[_Beat] = []
    for match in _SPAN.finditer(body):
        char_id, enc = match.group("id"), match.group("enc") or ""
        text = match.group("text")
        if beats:
            last = beats[-1]
            sep = body[last.end : match.start()]
            if last.char_id == char_id and last.enc == enc and "\n" in sep and not sep.strip():
                beats[-1] = last._replace(
                    end=match.end(), pieces=(*last.pieces, sep, text), originals=last.originals + 1
                )
                continue
        beats.append(_Beat(char_id, enc, match.start(), match.end(), (text,), 1))
    out: list[str] = []
    cursor = 0
    for beat in beats:
        out.append(body[cursor : beat.start])
        out.append(_render(beat, body))
        cursor = beat.end
    out.append(body[cursor:])
    return "".join(out)


def beat_markers_bracket_a_beat(doc: MigratableDocument) -> MigratableDocument:
    """v16→v17: merge a reply's per-paragraph spans into one bracketed beat with
    its interiority on the close marker. Consecutive spans for the same character
    with identical interiority (absent == absent), separated only by whitespace
    holding a line break, become one beat; otherwise each span is its own beat. A
    no-op for a body without old-format spans, and idempotent: a bracketed beat
    carrying interiority is never matched again."""
    if "character:id=" not in doc.body:
        return doc
    body = bracket_beats(doc.body)
    if body == doc.body:
        return doc
    return type(doc)(doc.front_matter, body)
