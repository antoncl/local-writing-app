"""Decks — titled boxes of cards on the plot board (ADR-0097 §2).

Composed onto `ProjectService` beside `PlotMixin`, whose parametrized plot-folder
CRUD the five public methods wrap, like the character arc's. A deck nests inside
another by the `plot_deck` reference (never a tree placement, §2): this module
owns the one rule that reference carries — a deck never sits inside itself — and
the pure ordering the board projection reads.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    CreateDeckRequest,
    DeckEntry,
    DeckList,
    DeckSummary,
    SaveDeckRequest,
)
from app.services.project.errors import ProjectServiceError

PLOT_DECK_ENTRY_TYPE = "plot:deck"
# The metadata field a card (its home deck) and a deck (its parent deck) share.
DECK_FIELD = "plot_deck"
# An unwritten card's place in a manuscript container (ADR-0097 §6): the container,
# and the scene it follows there. Endpoint-owned, like `scene`.
PLANNED_IN_FIELD = "planned_in"
PLANNED_AFTER_FIELD = "planned_after"
_PLANNED_FIELDS = (PLANNED_IN_FIELD, PLANNED_AFTER_FIELD)


def without_planned(metadata: dict[str, Any]) -> dict[str, Any]:
    """`metadata` with both planned fields cleared — the card left its container."""
    return {key: value for key, value in metadata.items() if key not in _PLANNED_FIELDS}


def deck_board_order(decks: list[DeckSummary]) -> list[tuple[DeckSummary, str | None]]:
    """Every deck with its parent id, parents before children, siblings by
    `(title.lower(), id)` (ADR-0097 §8). A deck whose `plot_deck` dangles is top
    level; so is each deck on a reference cycle (a hand-edited file) — never
    dropped, never looped over."""
    by_id = {deck.id: deck for deck in decks}

    def parent_of(deck: DeckSummary) -> str | None:
        parent = deck.metadata.get(DECK_FIELD)
        return parent if isinstance(parent, str) and parent in by_id else None

    def on_cycle(deck: DeckSummary) -> bool:
        seen: set[str] = set()
        cursor = parent_of(deck)
        while cursor is not None and cursor not in seen:
            if cursor == deck.id:
                return True
            seen.add(cursor)
            cursor = parent_of(by_id[cursor])
        return False

    parents = {deck.id: None if on_cycle(deck) else parent_of(deck) for deck in decks}
    children: dict[str | None, list[DeckSummary]] = {}
    for deck in sorted(decks, key=lambda d: (d.title.lower(), d.id)):
        children.setdefault(parents[deck.id], []).append(deck)
    ordered: list[tuple[DeckSummary, str | None]] = []
    stack = list(reversed(children.get(None, [])))
    while stack:
        deck = stack.pop()
        ordered.append((deck, parents[deck.id]))
        stack.extend(reversed(children.get(deck.id, [])))
    return ordered


class DeckMixin:
    def list_decks(self) -> DeckList:
        return DeckList(
            entries=self._list_plot_folder_nodes(entry_type=PLOT_DECK_ENTRY_TYPE, summary_cls=DeckSummary)
        )

    def _require_deck(self, deck_id: str) -> None:
        """422 unless `deck_id` is a `plot:deck` node of this project."""
        entry = self._build_node_index().by_id.get(deck_id)
        if (
            entry is None
            or entry.kind != "plot"
            or PLOT_DECK_ENTRY_TYPE not in self.entry_type_ancestry(entry.entry_type)
        ):
            raise ProjectServiceError(f"{deck_id} is not a deck of this project.", 422)

    def _require_deck_not_inside_itself(self, deck_id: str, parent_id: object) -> None:
        """422 when giving `deck_id` the parent `parent_id` would make it its own
        ancestor — the parent is the deck itself or one of its descendants."""
        if not isinstance(parent_id, str) or not parent_id:
            return
        parents = {
            deck.id: deck.metadata.get(DECK_FIELD) for deck in self.list_decks().entries
        }
        seen: set[str] = set()
        cursor: object = parent_id
        while isinstance(cursor, str) and cursor and cursor not in seen:
            if cursor == deck_id:
                raise ProjectServiceError("A deck cannot sit inside itself.", 422)
            seen.add(cursor)
            cursor = parents.get(cursor)

    def create_deck(self, request: CreateDeckRequest) -> DeckEntry:
        if request.plot_deck:
            self._require_deck(request.plot_deck)
        return self.read_deck(
            self._create_plot_folder_node(
                title=request.title,
                requested_entry_type=request.entry_type,
                default_entry_type=PLOT_DECK_ENTRY_TYPE,
                noun="deck",
                seed_metadata={DECK_FIELD: request.plot_deck} if request.plot_deck else None,
                node_id=request.id or None,
            )
        )

    def read_deck(self, entry_id: str) -> DeckEntry:
        return self._build_plot_folder_entry(
            self._read_plot_folder_node(entry_id, expected_entry_type=PLOT_DECK_ENTRY_TYPE, noun="deck"),
            DeckEntry,
        )

    def save_deck(self, entry_id: str, request: SaveDeckRequest) -> DeckEntry:
        self._require_deck_not_inside_itself(entry_id, request.metadata.get(DECK_FIELD))
        return self.read_deck(
            self._save_plot_folder_node(entry_id, request, expected_entry_type=PLOT_DECK_ENTRY_TYPE, noun="deck")
        )

    def delete_deck(self, entry_id: str) -> DeckList:
        # Deletes only the deck: the reference purge frees its cards and child decks.
        self._delete_plot_folder_node(entry_id, expected_entry_type=PLOT_DECK_ENTRY_TYPE, noun="deck")
        return self.list_decks()
