"""What a card shows as its title and synopsis (ADR-0097 §3).

One reader, so the board projection and the AI's plot context cannot disagree:
a written card shows its scene's title and summary; a card with no scene shows
its own title and body. The card node itself is unchanged — `read_card` and
`CardEntry` still carry the card's own text.
"""

from __future__ import annotations

from collections.abc import Mapping


def displayed_card_text(
    card_title: str,
    card_body: str,
    scene_id: str | None,
    scene_text: Mapping[str, tuple[str, str]],
) -> tuple[str, str]:
    """`(title, synopsis)` for one card. `scene_text` maps each scene id to its
    `(title, summary)`. A scene with an empty summary shows an empty synopsis —
    never the card's own body, which is the plan from before it was written."""
    if scene_id and scene_id in scene_text:
        return scene_text[scene_id]
    return card_title, card_body
