"""A cache strategy is an object the provider picks per model (ADR-0084 §2-§3).

`ChatCall.system_blocks` (ADR-0060 §5) carries a volatility-ordered list of
`{"text", "tier"}` blocks and never speaks a provider's caching vocabulary. A
`CacheStrategy` turns that ordering into a `CachePlan` within one provider's
limits: which blocks get a marker, what each marker says, and how long the
provider is expected to keep each block. The transport (a provider profile's
connection/SDK code) encodes the plan onto its wire shape without
interpreting it — see `ProviderProfile.cache_plan_for` (base.py).

This is where the 4-breakpoint cap and the `1h`/`5m` ttl tokens live, moved
here from `explicit_cache.py` (ADR-0060 §5); that module retires with this one.

Strategies: `NoCache`, `PrefixCache`, `AnthropicBreakpoints`, `GeminiBreakpoint`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

# Volatility tier → cache_control ttl. `stable` (system, staged, settled lore)
# caches for an hour; `volatile` (new-or-changed lore) for five minutes.
TIER_TTL = {"stable": "1h", "volatile": "5m"}
_TIER_TTL_SECONDS = {"stable": 3600, "volatile": 300}

# Anthropic's hard cap on `cache_control` markers per request.
MAX_BREAKPOINTS = 4

# Gemini's implicit cache is a fixed, non-renewing term (OpenRouter's guide,
# read 2026-09-06) — unlike Anthropic's, a hit does not extend it.
GEMINI_TTL_SECONDS = 300


@dataclass(frozen=True)
class PlannedBlock:
    """One block after planning: its text, its policy tier (carried through
    unchanged), the exact marker payload to attach (or None), and the
    strategy's projection of how long it stays cached (None = unknown/uncached).
    """

    text: str
    tier: str | None
    marker: dict | None
    ttl_seconds: int | None


@dataclass(frozen=True)
class CachePlan:
    """The output of `CacheStrategy.plan` — transport-neutral, blocks in wire
    order with empty-text blocks already dropped."""

    mode: Literal["markers", "collapse"]
    cached: bool
    blocks: list[PlannedBlock]

    def collapsed_text(self) -> str:
        """The collapse-mode wire body: block texts joined by a blank line."""
        return "\n\n".join(block.text for block in self.blocks)


class CacheStrategy(ABC):
    """One caching behaviour, chosen by a provider per model. Pure: `plan`
    reads only the blocks it is handed — no session, no settings, no token
    counter — and must not reorder or re-tier."""

    kind: ClassVar[str]
    caches: ClassVar[bool]

    @abstractmethod
    def plan(self, blocks: Sequence[Mapping[str, Any]]) -> CachePlan: ...


class _CollapseStrategy(CacheStrategy):
    """Shared shape for the marker-less strategies: collapse to one string, no
    markers, no projected ttl. Subclasses differ only in `kind`/`caches`."""

    def plan(self, blocks: Sequence[Mapping[str, Any]]) -> CachePlan:
        return CachePlan(
            mode="collapse",
            cached=self.caches,
            blocks=[
                PlannedBlock(text=b.get("text") or "", tier=b.get("tier"), marker=None, ttl_seconds=None)
                for b in blocks
                if (b.get("text") or "")
            ],
        )


class NoCache(_CollapseStrategy):
    """No caching at all (Ollama; unknown OpenRouter routes)."""

    kind = "none"
    caches = False


class PrefixCache(_CollapseStrategy):
    """Automatic prefix caching (OpenAI native; most OpenRouter routes): the
    provider caches transparently, at an unstated term."""

    kind = "prefix"
    caches = True


class AnthropicBreakpoints(CacheStrategy):
    """Anthropic's explicit `cache_control` markers. Absorbs `explicit_cache.py`
    verbatim: a marker on the LAST `MAX_BREAKPOINTS` eligible (non-empty,
    tiered) blocks, payload `{"type": "ephemeral", "ttl": "1h"|"5m"}` by tier.
    A block with no tier, a bogus tier, or beyond the cap gets no marker.

    The budget is computed over the ORIGINAL indices — before dropping empty
    blocks — exactly as `cache_control_indices` did, so "the last 4 eligible"
    matches today byte-for-byte once empties are dropped afterward.
    """

    kind = "anthropic"
    caches = True

    def plan(self, blocks: Sequence[Mapping[str, Any]]) -> CachePlan:
        blocks = list(blocks)
        markable = [
            i
            for i, block in enumerate(blocks)
            if (block.get("text") or "") and block.get("tier") in TIER_TTL
        ]
        budget = set(markable[-MAX_BREAKPOINTS:])
        planned: list[PlannedBlock] = []
        for i, block in enumerate(blocks):
            text = block.get("text") or ""
            if not text:
                continue
            tier = block.get("tier")
            marker: dict | None = None
            ttl_seconds: int | None = None
            if i in budget:
                ttl = TIER_TTL[tier]
                marker = {"type": "ephemeral", "ttl": ttl}
                ttl_seconds = _TIER_TTL_SECONDS[tier]
            planned.append(PlannedBlock(text=text, tier=tier, marker=marker, ttl_seconds=ttl_seconds))
        return CachePlan(mode="markers", cached=self.caches, blocks=planned)


class GeminiBreakpoint(CacheStrategy):
    """Gemini via OpenRouter honours ONE `cache_control` breakpoint (the last), no `ttl`,
    and caches the prefix up to it for a fixed five minutes that does not renew.
    So: one marker, on the last stable-tier non-empty block; blocks up to and including
    it project `ttl_seconds=300`; blocks after it (volatile) project None.
    No stable block → no marker, no projections."""

    kind = "gemini"
    caches = True

    def plan(self, blocks: Sequence[Mapping[str, Any]]) -> CachePlan:
        blocks = list(blocks)
        stable_indices = [
            i
            for i, block in enumerate(blocks)
            if (block.get("text") or "") and block.get("tier") == "stable"
        ]
        breakpoint_index = stable_indices[-1] if stable_indices else None
        planned: list[PlannedBlock] = []
        for i, block in enumerate(blocks):
            text = block.get("text") or ""
            if not text:
                continue
            tier = block.get("tier")
            marker: dict | None = None
            ttl_seconds: int | None = None
            if breakpoint_index is not None and i <= breakpoint_index:
                ttl_seconds = GEMINI_TTL_SECONDS
                if i == breakpoint_index:
                    marker = {"type": "ephemeral"}
            planned.append(PlannedBlock(text=text, tier=tier, marker=marker, ttl_seconds=ttl_seconds))
        return CachePlan(mode="markers", cached=self.caches, blocks=planned)


NO_CACHE = NoCache()
PREFIX_CACHE = PrefixCache()
ANTHROPIC_BREAKPOINTS = AnthropicBreakpoints()
GEMINI_BREAKPOINT = GeminiBreakpoint()

# Slice 1: `caching_style()` stays a concrete base method (retires in Slice 3)
# so `preview.py`, `_row_to_descriptor`'s capability, and the frontend don't
# move yet. This is the only place that projects a strategy's `kind` onto the
# three-value enum.
STYLE_BY_KIND = {"none": "none", "prefix": "auto", "anthropic": "explicit", "gemini": "explicit"}
