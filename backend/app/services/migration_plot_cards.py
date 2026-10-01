"""Migration v15: one card per scene, story time, and the seeded summary (ADR-0097 §10).

Until v15 a scene could be realized by several cards and a card carried no place
in story time. From v15 a scene has at most one card, every card has a
`story_rank` (a top-level front-matter key, outside `metadata`), and a written
card's synopsis is its scene's `summary`. This step runs once per layer of the
declared chain (a `ChainMigration`) over that layer's own `plot/` and `scenes/`:

1. **One card per scene.** For a scene held by more than one card, the card whose
   id sorts first keeps it; the others lose `scene` (and a stored
   `page_status: on_page`, which only a scene derives), so they read as unwritten.
   Nothing is deleted and every body stays.
2. **Seed the summary.** For each written card whose scene's `summary` is empty
   and whose body is not, the scene's `summary` becomes the body (stripped). Where
   both are non-empty, both stay.
3. **Seed story time**, last. `story_rank` 1..n: written cards in manuscript
   reading order (the v12 `parent` / `rank` on the scene files, a pre-order walk
   with ascending rank, ties by id), then the rest by `(title.lower(), id)` —
   today's board order. Done only when no card has a rank yet, so a re-run changes
   nothing.

Written against the v14 format and nothing else (ADR-0071): it reads the files
directly and does not call into the live services. A card is a `plot/*.md` whose
`entry_type` is exactly `plot:card`; a writer's own sub-type is not detected, so
it gets no rank and sorts last by the missing-rank rule. Every other byte of a
file stays as it was; only the front-matter block of a file whose own keys
change is re-dumped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.services.atomic_io import atomic_write_bytes
from app.services.project.placement import parse_rank, rank_sort_key
from app.services.yaml_io import load_yaml

if TYPE_CHECKING:
    from app.services.migrations import ChainContext

_CARD_ENTRY_TYPE = "plot:card"


@dataclass
class _Doc:
    """One markdown file: its lines, the closing `---` line, and the parsed
    front-matter block. `changed` marks a block that must be written back."""

    path: Path
    lines: list[str]
    close: int
    front_matter: dict[str, Any]
    changed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        value = self.front_matter.get("id")
        return value.strip() if isinstance(value, str) and value.strip() else self.path.stem

    @property
    def title(self) -> str:
        return str(self.front_matter.get("title") or self.id)

    @property
    def body(self) -> str:
        return "".join(self.lines[self.close + 1 :]).strip()

    def scene(self) -> str | None:
        value = self.metadata.get("scene")
        return value if isinstance(value, str) and value else None


def migrate_layer_plot_cards(root: Path, _ctx: ChainContext) -> None:
    cards = [doc for doc in _read_folder(root / "plot") if doc.front_matter.get("entry_type") == _CARD_ENTRY_TYPE]
    if not cards:
        return
    scenes = {doc.id: doc for doc in _read_folder(root / "scenes")}
    _one_card_per_scene(cards)
    _seed_summaries(cards, scenes)
    for card in cards:
        _write_back(card)
    for scene in scenes.values():
        _write_back(scene)
    if not any("story_rank" in card.front_matter for card in cards):
        _seed_story_rank(cards, scenes)


# ---- reading ----------------------------------------------------------------


def _read_folder(folder: Path) -> list[_Doc]:
    docs: list[_Doc] = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        lines = text.removeprefix("﻿").splitlines(keepends=True)
        close = _closing_line(lines)
        if close is None:
            continue
        try:
            data = load_yaml("".join(lines[1:close]))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        metadata = data.get("metadata")
        docs.append(_Doc(path, lines, close, data, metadata=metadata if isinstance(metadata, dict) else {}))
    return docs


def _closing_line(lines: list[str]) -> int | None:
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            return index
    return None


# ---- the three steps --------------------------------------------------------


def _one_card_per_scene(cards: list[_Doc]) -> None:
    holders: dict[str, list[_Doc]] = {}
    for card in cards:
        scene = card.scene()
        if scene is not None:
            holders.setdefault(scene, []).append(card)
    for held in holders.values():
        for card in sorted(held, key=lambda doc: doc.id)[1:]:
            del card.metadata["scene"]
            # `on_page` is derived from the scene; with none it would read stale.
            if card.metadata.get("page_status") == "on_page":
                del card.metadata["page_status"]
            card.front_matter["metadata"] = card.metadata
            card.changed = True


def _seed_summaries(cards: list[_Doc], scenes: dict[str, _Doc]) -> None:
    for card in cards:
        scene = scenes.get(card.scene() or "")
        body = card.body
        if scene is None or not body or str(scene.metadata.get("summary") or "").strip():
            continue
        scene.metadata["summary"] = body
        scene.front_matter["metadata"] = scene.metadata
        scene.changed = True


def _seed_story_rank(cards: list[_Doc], scenes: dict[str, _Doc]) -> None:
    reading = {scene_id: position for position, scene_id in enumerate(_reading_order(scenes))}
    written = sorted((card for card in cards if card.scene() in reading), key=lambda card: reading[card.scene() or ""])
    rest = sorted((card for card in cards if card.scene() not in reading), key=lambda card: (card.title.lower(), card.id))
    for rank, card in enumerate([*written, *rest], start=1):
        _append_story_rank(card, rank)


def _reading_order(scenes: dict[str, _Doc]) -> list[str]:
    """Every scene file id in manuscript reading order: a pre-order walk of the
    `parent` / `rank` tree, siblings ascending by rank, ties by id. A node whose
    parent is not a file here sits at the top."""
    children: dict[str | None, list[tuple[tuple[bool, float, str], str]]] = {}
    for scene_id, doc in scenes.items():
        parent = doc.front_matter.get("parent")
        parent_id = parent.strip() if isinstance(parent, str) and parent.strip() in scenes else None
        key = rank_sort_key(scene_id, parse_rank(doc.front_matter.get("rank")))
        children.setdefault(parent_id, []).append((key, scene_id))
    order: list[str] = []
    seen: set[str] = set()

    def visit(parent_id: str | None) -> None:
        for _, scene_id in sorted(children.get(parent_id, [])):
            if scene_id not in seen:
                seen.add(scene_id)
                order.append(scene_id)
                visit(scene_id)

    visit(None)
    return order


# ---- writing ----------------------------------------------------------------


def _newline(doc: _Doc) -> str:
    return "\r\n" if doc.lines[0].endswith("\r\n") else "\n"


def _rewrite(doc: _Doc, lines: list[str]) -> None:
    atomic_write_bytes(doc.path, "".join(lines).encode("utf-8"))
    doc.lines = lines


def _write_back(doc: _Doc) -> None:
    """Re-dump `doc`'s front-matter block when it changed, keeping the closing
    line and every body byte as they were."""
    if not doc.changed:
        return
    newline = _newline(doc)
    dumped = yaml.safe_dump(doc.front_matter, sort_keys=False, allow_unicode=True).strip().replace("\n", newline)
    _rewrite(doc, [doc.lines[0], dumped + newline, *doc.lines[doc.close :]])
    doc.close = _closing_line(doc.lines) or doc.close
    doc.changed = False


def _append_story_rank(doc: _Doc, rank: int) -> None:
    """Add `story_rank: n` at the block's end — a line edit, so a card that is
    not otherwise changed keeps its bytes."""
    newline = _newline(doc)
    _rewrite(doc, [*doc.lines[: doc.close], f"story_rank: {rank}{newline}", *doc.lines[doc.close :]])
    doc.close += 1
    doc.front_matter["story_rank"] = rank
