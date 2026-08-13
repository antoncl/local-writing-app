"""Spoiler-gated plot context for AI reasoning (ADR-0048 S8a; ADR-0053).

`read_plot_context` assembles the board's plot state — plotlines with their full
beat rosters, and the cards with their synopses, beat links and causal edges —
into one `PlotContext` packet a prompt can reason over. A plotline IS a plot-template
instance (ADR-0053 §1), so a single plotline set carries both the thread colour and
the beat structure the cards are measured against. It is the foundation Slice 8b's
card brainstorm reasons from, and the read behind the "what the AI sees" preview
endpoint.

The packet is **spoiler-gated by manuscript reveal order.** Every carded scene
holds a reading-order rank (`_board_container_map`'s `scene_to_order`, the same
rank the board's manuscript-order edge layer uses). Given an `as_of` anchor — a
card or a scene — cards up to and including its rank are included and later cards
are withheld but COUNTED (`omitted_cards`): the AI is told more exists without
seeing it, so a "what's next / what's missing" question never leaks unwritten-ahead
scenes and railroads the writer. A scene-less card (off-page / unwritten) holds no
reveal position, so it is never a spoiler and is always admitted.

Plotlines are the writer's own scaffolding, not manuscript content, so they are
never gated; the full beat roster is always present so the AI can name a beat no
card fulfils yet — the gaps.

This is context assembly (prompt INPUT). None of the quarry's claims/evidence
apparatus survives (migration principle 2); the JSON node-patch loop, not an XML
suggestion protocol, is how the AI writes back (Slice 8b).

Composed onto `ProjectService` beside `PlotMixin`, whose resolve helpers it reuses
through the MRO (`read_plot_board`, `list_cards` / `list_plotlines`,
`_board_container_map`, `_resolve_card_beats`, `_resolve_card_causal`,
`_board_page_status`).
"""

from __future__ import annotations

from typing import Any

from app.models import (
    PlotContext,
    PlotContextBeat,
    PlotContextCard,
    PlotContextPlotline,
)

# On-disk metadata field keys this mixin reads a card / plotline's metadata by — the
# same schema field-name literals plot.py reads them by; named here for legibility.
# The card→beat and card→causal resolutions, which key off plot.py's own
# `beat_links` / `causal_links` constants, are delegated to its `_resolve_card_beats`
# / `_resolve_card_causal`, so those keys are not restated here (no shared-constant
# drift seam to keep in sync).
_SCENE_FIELD = "scene"
_PLOTLINE_FIELD = "plotline"
_INSTANCE_BEATS_FIELD = "instance_beats"
_SOURCE_TEMPLATE_NAME_FIELD = "source_template_name"
_COLOR_FIELD = "color"


class PlotContextMixin:
    """Spoiler-gated plot-context assembly for prompt reasoning (ADR-0048 S8a)."""

    def read_plot_context(self, as_of: str | None = None) -> PlotContext:
        """Assemble the board's plot state into a `PlotContext`, spoiler-gated by
        the reveal `sequence` of the optional `as_of` anchor (a card or scene id).

        No anchor (or one that names no reveal position — an unknown id or a
        scene-less card) ⇒ the whole board, nothing withheld."""
        board = self.read_plot_board()
        _containers, _scene_to_container, scene_to_order = self._board_container_map()
        cards = self.list_cards().entries

        anchor_scene_id, anchor_rank = self._resolve_context_anchor(as_of, cards, scene_to_order)
        gated = anchor_rank is not None

        # Partition cards by the reveal gate: a carded card past the anchor is
        # withheld and only counted; a scene-less card carries no reveal position
        # and is always admitted (off-page / unwritten cards are never spoilers).
        admitted: list[Any] = []
        omitted = 0
        for card in cards:
            scene = card.metadata.get(_SCENE_FIELD) or None
            seq = scene_to_order.get(scene) if scene else None
            if gated and seq is not None and seq > anchor_rank:
                omitted += 1
                continue
            admitted.append(card)
        admitted_ids = {card.id for card in admitted}

        plotlines, plotline_titles, beat_catalog = self._context_plotlines()
        context_cards = [
            self._context_card(card, scene_to_order, plotline_titles, beat_catalog, admitted_ids)
            for card in admitted
        ]

        return PlotContext(
            board_id=board.id,
            completeness="through_as_of" if gated else "whole_board",
            as_of_scene_id=anchor_scene_id if gated else None,
            as_of_sequence=anchor_rank if gated else None,
            omitted_cards=omitted,
            plotlines=plotlines,
            cards=context_cards,
        )

    def _resolve_context_anchor(
        self, as_of: str | None, cards: list[Any], scene_to_order: dict[str, int]
    ) -> tuple[str | None, int | None]:
        """Resolve `as_of` to `(scene_id, reveal_rank)`. It may be a scene id
        (→ its rank) or a card id (→ its scene's rank). An anchor that names no
        reveal position — absent, an unknown id, or a scene-less card — yields
        `(None, None)`: no gate, the whole board."""
        if not as_of:
            return None, None
        if as_of in scene_to_order:
            return as_of, scene_to_order[as_of]
        for card in cards:
            if card.id == as_of:
                scene = card.metadata.get(_SCENE_FIELD) or None
                if scene and scene in scene_to_order:
                    return scene, scene_to_order[scene]
                return None, None
        return None, None

    def _context_plotlines(
        self,
    ) -> tuple[list[PlotContextPlotline], dict[str, str], dict[str, tuple[str, str | None, dict[str, str]]]]:
        """All plotlines with their FULL beat rosters (ADR-0053 §1) — ungated
        scaffolding, so a beat no card fulfils still appears (a gap for the AI to
        name). One traversal of `list_plotlines` builds three things at once: the
        `PlotContextPlotline` list (thread + beats + lineage), a `{id: title}` map the
        cards resolve their primary plotline name by, and a `{plotline_id:
        (title, colour, {beat_id: beat title})}` catalog — the shape
        `_resolve_card_beats` consumes so a card's beat links resolve to titled badges
        by a map lookup rather than a re-read. The board projection fills the colour so
        a card can tint its badges; the AI context never renders colour, so the catalog
        holds the slot as None rather than shipping an unused swatch id."""
        plotlines: list[PlotContextPlotline] = []
        plotline_titles: dict[str, str] = {}
        catalog: dict[str, tuple[str, str | None, dict[str, str]]] = {}
        for line in self.list_plotlines().entries:
            plotline_titles[line.id] = line.title
            beats: list[PlotContextBeat] = []
            titles: dict[str, str] = {}
            raw = line.metadata.get(_INSTANCE_BEATS_FIELD)
            if isinstance(raw, list):
                for beat in raw:
                    if not isinstance(beat, dict):
                        continue
                    beat_id = beat.get("id")
                    if not isinstance(beat_id, str) or not beat_id:
                        continue
                    title = str(beat.get("title") or "")
                    beats.append(
                        PlotContextBeat(
                            beat_id=beat_id,
                            title=title,
                            function=str(beat.get("function") or ""),
                            guidance=str(beat.get("guidance") or ""),
                        )
                    )
                    titles[beat_id] = title
            plotlines.append(
                PlotContextPlotline(
                    id=line.id,
                    title=line.title,
                    color=line.metadata.get(_COLOR_FIELD) or None,
                    source_template_name=str(line.metadata.get(_SOURCE_TEMPLATE_NAME_FIELD) or ""),
                    beats=beats,
                )
            )
            catalog[line.id] = (line.title, None, titles)  # colour unused in AI context
        return plotlines, plotline_titles, catalog

    def _context_card(
        self,
        card: Any,
        scene_to_order: dict[str, int],
        plotline_titles: dict[str, str],
        beat_catalog: dict[str, tuple[str, str | None, dict[str, str]]],
        admitted_ids: set[str],
    ) -> PlotContextCard:
        """Project one admitted card for the AI: synopsis + plotline + reveal rank
        + page status + the beats it fulfils + the cards it leads to. Beat links
        resolve through PlotMixin's `_resolve_card_beats` against `beat_catalog`
        (dropping a link whose arc or beat is gone — the same display-side heal the
        board projection applies), and `causal_out` is filtered to `admitted_ids`
        via `_resolve_card_causal` so a withheld card never leaks through an edge."""
        scene = card.metadata.get(_SCENE_FIELD) or None
        plotline_id = card.metadata.get(_PLOTLINE_FIELD) or None
        return PlotContextCard(
            id=card.id,
            title=card.title,
            synopsis=card.body,
            plotline_id=plotline_id,
            plotline_title=plotline_titles.get(plotline_id) if plotline_id else None,
            scene_id=scene,
            sequence=scene_to_order.get(scene) if scene else None,
            page_status=self._board_page_status(card.metadata, scene),
            beats=self._resolve_card_beats(card.metadata, beat_catalog),
            causal_out=self._resolve_card_causal(card.metadata, admitted_ids, card.id),
        )
