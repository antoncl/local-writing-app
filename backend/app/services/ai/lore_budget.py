"""ADR-0086: the inferred lore selection fits a per-turn token budget.

The one selector (`lore_selection._select_lore`) now says, for every id it
produces, whether the author *declared* it (a `use()` pick, a scene ref, an
`always` policy) or the app *inferred* it (a journal detection, the structural
one-hop). This module is the pure half: the value types that carry that
provenance, and `fit_lore_budget`, which walks the inferred candidates in fit
order and keeps each whole entry that still fits. Declared entries are never
walked, never counted against the budget, never dropped (ADR-0086 §1–§3).

No project access here: the caller renders every candidate once and hands the
`{id: xml}` map in, so this is tested as a function.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.models import LoreFit, LoreFitEntry
from app.services.ai.profiles.base import default_token_count

# ADR-0086 §2: the resolver's default when the assistant leaves
# `ai_lore_budget_tokens` blank (or sets it to something that isn't a
# non-negative number). A starting point, not a derivation: roughly four to
# five times the transcript that lost in #1874 and under half the lore block
# that beat it. `0` is legal and means "declared entries only".
DEFAULT_LORE_BUDGET_TOKENS = 16_000

# ADR-0086 §2b: by which routes the app may reach inferred lore. `one_hop` is
# today's behaviour (both the textual depth-1 hop and the structural hop);
# `named` sends only what was actually named — the two hops are not taken.
LoreExpansion = Literal["one_hop", "named"]

# The fit's own closed source set: the journal's `JournalSource` values plus
# the structural hop, which the journal never records (ADR-0086 §5). The
# journal's own type is deliberately not widened.
LoreSource = Literal[
    "user_message", "rendered_prompt", "scene_prose", "depth1_expansion", "structural_hop"
]

# ADR-0086 §1 fit order: distance from the author's own words — what they typed
# this session, what their prompt named, what the anchored scene's prose names,
# what the app found one textual hop from those, what it followed through graph
# edges. Lower ranks fit first; the budget drops the structural hop first.
_SOURCE_RANK: dict[str, int] = {
    "user_message": 0,
    "rendered_prompt": 1,
    "scene_prose": 2,
    "depth1_expansion": 3,
    "structural_hop": 4,
}

# The sources `named` expansion keeps: an entry the author, the prompt, or the
# scene actually named. The two hops (`depth1_expansion`, `structural_hop`)
# are what `named` turns off.
NAMED_SOURCES: frozenset[str] = frozenset({"user_message", "rendered_prompt", "scene_prose"})


@dataclass(frozen=True)
class LoreLimits:
    """What the assistant allows an ordinary turn's inferred lore: the token
    budget (§2) and how far the app may reach for candidates (§2b). Resolved
    beside `max_tokens` in `resolve_call_params`; the defaults are what a
    call with no assistant gets."""

    budget_tokens: int = DEFAULT_LORE_BUDGET_TOKENS
    expansion: LoreExpansion = "one_hop"


@dataclass(frozen=True)
class InferredCandidate:
    """One id the app inferred, with why (`source`) and when it was first
    noticed (`added_at_turn` — the journal records no re-mentions; a
    structural-hop id carries no turn and orders by id)."""

    id: str
    source: LoreSource
    added_at_turn: int = 0
    title: str = ""

    @property
    def fit_key(self) -> tuple[int, int, str]:
        """`(source, -added_at_turn, id)`: total, deterministic, no title."""
        return (_SOURCE_RANK[self.source], -self.added_at_turn, self.id)


@dataclass(frozen=True)
class LoreSelection:
    """The selector's two sets (ADR-0086 §1). `declared` is never dropped;
    `inferred` is already minus `declared` (precedence: an id reachable both
    ways is declared), deduped by id, and in fit order. Both are past the one
    `never` chokepoint."""

    declared: frozenset[str]
    inferred: tuple[InferredCandidate, ...]

    @property
    def ids(self) -> list[str]:
        """The id-sorted union — the `list[str]` face `_relevant_lore_ids`
        keeps for its callers."""
        return sorted(self.declared | {c.id for c in self.inferred})


@dataclass(frozen=True)
class BudgetedLore:
    """`fit_lore_budget`'s result: the ids to send (id-sorted, the wire order
    `_tier_lore_ids` relies on) and the report the send hands back (§5)."""

    kept_ids: list[str]
    report: LoreFit


def fit_lore_budget(
    selection: LoreSelection,
    rendered: Mapping[str, str],
    budget_tokens: int,
    *,
    count: Callable[[str], int] = default_token_count,
    title_of: Callable[[str], str] | None = None,
) -> BudgetedLore:
    """Walk the inferred candidates in fit order and keep each whole entry
    whose rendered size fits in what remains of the budget (`<=`); leave the
    rest out and continue, so an oversized entry doesn't block the smaller
    ones ordered below it (ADR-0086 §3). The declared set is neither walked nor
    counted: declared plus up to a budget's worth of inferred is what a turn
    sends, and a declared set alone larger than the budget is reported, never
    rationed.

    `rendered` is `{id: element_xml}` for every candidate the caller could
    render; an id absent from it was unreadable and is not sendable, so it is
    skipped on both sides. `count` is the one estimator every profile uses
    (`default_token_count`), injectable for tests. `title_of` fills the title
    of a left-out entry the selection couldn't name (a structural-hop id
    carries no journal snapshot); it is called only for what was left out.
    """
    remaining = max(0, budget_tokens)
    declared_tokens = sum(count(rendered[eid]) for eid in selection.declared if eid in rendered)
    kept: set[str] = {eid for eid in selection.declared if eid in rendered}
    used = 0
    left_out: list[LoreFitEntry] = []
    for candidate in selection.inferred:
        xml = rendered.get(candidate.id)
        if xml is None:
            continue
        tokens = count(xml)
        if tokens <= remaining:
            remaining -= tokens
            used += tokens
            kept.add(candidate.id)
            continue
        title = candidate.title or (title_of(candidate.id) if title_of is not None else "")
        left_out.append(
            LoreFitEntry(id=candidate.id, title=title, source=candidate.source, tokens=tokens)
        )
    report = LoreFit(
        budget_tokens=max(0, budget_tokens),
        used_tokens=used,
        declared_tokens=declared_tokens,
        kept=len(kept),
        left_out=left_out,
    )
    return BudgetedLore(kept_ids=sorted(kept), report=report)
