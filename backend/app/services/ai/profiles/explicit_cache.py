"""Explicit prompt-cache mapping shared by the Anthropic-family adapters.

ADR-0060 §5: the shared block model (`ChatCall.system_blocks`, base.py) carries
only a volatility `tier`; Anthropic's ttl vocabulary and its 4-breakpoint cap live
**adapter-side**. Anthropic and OpenRouter's explicit routes both emit Anthropic's
`cache_control` primitive, so they share this one mapping here rather than
duplicating it. This is NOT the shared block model — it is the explicit-cache
adapters' common translation of `tier` into that wire format.
"""

from __future__ import annotations

# Volatility tier → cache_control ttl. `stable` (system, staged, settled lore)
# caches for an hour; `volatile` (new-or-changed lore) for five minutes.
TIER_TTL = {"stable": "1h", "volatile": "5m"}

# Anthropic's hard cap on `cache_control` markers per request.
MAX_BREAKPOINTS = 4


def cache_control_indices(
    blocks: list[dict], max_breakpoints: int = MAX_BREAKPOINTS
) -> set[int]:
    """The indices of `blocks` that should carry a `cache_control` marker: the
    non-empty, tiered blocks, capped to the LAST `max_breakpoints`. Anthropic
    caches the longest prefix at the latest marker, so when more than the cap are
    eligible the earliest boundaries are the cheapest to drop."""
    markable = [
        i
        for i, block in enumerate(blocks)
        if (block.get("text") or "") and block.get("tier") in TIER_TTL
    ]
    return set(markable[-max_breakpoints:])
