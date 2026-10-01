"""A deck and its manuscript container: realize, attach, detach, and the displayed
text (ADR-0097 §3, §7).

Composed onto `ProjectService` beside `DeckMixin`. A deck's `realized_container`
is owned by these endpoints: `save_deck` keeps the on-disk value. While a deck is
realized its own title and body are frozen and it shows its container's title and
summary; this module is where text moves between the two, mirroring a card and its
scene (`card_scene.py`, whose conflict error and summary writer it reuses).
"""

from __future__ import annotations

from typing import Any

from app.models import (
    AttachDeckRequest,
    CardSummary,
    CreateStructureNodeRequest,
    DeckEntry,
    DeckTextRequest,
    DetachDeckRequest,
    RealizeDeckResult,
    SaveDeckRequest,
    StructureDocument,
    StructureLevel,
    StructureNode,
)
from app.services.project.card_scene import _text_choice_required
from app.services.project.decks import DECK_FIELD, PLANNED_IN_FIELD, REALIZED_FIELD
from app.services.project.errors import ProjectServiceError
from app.services.project.placement import Sibling
from app.services.project.story_time import own_story_group
from app.services.project.tree_configs import MANUSCRIPT_TREE
from app.services.project.tree_nodes import level_at
from app.services.tree_structure import TreeStructureService

_SUMMARY_FIELD = "summary"
_CARD_ENTRY_TYPE = "plot:card"


class DeckRealizeMixin:
    def _container_node(self, container_id: object, document: StructureDocument | None = None) -> StructureNode | None:
        """The manuscript container `container_id`, or None when it is no longer
        one (deleted, or a scene)."""
        if not isinstance(container_id, str) or not container_id:
            return None
        node = TreeStructureService.find_node(document or self.read_structure(), container_id)
        return None if node is None or self._is_leaf_node(node) else node

    def _container_level_name(self, container_id: str) -> str:
        node = self._container_node(container_id)
        return (node.level_name if node is not None else None) or "container"

    def _container_summary(self, container_id: str) -> str:
        return str(self.read_scene(container_id).metadata.get(_SUMMARY_FIELD) or "")

    def _require_container_unheld(self, container_id: str, deck_id: str) -> None:
        """409 when another deck is already realized as `container_id` (§7)."""
        for other in self.list_decks().entries:
            if other.id != deck_id and other.metadata.get(REALIZED_FIELD) == container_id:
                raise ProjectServiceError(
                    f"Container {container_id} is already realized by deck {other.title or other.id}; "
                    "detach it there first.",
                    409,
                )

    def _require_deck_here(self, deck: DeckEntry) -> None:
        """Refuse an inherited deck: realize / attach / detach write the deck."""
        self._reject_inherited_book_local(
            deck.id, self._build_node_index().by_id.get(deck.id), self._require_project(), noun="deck"
        )

    def _write_deck_fields(
        self,
        deck: DeckEntry,
        *,
        title: str | None = None,
        body: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DeckEntry:
        """The internal deck write that may set `realized_container` or change a
        realized deck's frozen text — past `save_deck`'s pin. Fields left None keep
        the deck's own."""
        return self._write_deck(
            deck.id,
            SaveDeckRequest(
                title=deck.title if title is None else title,
                body=deck.body if body is None else body,
                entry_type=deck.entry_type,
                metadata=deck.metadata if metadata is None else metadata,
                base_revision=deck.revision,
            ),
        )

    def _realize_target(self, deck: DeckEntry, document: StructureDocument) -> tuple[str | None, StructureLevel | None]:
        """Where realizing `deck` would create its container: the parent deck's
        container when that deck is realized, else the top of the manuscript — and
        the level there (None when the level list has none)."""
        parent_deck = deck.metadata.get(DECK_FIELD)
        parent = None
        if isinstance(parent_deck, str) and parent_deck:
            parent = self._container_node(self.read_deck(parent_deck).metadata.get(REALIZED_FIELD), document)
        level = (parent.level or 0) + 1 if parent is not None else 1
        if level > len(document.levels):
            return (parent.id if parent else None), None
        return (parent.id if parent else None), level_at(document.levels, level)

    def realize_deck(self, entry_id: str) -> RealizeDeckResult:
        """Create a manuscript container from a deck (ADR-0097 §7): titled as the
        deck, its summary the deck's body, under the parent deck's container when
        that is realized. Every own unwritten card whose home deck this is, and that
        no chapter plans yet, is planned in it in story-time order; no scene is
        created. Everything refusable is checked before the container exists."""
        deck = self.read_deck(entry_id)
        self._require_deck_here(deck)
        if deck.metadata.get(REALIZED_FIELD):
            raise ProjectServiceError("This deck is already realized; detach it first.", 409)
        document = self.read_structure()
        parent_id, level = self._realize_target(deck, document)
        if level is None:
            raise ProjectServiceError("The level list has no level for a container here.", 422)
        created = self.create_structure_node(
            CreateStructureNodeRequest(
                title=deck.title, entry_type=level.type or MANUSCRIPT_TREE.container_type, parent_id=parent_id
            )
        )
        before = {node.id for node in TreeStructureService.collect(document.root, skip_root=True)}
        container_id = next(
            node.id for node in TreeStructureService.collect(created.root, skip_root=True) if node.id not in before
        )
        if deck.body.strip():
            self._set_scene_summary(container_id, deck.body.strip())
        realized = self._write_deck_fields(deck, metadata={**deck.metadata, REALIZED_FIELD: container_id})
        planned = self._plan_deck_cards(realized.id, container_id, created)
        return RealizeDeckResult(deck=realized, container_id=container_id, planned=planned)

    def _plan_deck_cards(self, deck_id: str, container_id: str, document: StructureDocument) -> list[str]:
        """Plan every own unwritten card homed in `deck_id` in `container_id`, in
        story-time order. A card already planned in a live container keeps that plan
        — the writer placed it. Returns the ids planned."""
        live = {node.id for node in TreeStructureService.collect(document.root, skip_root=True) if not self._is_leaf_node(node)}
        summaries = {
            card.id: card
            for card in self._list_plot_folder_nodes(entry_type=_CARD_ENTRY_TYPE, summary_cls=CardSummary)
        }
        group = own_story_group([Sibling(entry.id, rank) for entry, rank in self._own_card_ranks()])
        planned: list[str] = []
        for sibling in group:
            summary = summaries.get(sibling.id)
            if summary is None:
                continue
            metadata = summary.metadata
            if metadata.get(DECK_FIELD) != deck_id or metadata.get("scene") or metadata.get(PLANNED_IN_FIELD) in live:
                continue
            card = self.read_card(sibling.id)
            self._write_card_fields(card, metadata={**card.metadata, PLANNED_IN_FIELD: container_id})
            planned.append(card.id)
        return planned

    def attach_deck(self, entry_id: str, request: AttachDeckRequest) -> DeckEntry:
        """Re-link a deck to an existing container (ADR-0097 §7; the undo of a
        detach). The deck then shows the container's title and summary; an empty
        summary is seeded from the deck's synopsis, and two different non-empty
        texts make the writer choose (`request.text`)."""
        deck = self.read_deck(entry_id)
        self._require_deck_here(deck)
        if deck.metadata.get(REALIZED_FIELD):
            raise ProjectServiceError("This deck is already realized; detach it first.", 409)
        if self._container_node(request.container_id) is None:
            raise ProjectServiceError(f"{request.container_id} is not a container of this manuscript.", 422)
        self._require_container_unheld(request.container_id, entry_id)
        summary = self._container_summary(request.container_id)
        synopsis = deck.body.strip()
        if not summary.strip():
            if synopsis:
                self._set_scene_summary(request.container_id, synopsis)
        elif synopsis and synopsis != summary.strip():
            if request.text is None:
                raise _text_choice_required(summary, synopsis)
            if request.text == "card":
                self._set_scene_summary(request.container_id, synopsis)
        return self._write_deck_fields(deck, metadata={**deck.metadata, REALIZED_FIELD: request.container_id})

    def detach_deck(self, entry_id: str, request: DetachDeckRequest) -> DeckEntry:
        """Unbind a deck from its container (ADR-0097 §3, §7). The deck takes the
        container's title; its body becomes the summary unless it holds a different
        synopsis of its own, in which case the writer chooses (`request.text`). The
        container and the cards planned in it stay."""
        deck = self.read_deck(entry_id)
        self._require_deck_here(deck)
        container_id = deck.metadata.get(REALIZED_FIELD)
        if not container_id:
            raise ProjectServiceError("This deck is not realized.", 409)
        container_id = str(container_id)
        summary = self._container_summary(container_id)
        body = deck.body
        if not body.strip() or body.strip() == summary.strip():
            body = summary
        elif summary.strip():
            if request.text is None:
                raise _text_choice_required(summary, body.strip())
            if request.text == "scene":
                body = summary
        metadata = {key: value for key, value in deck.metadata.items() if key != REALIZED_FIELD}
        return self._write_deck_fields(
            deck, title=self.read_scene(container_id).title, body=body, metadata=metadata
        )

    def set_deck_text(self, entry_id: str, request: DeckTextRequest) -> DeckEntry:
        """Edit the title and/or synopsis a deck DISPLAYS (ADR-0097 §3): the
        container's while the deck is realized, the deck's own otherwise."""
        if request.title is not None and not request.title.strip():
            raise ProjectServiceError("Title cannot be empty.", 422)
        deck = self.read_deck(entry_id)
        self._require_deck_here(deck)
        container_id = deck.metadata.get(REALIZED_FIELD)
        if not container_id:
            return self._write_deck_fields(deck, title=request.title, body=request.synopsis)
        container_id = str(container_id)
        if request.title is not None and request.title != self.read_scene(container_id).title:
            self.rename_structure_node(container_id, request.title)
        if request.synopsis is not None:
            self._set_scene_summary(container_id, request.synopsis)
        return self.read_deck(entry_id)
