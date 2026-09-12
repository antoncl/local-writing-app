"""ADR-0086: the inferred lore selection fits a per-turn token budget.

The one selector (`lore_selection._select_lore`) now says, for every id it
produces, whether the author *declared* it (a `use()` pick, a scene ref, an
`always` policy) or the app *inferred* it (a journal detection, the structural
one-hop). This module is the pure half: the value types that carry that
provenance, and `fit_lore_budget`, which walks the inferred candidates in fit
order and keeps each whole entry that still fits. Declared entries are never
walked, never counted against the budget, never dropped (ADR-0086 §1–§3).

No project access here: the caller renders every candidate once and hands the
`{id: xml}` map in, so this is tested as a function. The project-aware
composition (select → render → fit → tier) that the send and the preview share
is `lore_selection._budgeted_lore_tiers`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, get_args

from app.models import LoreFit, LoreFitEntry, LoreSource
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

# ADR-0086 §1 fit order — distance from the author's own words: what they typed
# this session, what their prompt named, what the anchored scene's prose names,
# what the app found one textual hop from those, what it followed through graph
# edges. The order is `LoreSource`'s declaration order (`app.models`), spelled
# once; lower ranks fit first, so the budget drops the structural hop first.
_SOURCE_RANK: dict[str, int] = {source: rank for rank, source in enumerate(get_args(LoreSource))}

# The two hops `named` expansion turns off; everything else is an entry the
# author, the prompt, or the scene actually named.
HOP_SOURCES: frozenset[str] = frozenset({"depth1_expansion", "structural_hop"})
NAMED_SOURCES: frozenset[str] = frozenset(_SOURCE_RANK) - HOP_SOURCES


def source_rank(source: str) -> int:
    """The fit rank of a source — lower fits first. The one precedence the
    journal's promotion rule (ADR-0086 Amendment 1) and the fit share; a
    source outside the closed set is a programming error."""
    try:
        return _SOURCE_RANK[source]
    except KeyError:
        raise ValueError(
            f"unknown lore source {source!r}; the fit knows {sorted(_SOURCE_RANK)}"
        ) from None


@dataclass(frozen=True)
class LoreLimits:
    """What the assistant allows an ordinary turn's inferred lore: the token
    budget (§2) and how far the app may reach for candidates (§2b). Resolved
    beside `max_tokens` in `resolve_call_params`; the defaults are what a
    call with no assistant gets."""

    budget_tokens: int = DEFAULT_LORE_BUDGET_TOKENS
    expansion: LoreExpansion = "one_hop"


# The resolver's defaults as one shared (frozen) value, for signatures that
# default to them.
DEFAULT_LORE_LIMITS = LoreLimits()


@dataclass(frozen=True)
class InferredCandidate:
    """One id the app inferred, with why (`source`) and when it was first
    noticed under that source (`added_at_turn`; the journal holds at most one
    entry per (id, source) — a better-ranked re-mention is a second entry,
    ADR-0086 Amendment 1 — and the selector keeps the best-ranked candidate
    per id; a structural-hop id carries no turn and orders by id). A source
    outside the fit's closed set is a programming error and fails here,
    loudly — never a silent re-rank."""

    id: str
    source: LoreSource
    added_at_turn: int = 0

    def __post_init__(self) -> None:
        if self.source not in _SOURCE_RANK:
            raise ValueError(
                f"unknown lore source {self.source!r}; the fit knows {sorted(_SOURCE_RANK)}"
            )

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


@dataclass(frozen=True)
class BudgetedLoreTiers:
    """What `lore_selection._budgeted_lore_tiers` hands the send and the
    preview alike: the kept entries as `(id, element_xml)` pairs per tier (the
    send wraps them; the preview surfaces them), the left-out entries' own
    elements keyed by id (the door's drill), and the fit report."""

    stable_entries: list[tuple[str, str]]
    volatile_entries: list[tuple[str, str]]
    left_out_entries: dict[str, str] = field(default_factory=dict)
    report: LoreFit = field(default_factory=lambda: LoreFit(
        budget_tokens=0, used_tokens=0, declared_tokens=0, kept=0
    ))


def fit_lore_budget(
    selection: LoreSelection,
    rendered: Mapping[str, str],
    budget_tokens: int,
    *,
    titles: Mapping[str, str] | None = None,
    count: Callable[[str], int] = default_token_count,
) -> BudgetedLore:
    """Walk the inferred candidates in fit order and keep each whole entry
    whose rendered size fits in what remains of the budget (`<=`); leave the
    rest out and continue, so an oversized entry doesn't block the smaller
    ones ordered below it (ADR-0086 §3). The declared set is not walked
    against the budget and never dropped; it is counted only to report
    `declared_tokens` (§5) — a declared set alone larger than the budget is
    reported, never rationed.

    `rendered` is `{id: element_xml}` for every candidate the caller could
    render; an id absent from it was unreadable and is not sendable, so it is
    skipped on both sides. `titles` is `{id: title}` from the same render, so
    a left-out entry is named by the node the model would have seen — one
    provenance, no second read. `count` is the one estimator every profile
    already uses (`default_token_count`), injectable for tests.
    """
    remaining = max(0, budget_tokens)
    names = titles or {}
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
        left_out.append(
            LoreFitEntry(
                id=candidate.id,
                title=names.get(candidate.id, ""),
                source=candidate.source,
                tokens=tokens,
            )
        )
    report = LoreFit(
        budget_tokens=max(0, budget_tokens),
        used_tokens=used,
        declared_tokens=declared_tokens,
        kept=len(kept),
        left_out=left_out,
    )
    return BudgetedLore(kept_ids=sorted(kept), report=report)
