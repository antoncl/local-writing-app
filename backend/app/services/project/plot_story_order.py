"""Story order for the plot context's cards (#2387).

A card written into a scene has a reading position: its scene's rank in the
manuscript. A card not yet in the manuscript has none, but the writer has usually
said where it goes by linking it — "Three Clocks leads to The Note Under the Door,
which leads to The Covering" puts the Note between those two scenes. So the board
reads in story order when the placed cards keep their manuscript order and each
unplaced card joins them through its causal links:

- after the card that leads to it (the latest one, if several do);
- with no positioned card leading to it, directly before the card it leads to;
- a chain of unplaced cards follows its links one card at a time;
- with no link that positions it at all, at the end.

Placed cards never move. A causal link that runs backwards between two placed
cards is a finding (a payoff set up too late), not something to sort away; an
unplaced card has no reading position for a link to contradict, so placing it by
its links hides nothing. When an unplaced card's own links disagree — it follows a
later card but leads to an earlier one — the incoming link wins, which leaves the
contradiction visible on the board.
"""

from __future__ import annotations

from app.models import PlotContextCard


def story_order(cards: list[PlotContextCard]) -> list[PlotContextCard]:
    """The cards in story order: placed cards by reading position, each unplaced
    card positioned by its causal links (see the module docstring)."""
    ordered = sorted((c for c in cards if c.sequence is not None), key=lambda c: c.sequence)
    pending = [c for c in cards if c.sequence is None]
    leads_here = {c.id: [p.id for p in cards if c.id in p.causal_out] for c in pending}
    while pending:
        card = _place_next(ordered, pending, leads_here)
        if card is None:
            break
        pending.remove(card)
    return ordered + pending


def _place_next(
    ordered: list[PlotContextCard],
    pending: list[PlotContextCard],
    leads_here: dict[str, list[str]],
) -> PlotContextCard | None:
    """Insert one pending card into `ordered` and return it, or None when no
    pending card can be positioned by its links. Following an incoming link is
    tried for every pending card before any card is placed by an outgoing one, so a
    card both linked to and linking on stays with the card that leads to it."""
    positions = {c.id: i for i, c in enumerate(ordered)}
    for card in pending:
        before = [positions[p] for p in leads_here[card.id] if p in positions]
        if before:
            index = max(before) + 1
            # Step over what already follows the same card — an earlier sibling and
            # the chain that sibling leads on to — so each keeps its run together.
            following = {ordered[max(before)].id}
            while index < len(ordered) and following.intersection(leads_here.get(ordered[index].id, ())):
                following.add(ordered[index].id)
                index += 1
            ordered.insert(index, card)
            return card
    for card in pending:
        after = [positions[t] for t in card.causal_out if t in positions]
        if after:
            ordered.insert(min(after), card)
            return card
    return None
