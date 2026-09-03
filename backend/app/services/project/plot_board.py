"""The board (plot:board) — the read/projection face of the plot kind (ADR-0048
S7a; ADR-0053; ADR-0080 §5): plotlines + character arcs + cards, projected into
the shape the SvelteFlow board renders — beat rosters, manuscript containers,
resolved beat badges and causal edges. Read-only and computed; the board's own
persisted state is only its opaque `layout` payload.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from app.models import (
    CharacterArcSummary,
    PlotBoard,
    PlotBoardBeat,
    PlotBoardCard,
    PlotBoardCharacterArc,
    PlotBoardContainer,
    PlotBoardPlotline,
    PlotBoardPlotlineBeat,
    PlotBoardProjection,
    PlotlineSummary,
    SavePlotBoardRequest,
    StructureNode,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.plot import (
    _BEAT_LINK_FIELD,
    _CAUSAL_LINK_FIELD,
    _PAGE_STATUS_FIELD,
    PLOT_BOARD_FILENAME,
    PLOT_CHARACTER_ARC_ENTRY_TYPE,
    PLOT_PLOTLINE_ENTRY_TYPE,
)
from app.services.project.plot_diagnostics import compute_plot_diagnostics
from app.services.tree_structure import StructureVisitor, TreeStructureService


class _PlotBoardLayout(StructureVisitor):
    """Rank each carded leaf scene by reading order and map it to its
    innermost-container id; mint each container once, parented to its nearest
    container ancestor (a node directly under root has None). Pre-order ==
    reading order, so encounter order is the rank and `containers` lands in
    manuscript order. `is_leaf` is the same leaf/container line seed-from-
    manuscript uses (type == manuscript:scene, not merely "has a scene_id")."""

    def __init__(self, is_leaf: Callable[[StructureNode], bool]) -> None:
        self._is_leaf = is_leaf
        self.containers: dict[str, PlotBoardContainer] = {}
        self.scene_to_container: dict[str, str] = {}
        self.scene_to_order: dict[str, int] = {}

    def visit_node(
        self, node: StructureNode, ancestors: tuple[StructureNode, ...]
    ) -> None:
        parent = ancestors[-1] if ancestors else None
        parent_container = (
            parent.id if parent is not None and parent.type != "root" else None
        )
        if self._is_leaf(node):
            if node.scene_id:
                # Rank by encounter order (pre-order == reading order); a scene
                # under the root is homeless but still ranked.
                self.scene_to_order[node.scene_id] = len(self.scene_to_order)
                if parent_container is not None:
                    self.scene_to_container[node.scene_id] = parent_container
        elif node.id not in self.containers:
            self.containers[node.id] = PlotBoardContainer(
                id=node.id, title=node.title, parent=parent_container
            )


class _ThreadCatalogEntry(NamedTuple):
    """One `plot:thread` holder (plotline or arc) as the beat-badge catalog resolves
    it (ADR-0080 §5): title, colour, beat roster (id -> title), holder subtype, and —
    for an arc — the bound character's identity triple (None for a plotline)."""

    title: str
    color: str | None
    beat_titles: dict[str, str]
    holder_kind: str
    character_id: str | None
    character_name: str | None
    character_initial: str | None


class PlotBoardMixin:
    """The board-projection slice of `ProjectService`. Composes onto
    `ProjectService` beside `PlotMixin` / `PlotContextMixin` (via MRO); its
    methods reach the shared plot/ CRUD, node index, and structure helpers
    those mixins (and the base service) define through `self._…` — never a
    cross-module import."""

    # ----- The board (plot:board) — a per-project layout singleton --------

    def _plot_board_path(self) -> Path:
        return self._require_project() / PLOT_BOARD_FILENAME

    def read_plot_board(self) -> PlotBoard:
        """Open the board, creating it on first open (ADR-0048 §3).

        Unlike the project node (project.md always exists from create_project),
        the board is minted lazily the first time it is opened, so an absent
        file is created here rather than 404'd. It lives outside the `plot/`
        family folder and is not in the node index — one board per open book.
        """
        path = self._plot_board_path()
        if not path.exists():
            self._write_plot_board_file(path, PlotBoard(id=self._new_id("plot"), layout={}))
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "plot:board"
        entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "plot:board"
        raw_layout = front_matter.get("layout")
        layout = raw_layout if isinstance(raw_layout, dict) else {}
        return PlotBoard(
            id=node_id,
            title=str(front_matter.get("title") or "Board"),
            revision=self._revision(path),
            entry_type=entry_type,
            layout=layout,
        )

    def save_plot_board(self, request: SavePlotBoardRequest) -> PlotBoard:
        path = self._plot_board_path()
        exists = path.exists()
        current_revision = self._revision(path) if exists else ""
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Plot board changed on disk after it was opened.", 409)
        # Identity rides the file, not the request — a save never re-mints an id
        # the file already carries; an absent (or id-less) file is minted here,
        # the same repair contract as the project node.
        node_id = (self._front_matter_id(path) if exists else None) or self._new_id("plot")
        board = PlotBoard(id=node_id, revision=current_revision, layout=request.layout)
        self._write_plot_board_file(path, board)
        return self.read_plot_board()

    def _write_plot_board_file(self, path: Path, board: PlotBoard) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": board.id,
                "title": board.title,
                "entry_type": board.entry_type,
                "layout": board.layout,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        self._atomic_write(path, f"---\n{front_matter}\n---\n")

    def read_plot_board_projection(self) -> PlotBoardProjection:
        """The board's render model in one read (ADR-0048 S7a + Slice 4; ADR-0053;
        ADR-0080 §5): plotlines AND character arcs — sibling `plot:thread` holders,
        projected as separate bands (`plotlines` / `arcs`) with their beat rosters —
        the manuscript containers a card lays out inside, the cards with their
        refs + resolved container + beat badges (tagged by holder subtype), and the
        board's opaque layout. Read-only and computed — never the Library templates.

        Card refs need no dangling-resolution here: deleting a scene or a plotline
        purges the referencing cards (delete_scene / delete_plotline →
        `_purge_references_to`), so a stored ref is always either live or already
        blanked to "" — the same invariant the unset case relies on. A plain
        `or None` is the whole of "resolve a ref"; a gone scene projects as an
        unattached card (ADR §S5), never a dangling pointer.

        The structure is walked exactly once (`_board_container_map`) and joined
        onto the cards in memory, so the projection adds no per-card structure I/O.
        """
        board = self.read_plot_board()
        plotline_entries = self.list_plotlines().entries
        # ADR-0080 §5: character arcs enumerate alongside plotlines — their own band,
        # resolved through the same beat machinery (both are `plot:thread` holders).
        arc_entries = self.list_character_arcs().entries
        card_entries = self.list_cards().entries
        # One pass over every card's beat links yields two things with no extra I/O:
        # the per-(holder, beat) USE-COUNT a plotline/arc node shows (0 = a gap the
        # structure exposes; ADR-0053 §6 / S5a), and the set of holders some card
        # links — this already covers arc holder ids, unchanged, since beat_links are
        # keyed by holder id.
        use_counts: dict[str, Counter[str]] = {}
        for card in card_entries:
            for plotline_id, beat_id in self._iter_valid_beat_link_pairs(card.metadata.get(_BEAT_LINK_FIELD)):
                use_counts.setdefault(plotline_id, Counter())[beat_id] += 1
        plotlines = [
            PlotBoardPlotline(
                id=line.id,
                title=line.title,
                color=line.metadata.get("color") or None,
                beats=self._plotline_board_beats(line.metadata, use_counts.get(line.id)),
            )
            for line in plotline_entries
        ]
        # Built once for character resolution — reused by the arc list AND the beat
        # catalog below, so no second full node-index build.
        index = self._build_node_index()
        arcs = []
        for arc in arc_entries:
            character_id, character_name, character_initial = self._resolve_arc_character(
                arc.metadata.get("character"), index
            )
            arcs.append(PlotBoardCharacterArc(
                id=arc.id, title=arc.title, color=arc.metadata.get("color") or None,
                character_id=character_id, character_name=character_name, character_initial=character_initial,
                beats=self._plotline_board_beats(arc.metadata, use_counts.get(arc.id)),
            ))
        containers, scene_to_container, scene_to_order = self._board_container_map()
        # Resolve card→beat badges against the live plotlines AND arcs once per
        # projection (Slice 5b; ADR-0053; ADR-0080 §5): a titled, subtype-tagged
        # badge per link via map lookup, built from the lists already fetched above,
        # limited to the holders some card links (the use_counts keys).
        beat_catalog = self._thread_beat_catalog(plotline_entries, arc_entries, set(use_counts), index)
        # The live card ids, so authored causal links resolve to real edge endpoints
        # (Slice 6b) — the display side of `_heal_causal_links`, symmetric with the
        # beat catalog above.
        card_ids = {card.id for card in card_entries}
        cards: list[PlotBoardCard] = []
        used_containers: set[str] = set()
        for card in card_entries:
            scene = card.metadata.get("scene") or None
            container = scene_to_container.get(scene) if scene else None
            # Mark the card's container and every ancestor used, so a nesting box
            # (a "part" between act and chapter) is projected even with no direct card.
            cursor = container
            while cursor is not None and cursor not in used_containers:
                used_containers.add(cursor)
                cursor = containers[cursor].parent
            cards.append(
                PlotBoardCard(
                    id=card.id,
                    title=card.title,
                    synopsis=card.body,
                    plotline=card.metadata.get("plotline") or None,
                    scene=scene,
                    container=container,
                    page_status=self._board_page_status(card.metadata, scene),
                    beats=self._resolve_card_beats(card.metadata, beat_catalog),
                    sequence=scene_to_order.get(scene) if scene else None,
                    causal_links=self._resolve_card_causal(card.metadata, card_ids, card.id),
                )
            )
        # Reading order (containers is already ordered), used-only — an empty
        # container is not a board concern.
        board_containers = [c for cid, c in containers.items() if cid in used_containers]
        projection = PlotBoardProjection(
            board_id=board.id,
            board_revision=board.revision,
            layout=board.layout,
            plotlines=plotlines,
            arcs=arcs,
            containers=board_containers,
            cards=cards,
        )
        # Cross-dimension findings (ADR-0048 S7) derive purely from the projection just
        # built — no further reads — and ride along so the panel is live per refetch.
        projection.diagnostics = compute_plot_diagnostics(projection)
        return projection

    def _board_container_map(
        self,
    ) -> tuple[dict[str, PlotBoardContainer], dict[str, str], dict[str, int]]:
        """Walk the manuscript once → (containers-by-id in reading order,
        scene_id → innermost-container-id, scene_id → reading-order rank).

        A *container* is a non-leaf structure node other than the root — an act, a
        chapter, whatever container types the project declares (`_is_leaf_node`
        draws the leaf/container line, the same test seed-from-manuscript uses). A
        card lays out inside its scene's INNERMOST container (the scene's immediate
        parent); the board nests that box inside its ancestors via `parent`. A scene
        directly under the root has no container (it maps to nothing here), so its
        card is homeless — same as a scene-less card.

        `scene_to_order` ranks EVERY carded leaf scene by manuscript reading order
        (0-based, in pre-order) — including a scene directly under the root, which
        is homeless (no container) yet still holds a reveal-order position (ADR-0048
        S7 Slice 6). The board's manuscript-order edge layer chains cards by this
        rank, and the beat-sequence layer orders a beat's cards by it.

        `containers` is insertion-ordered by a pre-order walk, i.e. manuscript
        reading order, which the board relies on to lay acts/chapters out in order.
        """
        layout = _PlotBoardLayout(self._is_leaf_node)
        TreeStructureService.walk(
            self.read_structure().root,
            layout,
            skip_root=True,
            is_leaf=self._is_leaf_node,
        )
        return layout.containers, layout.scene_to_container, layout.scene_to_order

    def _board_page_status(self, metadata: dict[str, Any], scene: str | None) -> str | None:
        """The card's page status as the board shows it (ADR-0048 S7 Slice 5b):
        `on_page` when a scene is attached (the shared `_page_status_from_scene` rule,
        overriding any stored value), else the authored `off_page` / `unwritten`, else
        None — the sparse default, which reads as unwritten. Derived from the CURRENT
        scene, so a stale stored `on_page` on a since-detached card (the card list
        skips read-side healing) never reaches the board. The valid-value filter is a
        read-time defense (write-time schema validation is what strips a bad value)."""
        derived = self._page_status_from_scene(scene)
        if derived is not None:
            return derived
        stored = metadata.get(_PAGE_STATUS_FIELD)
        return stored if stored in ("off_page", "unwritten") else None

    @staticmethod
    def _iter_roster_beats(metadata: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield each well-formed beat dict — one carrying a non-empty string `id` —
        from a plotline's `instance_beats` roster, in stored order (ADR-0053). One
        place decides what a valid roster beat is, so the board-node roster, the
        card-badge catalog, and the AI context can't drift on it. A plotline's own
        writes id-heal the roster, so a beat lacking an id is a belt-and-braces skip."""
        raw = metadata.get("instance_beats")
        if not isinstance(raw, list):
            return
        for beat in raw:
            if isinstance(beat, dict) and isinstance(beat.get("id"), str) and beat["id"]:
                yield beat

    def _plotline_board_beats(
        self, metadata: dict[str, Any], use_counts: Mapping[str, int] | None = None
    ) -> list[PlotBoardPlotlineBeat]:
        """A `plot:thread` holder's beat roster as the board node renders it (ADR-0053
        §3; ADR-0080 §5): each beat's stable id + title, in stored order, with its
        `use_count` (how many cards fulfil it). Shared by plotlines (event-beats) and
        character arcs (change-beats) — both read `instance_beats` the same way.
        `use_counts` maps this holder's beat ids to their counts — absent is 0."""
        counts = use_counts or {}
        return [
            PlotBoardPlotlineBeat(
                beat_id=beat["id"],
                title=str(beat.get("title") or ""),
                use_count=counts.get(beat["id"], 0),
            )
            for beat in self._iter_roster_beats(metadata)
        ]

    def _resolve_arc_character(
        self, character_id: str | None, index: Any
    ) -> tuple[str | None, str | None, str | None]:
        """(id, display name, single-letter avatar) for an arc's bound character, or
        (None, None, None) when unbound. Name is the character node's title from the
        already-built node index (no extra read); avatar is its first character,
        upper-cased. A bound-but-gone character still returns the id, unresolved."""
        if not character_id:
            return (None, None, None)
        entry = index.by_id.get(character_id)
        if entry is None:
            return (character_id, None, None)  # bound but the character is gone
        name = entry.title or ""
        return (character_id, name or None, (name[:1].upper() or None))

    def _thread_beat_catalog(
        self,
        plotline_entries: list[PlotlineSummary],
        arc_entries: list[CharacterArcSummary],
        referenced: set[str],
        index: Any,
    ) -> dict[str, _ThreadCatalogEntry]:
        """`thread holder id -> _ThreadCatalogEntry` for each `referenced` plotline OR
        character arc (ADR-0080 §5; ADR-0048 S7 Slice 5b; ADR-0053), so a card's beat
        badges resolve by map lookup rather than a read per link. Built from the
        plotline/arc summaries already listed — no second front-matter read; an
        unreadable holder never enters those lists, so its links drop, matching
        `_heal_beat_links`. An arc's entry also resolves its bound character."""
        catalog: dict[str, _ThreadCatalogEntry] = {}
        tagged = [(e, PLOT_PLOTLINE_ENTRY_TYPE) for e in plotline_entries]
        tagged += [(e, PLOT_CHARACTER_ARC_ENTRY_TYPE) for e in arc_entries]
        for entry, holder_kind in tagged:
            if entry.id not in referenced:
                continue
            titles = {beat["id"]: str(beat.get("title") or "") for beat in self._iter_roster_beats(entry.metadata)}
            character_id, character_name, character_initial = self._resolve_arc_character(
                entry.metadata.get("character"), index
            ) if holder_kind == PLOT_CHARACTER_ARC_ENTRY_TYPE else (None, None, None)
            catalog[entry.id] = _ThreadCatalogEntry(
                title=entry.title,
                color=entry.metadata.get("color") or None,
                beat_titles=titles,
                holder_kind=holder_kind,
                character_id=character_id,
                character_name=character_name,
                character_initial=character_initial,
            )
        return catalog

    def _resolve_card_beats(
        self, metadata: dict[str, Any], catalog: dict[str, _ThreadCatalogEntry]
    ) -> list[PlotBoardBeat]:
        """Resolve a card's stored `beat_links` (id pairs) into board badges (ADR-0048
        S7 Slice 5b; ADR-0053; ADR-0080 §5), dropping any link whose holder or beat is
        gone (the display side of `_heal_beat_links`). Well-formedness + dedup are the
        shared `_iter_valid_beat_link_pairs`; this adds the catalog lookup + title
        resolution, tagging each beat with its holder's subtype and — for an arc —
        the bound character's identity, so the frontend renders a change-beat pill
        distinctly from an event-beat one. Order follows the stored list."""
        resolved: list[PlotBoardBeat] = []
        for plotline_id, beat_id in self._iter_valid_beat_link_pairs(metadata.get(_BEAT_LINK_FIELD)):
            entry = catalog.get(plotline_id)
            if entry is None:
                continue  # holder gone / not referenced → drop (display-side heal)
            title = entry.beat_titles.get(beat_id)
            if title is None:
                continue  # beat left the roster → drop
            resolved.append(
                PlotBoardBeat(
                    plotline_id=plotline_id,
                    plotline_title=entry.title,
                    plotline_color=entry.color,
                    beat_id=beat_id,
                    title=title,
                    # 1-based position in the holder's roster (#941). `beat_titles` is
                    # built from `_iter_roster_beats` in order, so its key order IS the
                    # roster order; the pair is already validated present above.
                    number=list(entry.beat_titles).index(beat_id) + 1,
                    holder_kind=entry.holder_kind,
                    character_id=entry.character_id,
                    character_name=entry.character_name,
                    character_initial=entry.character_initial,
                )
            )
        return resolved

    def _resolve_card_causal(
        self, metadata: dict[str, Any], card_ids: set[str], self_id: str
    ) -> list[str]:
        """Resolve a card's stored `causal_links` into the target card ids the board
        draws edges to (ADR-0048 S7 Slice 6b), dropping any target that is gone, is a
        self-reference, or isn't a live card (the display side of `_heal_causal_links`).
        Well-formedness + dedup are the shared `_iter_valid_causal_targets`; this adds
        the live-card + non-self filter. Order follows the stored list, so it is stable
        across reads."""
        return [
            target
            for target in self._iter_valid_causal_targets(metadata.get(_CAUSAL_LINK_FIELD))
            if target != self_id and target in card_ids
        ]
