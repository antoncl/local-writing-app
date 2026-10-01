"""Story time: a card's rank in the order things happen (ADR-0097 §5).

A `plot:card` carries `story_rank` — a number in a top-level front-matter key,
outside `metadata`, kept the way ADR-0094 keeps `parent` / `rank`: the backend
owns it (a card save carries the on-disk value forward, `place` is the only
writer), and it is not content, so the save revision ignores it
(`content_without_placement`). The ordering rules are placement's — ascending,
ties by id, a missing rank last, a new rank between its neighbours — so this
module only adds the key, a line-edit writer, and the story-time order across
layers. The service half is `CardStoryTimeMixin`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

import yaml

from app.services.project.placement import (
    Sibling,
    _front_matter_span,
    parse_rank,
    rank_sort_key,
    rank_to_yaml,
)
from app.services.yaml_io import load_yaml

STORY_RANK_KEY = "story_rank"

_STORY_RANK_LINE = re.compile(r"^story_rank[ \t]*:")


def story_rank_extra(front_matter: dict[str, object]) -> dict[str, object]:
    """The `extra=` for a typed writer that re-dumps a card's front matter: the
    on-disk `story_rank`, raw, so a save never moves a card in story time and
    never takes a rank from a client."""
    value = front_matter.get(STORY_RANK_KEY)
    return {STORY_RANK_KEY: value} if parse_rank(value) is not None else {}


def story_rank_value(rank: Decimal | float) -> int | float:
    """A rank as written to front matter: an int when integral, so 1.0 never
    drifts into the file where 1 was."""
    return rank_to_yaml(rank if isinstance(rank, Decimal) else Decimal(repr(rank)))


def set_story_rank_in_text(text: str, rank: Decimal | float | None) -> str:
    """`text` with its `story_rank:` line replaced (removed for None) — every
    other byte kept.

    The line goes at the end of the front-matter block, where a typed save's
    re-dump puts it, in the file's own line ending. `text` must be the file
    decoded as-is (no newline translation); the caller writes bytes back. A
    file with no front-matter block is returned unchanged — a card always has
    one."""
    lines = text.splitlines(keepends=True)
    close = _front_matter_span(lines)
    if close is None:
        return text
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    block = [line for line in lines[1:close] if not _STORY_RANK_LINE.match(line)]
    if rank is not None:
        block.append(yaml.safe_dump({STORY_RANK_KEY: story_rank_value(rank)}).strip() + newline)
    return "".join([lines[0], *block, *lines[close:]])


def next_story_rank(own_ranks: Sequence[float | None]) -> Decimal:
    """The rank for a card added at the end of the layer's story time: one past
    the highest own rank, or 1 when no card is ranked yet."""
    ranked = [rank for rank in own_ranks if rank is not None]
    if not ranked:
        return Decimal(1)
    return Decimal(repr(max(ranked))) + 1


def own_story_group(own: Sequence[Sibling]) -> list[Sibling]:
    """The open layer's cards in story time — the group `plan_placement` works
    on."""
    return sorted(own, key=lambda card: rank_sort_key(card.id, card.rank))


def story_time_order(own: Sequence[Sibling], inherited: Sequence[tuple[Sibling, int]]) -> list[str]:
    """Every card id in story time: the open layer's own cards by
    `rank_sort_key`, then the inherited ones after, nearest layer first, each
    layer by `rank_sort_key` (ADR-0097 §5, *Layers*). `inherited` pairs a card
    with its layer's rank, a higher number being the nearer layer
    (`_layer_rank_map`)."""
    ordered = [card.id for card in own_story_group(own)]
    for layer_rank in sorted({layer_rank for _, layer_rank in inherited}, reverse=True):
        layer = [card for card, rank in inherited if rank == layer_rank]
        ordered.extend(card.id for card in own_story_group(layer))
    return ordered


def drop_card_scene_in_text(text: str) -> tuple[str, str | None]:
    """`text` with its card's `metadata.scene` removed, and the scene id it held.

    For a snapshot restore whose scene another card now holds (ADR-0097 §1).
    Re-dumps the front-matter block — a rare path, and the line to drop sits
    inside a nested mapping — keeping the body bytes. `(text, None)` when the
    block holds no scene."""
    lines = text.splitlines(keepends=True)
    close = _front_matter_span(lines)
    if close is None:
        return text, None
    try:
        data = load_yaml("".join(lines[1:close]))
    except yaml.YAMLError:
        return text, None
    metadata = data.get("metadata") if isinstance(data, dict) else None
    scene = metadata.get("scene") if isinstance(metadata, dict) else None
    if not isinstance(scene, str) or not scene:
        return text, None
    del metadata["scene"]
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip().replace("\n", newline)
    return "".join([lines[0], dumped + newline, *lines[close:]]), scene


def front_matter_in_text(text: str) -> dict[str, object]:
    """The front-matter mapping of file text, `{}` when it has none or it is not
    a mapping."""
    lines = text.splitlines(keepends=True)
    close = _front_matter_span(lines)
    if close is None:
        return {}
    try:
        data = load_yaml("".join(lines[1:close]))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}
