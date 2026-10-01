"""Cards in story time, and one card per scene (ADR-0097 §1, §4, §5) — the
service half of `story_time.py`.

Composed onto `ProjectService` beside `PlotMixin`, whose card CRUD calls the
checks and writers here. A card's `story_rank` is written by exactly three
things: `_create_plot_folder_node` / seed (a new card's rank, via `extra=`),
`place_card` (a line edit under the file lock), and nothing else — a card save
carries the on-disk value forward (`story_rank_extra`).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.models import CardEntry, CardSummary, PlaceCardRequest
from app.services.atomic_io import atomic_write_bytes
from app.services.migrations import MigratableDocument
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndexEntry
from app.services.project.placement import (
    Sibling,
    file_lock,
    note_placement_write,
    parse_rank,
    plan_placement,
)
from app.services.project.story_time import (
    STORY_RANK_KEY,
    drop_card_scene_in_text,
    front_matter_in_text,
    next_story_rank,
    own_story_group,
    set_story_rank_in_text,
    story_rank_value,
)

logger = logging.getLogger(__name__)

_CARD_ENTRY_TYPE = "plot:card"


class CardStoryTimeMixin:
    # ----- one card per scene (ADR-0097 §1) --------------------------------

    def _card_holding_scene(self, scene_id: str, *, excluding: str) -> CardSummary | None:
        # Every card visible at this layer (inherited included — the set `list_cards`
        # returns), by exact `plot:card` like the listing itself.
        for card in self._list_plot_folder_nodes(entry_type=_CARD_ENTRY_TYPE, summary_cls=CardSummary):
            if card.id != excluding and card.metadata.get("scene") == scene_id:
                return card
        return None

    def _require_scene_unheld(self, scene_id: object, card_id: str) -> None:
        """409 when another card already realizes `scene_id` (§1)."""
        if not isinstance(scene_id, str) or not scene_id:
            return
        holder = self._card_holding_scene(scene_id, excluding=card_id)
        if holder is not None:
            raise ProjectServiceError(
                f"Scene {scene_id} is already realized by card {holder.title or holder.id}; "
                "detach it there first.",
                409,
            )

    # ----- story rank (ADR-0097 §5) ----------------------------------------

    def _own_card_ranks(self) -> list[tuple[NodeIndexEntry, float | None]]:
        """The open layer's own cards with their story ranks — the layer story
        time ranks (inherited cards are never written)."""
        root = self._require_project()
        cards = []
        for entry in self._build_node_index().by_id.values():
            if entry.kind != "plot" or entry.entry_type != _CARD_ENTRY_TYPE:
                continue
            if not self._node_is_owned_here(entry, root):
                continue
            try:
                front_matter = self._read_front_matter_only(entry.path)
            except ProjectServiceError:
                continue
            cards.append((entry, parse_rank(front_matter.get(STORY_RANK_KEY))))
        return cards

    def _next_card_story_rank(self) -> Decimal:
        return next_story_rank([rank for _, rank in self._own_card_ranks()])

    def _write_story_rank(self, path: Path, rank: Decimal | float | None) -> None:
        """Rewrite `path`'s `story_rank:` line and nothing else, under the file's
        lock from read to write (a concurrent card save must neither drop this
        rank nor be undone by it). Recorded as a placement write so the
        session-boundary snapshot rule does not count it as a save."""
        with file_lock(path):
            original = path.read_bytes()
            updated = set_story_rank_in_text(original.decode("utf-8"), rank).encode("utf-8")
            if updated == original:
                return
            before = path.stat().st_mtime_ns
            atomic_write_bytes(path, updated)
            note_placement_write(path, before, path.stat().st_mtime_ns)
        self._maintain_index_after_write(path)

    def place_card(self, entry_id: str, request: PlaceCardRequest) -> CardEntry:
        """Move a card in story time: right after or right before a neighbour
        (ADR-0097 §4, story only). Ranks are the open layer's; an inherited card
        cannot be moved, nor anchored on."""
        root = self._require_project()
        card = self.read_card(entry_id)
        winner = self._build_node_index().by_id.get(entry_id)
        self._reject_inherited_book_local(entry_id, winner, root, noun="card")
        own = self._own_card_ranks()
        paths = {entry.id: entry.path for entry, _ in own}
        story = request.story
        anchor_id = story.after_id if story.after_id is not None else story.before_id
        if anchor_id == entry_id:
            raise ProjectServiceError("A card cannot be placed next to itself.", 422)
        if anchor_id not in paths:
            raise ProjectServiceError(
                f"Card {anchor_id} is not a card of this project; only its own cards can be an anchor.", 422
            )
        group = own_story_group([Sibling(entry.id, rank) for entry, rank in own])
        others = [sibling.id for sibling in group if sibling.id != entry_id]
        position = others.index(anchor_id) + (1 if story.after_id is not None else 0)
        # `plan_placement` orders its writes so every intermediate state still reads
        # in the right order (a renumber writes the last member first).
        for node_id, rank in plan_placement(group, entry_id, position):
            self._write_story_rank(paths[node_id], rank)
        return self.read_card(card.id)

    # ----- snapshot restore (ADR-0097 §1, §5) ------------------------------
    #
    # A restore is not a move in story time (the card keeps its CURRENT rank) and
    # never gives a card a scene another card now holds (it keeps the card, drops
    # the scene, and logs it — the restore has no warning channel to the client).

    def _live_story_rank(self, path: Path) -> float | None:
        live = self._read_front_matter_only(path) if path.exists() else {}
        return parse_rank(live.get(STORY_RANK_KEY))

    def _scene_to_drop_on_restore(self, node_id: str, scene: object) -> bool:
        if not isinstance(scene, str) or not scene:
            return False
        holder = self._card_holding_scene(scene, excluding=node_id)
        if holder is None:
            return False
        logger.warning(
            "Restoring card %s dropped its scene %s: card %s now realizes it.", node_id, scene, holder.id
        )
        return True

    def _adjust_restored_plot_card(
        self, kind: str, node_id: str, path: Path, frozen_bytes: bytes, migrated: MigratableDocument | None
    ) -> tuple[bytes, MigratableDocument | None]:
        """The restore's one hook: `(bytes, migrated)` in, the same pair out, a
        card's story rank and scene adjusted. Anything but a plot card passes
        through."""
        if kind != "plot":
            return frozen_bytes, migrated
        if migrated is not None:
            front_matter = self._restored_card_front_matter(node_id, path, dict(migrated.front_matter))
            return frozen_bytes, MigratableDocument(front_matter, migrated.body)
        return self._restored_card_text(node_id, path, frozen_bytes.decode("utf-8")).encode("utf-8"), None

    def _restored_card_text(self, node_id: str, path: Path, text: str) -> str:
        """A restored plot card's file text, adjusted (byte-restore branch). Anything
        but a card passes through."""
        if front_matter_in_text(text).get("entry_type") != _CARD_ENTRY_TYPE:
            return text
        text = set_story_rank_in_text(text, self._live_story_rank(path))
        dropped, scene = drop_card_scene_in_text(text)
        return dropped if self._scene_to_drop_on_restore(node_id, scene) else text

    def _restored_card_front_matter(
        self, node_id: str, path: Path, front_matter: dict[str, Any]
    ) -> dict[str, Any]:
        """The same adjustment for the migrated-document branch, which carries a
        front-matter mapping instead of bytes."""
        if front_matter.get("entry_type") != _CARD_ENTRY_TYPE:
            return front_matter
        front_matter = {key: value for key, value in front_matter.items() if key != STORY_RANK_KEY}
        live_rank = self._live_story_rank(path)
        if live_rank is not None:
            front_matter[STORY_RANK_KEY] = story_rank_value(live_rank)
        metadata = front_matter.get("metadata")
        if isinstance(metadata, dict) and self._scene_to_drop_on_restore(node_id, metadata.get("scene")):
            front_matter["metadata"] = {key: value for key, value in metadata.items() if key != "scene"}
        return front_matter
