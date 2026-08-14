"""Cross-dimension plot diagnostics (ADR-0048 S7 — the payoff).

A plot board's value is holding several dimensions at once — reveal order, beat
sequence, authored causality. A *disagreement between two layers* is a plot problem
the writer can see nowhere else: a setup→payoff edge that runs backwards against
reveal order is a scene read out of sequence; an interior beat no card fulfils is a
hole. `compute_plot_diagnostics` derives those findings from an already-built
`PlotBoardProjection` — pure, deterministic, no LLM and no extra I/O (the AI
diagnostic pass is S7b). It rides along on the projection so the panel is live with
every board refetch.

Three detections, each with a strict anti-nag rule (off-page and unwritten cards are
legitimate — the tool reports, it never prescribes):

- ``causal_inversion`` — a card sets up a card revealed *earlier*. Both must be
  on-page (an off-page setup told-late has no reveal position to invert — legitimate).
- ``beat_inversion`` — within one plotline, a later beat is *fully* revealed before an
  earlier beat *begins*. Strict — braided/interleaving beats never flag.
- ``beat_gap`` — an interior beat no card fulfils, with a fulfilled beat still after it.
  A merely-unwritten *tail* is "not written yet", not a hole, and never flags.
"""

from __future__ import annotations

from app.models.entries import (
    PlotBoardCard,
    PlotBoardProjection,
    PlotDiagnostic,
    PlotDiagnosticCard,
    PlotDiagnosticEdge,
)


def compute_plot_diagnostics(projection: PlotBoardProjection) -> list[PlotDiagnostic]:
    """Derive the board's cross-dimension findings from a built projection (pure).

    Ordered causal inversions → beat inversions → beat gaps: the sharpest structural
    contradiction first, the softer "you skipped a beat" hint last."""
    cards_by_id = {card.id: card for card in projection.cards}
    findings: list[PlotDiagnostic] = []
    findings.extend(_causal_inversions(projection.cards, cards_by_id))
    findings.extend(_beat_inversions(projection.cards))
    findings.extend(_beat_gaps(projection))
    return findings


def _title(text: str, fallback: str) -> str:
    return text or fallback


def _causal_inversions(
    cards: list[PlotBoardCard], cards_by_id: dict[str, PlotBoardCard]
) -> list[PlotDiagnostic]:
    """A card *leads to* (`causal_links`) a card whose reveal rank is earlier: the
    payoff is read before its setup. Both endpoints must be on-page — an off-page card
    holds no reveal position, so there is simply no order to contradict (two cards on
    the *same* scene share a rank and never invert)."""
    out: list[PlotDiagnostic] = []
    for setup in cards:
        if setup.sequence is None:
            continue
        for target_id in setup.causal_links:
            payoff = cards_by_id.get(target_id)
            if payoff is None or payoff.sequence is None:
                continue
            if payoff.sequence < setup.sequence:
                out.append(
                    PlotDiagnostic(
                        id=f"causal:{setup.id}:{payoff.id}",
                        kind="causal_inversion",
                        message=(
                            f"“{_title(setup.title, 'Untitled card')}” sets up "
                            f"“{_title(payoff.title, 'untitled card')}”, but the payoff "
                            f"is revealed first — its setup comes later."
                        ),
                        cards=[
                            PlotDiagnosticCard(id=setup.id, title=setup.title),
                            PlotDiagnosticCard(id=payoff.id, title=payoff.title),
                        ],
                        edge=PlotDiagnosticEdge(source=setup.id, target=payoff.id),
                    )
                )
    return out


def _beat_inversions(cards: list[PlotBoardCard]) -> list[PlotDiagnostic]:
    """Within one plotline, a later beat is *entirely* revealed before an earlier beat
    *begins*. Reveal spans are read off the on-page cards linked to each beat; a strict
    ``later.max < earlier.min`` keeps braided beats (whose spans overlap) from flagging."""
    # (plotline_id, beat_id) -> reveal span + roster order + a title + the cards to light.
    spans: dict[tuple[str, str], _BeatSpan] = {}
    for card in cards:
        if card.sequence is None:
            continue
        for beat in card.beats:
            key = (beat.plotline_id, beat.beat_id)
            span = spans.get(key)
            if span is None:
                spans[key] = span = _BeatSpan(order=beat.number, title=beat.title, rank=card.sequence)
            else:
                span.extend(card.sequence)
            span.cards.append(PlotDiagnosticCard(id=card.id, title=card.title))

    by_plotline: dict[str, list[tuple[str, _BeatSpan]]] = {}
    for (plotline_id, beat_id), span in spans.items():
        by_plotline.setdefault(plotline_id, []).append((beat_id, span))

    out: list[PlotDiagnostic] = []
    for plotline_id, beats in by_plotline.items():
        beats.sort(key=lambda item: item[1].order)
        for i, (earlier_id, earlier) in enumerate(beats):
            for later_id, later in beats[i + 1 :]:
                if later.max < earlier.min:
                    out.append(
                        PlotDiagnostic(
                            id=f"beatorder:{plotline_id}:{earlier_id}:{later_id}",
                            kind="beat_inversion",
                            message=(
                                f"“{_title(later.title, 'A later beat')}” is fully "
                                f"revealed before “{_title(earlier.title, 'an earlier beat')}” "
                                f"begins — the beats are out of order."
                            ),
                            cards=[*earlier.cards, *later.cards],
                            plotline_id=plotline_id,
                            beat_ids=[earlier_id, later_id],
                        )
                    )
    return out


def _beat_gaps(projection: PlotBoardProjection) -> list[PlotDiagnostic]:
    """An interior beat no card fulfils, with a fulfilled beat still after it. The
    trailing run of unfilled beats past the last fulfilled one is "not written yet" —
    never a gap; a plotline with nothing written yet has no gaps at all."""
    out: list[PlotDiagnostic] = []
    for plotline in projection.plotlines:
        beats = plotline.beats
        last_filled = max(
            (i for i, beat in enumerate(beats) if beat.use_count > 0), default=-1
        )
        if last_filled < 0:
            continue
        for beat in beats[:last_filled]:
            if beat.use_count == 0:
                out.append(
                    PlotDiagnostic(
                        id=f"beatgap:{plotline.id}:{beat.beat_id}",
                        kind="beat_gap",
                        message=(
                            f"The “{_title(beat.title, 'untitled')}” beat of "
                            f"“{_title(plotline.title, 'this plotline')}” has no card, "
                            f"but later beats do."
                        ),
                        plotline_id=plotline.id,
                        beat_ids=[beat.beat_id],
                    )
                )
    return out


class _BeatSpan:
    """Mutable accumulator for a beat's reveal span while `_beat_inversions` folds over
    the cards linked to it: the min/max on-page reveal rank, the beat's roster order and
    title (for ordering + the message), and the cards to light when the finding is
    selected."""

    __slots__ = ("order", "title", "min", "max", "cards")

    def __init__(self, order: int, title: str, rank: int) -> None:
        self.order = order
        self.title = title
        self.min = rank
        self.max = rank
        self.cards: list[PlotDiagnosticCard] = []

    def extend(self, rank: int) -> None:
        self.min = min(self.min, rank)
        self.max = max(self.max, rank)
