"""The cache-strategy objects (ADR-0084 §2-§3). Each strategy is a pure
function: blocks in, plan out. `AnthropicBreakpoints` pins the tier→ttl table
and the <=4-marker budget that used to live in `explicit_cache.py`; the other
two strategies pin the collapse shape shared by every non-marker provider."""

from __future__ import annotations

from app.services.ai.profiles.cache_strategy import (
    ANTHROPIC_BREAKPOINTS,
    MAX_BREAKPOINTS,
    NO_CACHE,
    PREFIX_CACHE,
    STYLE_BY_KIND,
    TIER_TTL,
    AnthropicBreakpoints,
    CacheStrategy,
    NoCache,
    PrefixCache,
)

# ---- AnthropicBreakpoints.plan ---------------------------------------------


def test_tier_ttl_table():
    assert TIER_TTL == {"stable": "1h", "volatile": "5m"}


def test_only_tiered_non_empty_blocks_are_markable():
    blocks = [
        {"text": "a", "tier": "stable"},
        {"text": "", "tier": "stable"},  # empty → not markable
        {"text": "c", "tier": None},  # no tier → not markable
        {"text": "d", "tier": "bogus"},  # unknown tier → not markable
        {"text": "e", "tier": "volatile"},
    ]
    plan = ANTHROPIC_BREAKPOINTS.plan(blocks)
    assert plan.mode == "markers"
    assert plan.cached is True
    # Empty-text block dropped: 4 blocks remain (indices 0, 2, 3, 4 of input).
    assert [b.text for b in plan.blocks] == ["a", "c", "d", "e"]
    marked = {i for i, b in enumerate(plan.blocks) if b.marker}
    assert marked == {0, 3}  # "a" (was index 0) and "e" (was index 4)
    assert plan.blocks[0].marker == {"type": "ephemeral", "ttl": "1h"}
    assert plan.blocks[0].ttl_seconds == 3600
    assert plan.blocks[3].marker == {"type": "ephemeral", "ttl": "5m"}
    assert plan.blocks[3].ttl_seconds == 300
    assert plan.blocks[1].marker is None
    assert plan.blocks[1].ttl_seconds is None
    assert plan.blocks[2].marker is None


def test_budget_keeps_the_last_n_when_over_cap():
    blocks = [{"text": f"b{i}", "tier": "stable"} for i in range(MAX_BREAKPOINTS + 1)]
    plan = ANTHROPIC_BREAKPOINTS.plan(blocks)
    marked = [bool(b.marker) for b in plan.blocks]
    # Six eligible → only the last MAX_BREAKPOINTS keep a marker (the first drops).
    assert marked == [False] + [True] * MAX_BREAKPOINTS


def test_at_or_below_cap_marks_all_eligible():
    blocks = [{"text": f"b{i}", "tier": "stable"} for i in range(MAX_BREAKPOINTS)]
    plan = ANTHROPIC_BREAKPOINTS.plan(blocks)
    assert all(b.marker for b in plan.blocks)


def test_empty_is_empty():
    plan = ANTHROPIC_BREAKPOINTS.plan([])
    assert plan.blocks == []
    assert plan.mode == "markers"
    assert plan.cached is True


def test_bogus_tier_gets_no_marker():
    plan = ANTHROPIC_BREAKPOINTS.plan([{"text": "x", "tier": "bogus"}])
    assert plan.blocks[0].marker is None
    assert plan.blocks[0].ttl_seconds is None


# ---- NoCache / PrefixCache: collapse-mode plans ----------------------------


def test_no_cache_collapses_with_no_markers():
    plan = NO_CACHE.plan([{"text": "a", "tier": "stable"}, {"text": "b", "tier": "volatile"}])
    assert plan.mode == "collapse"
    assert plan.cached is False
    assert all(b.marker is None and b.ttl_seconds is None for b in plan.blocks)
    assert plan.collapsed_text() == "a\n\nb"


def test_prefix_cache_collapses_and_is_cached():
    plan = PREFIX_CACHE.plan([{"text": "a", "tier": "stable"}, {"text": "b", "tier": "volatile"}])
    assert plan.mode == "collapse"
    assert plan.cached is True
    assert all(b.marker is None and b.ttl_seconds is None for b in plan.blocks)
    assert plan.collapsed_text() == "a\n\nb"


def test_no_cache_drops_empty_text_blocks():
    plan = NO_CACHE.plan([{"text": "real", "tier": "stable"}, {"text": "", "tier": "stable"}])
    assert [b.text for b in plan.blocks] == ["real"]
    assert plan.collapsed_text() == "real"


def test_no_cache_empty_input_collapses_to_empty_string():
    plan = NO_CACHE.plan([])
    assert plan.blocks == []
    assert plan.collapsed_text() == ""


# ---- kind / caches class attrs + STYLE_BY_KIND coverage --------------------


def test_style_by_kind_covers_every_strategy_kind():
    for strategy in (NO_CACHE, PREFIX_CACHE, ANTHROPIC_BREAKPOINTS):
        assert strategy.kind in STYLE_BY_KIND
    # Gemini's kind is reserved for Slice 2 but the projection is pinned now.
    assert STYLE_BY_KIND == {
        "none": "none",
        "prefix": "auto",
        "anthropic": "explicit",
        "gemini": "explicit",
    }


def test_strategies_are_cache_strategy_instances_with_expected_kind_and_caches():
    assert isinstance(NO_CACHE, CacheStrategy) and isinstance(NO_CACHE, NoCache)
    assert NO_CACHE.kind == "none" and NO_CACHE.caches is False
    assert isinstance(PREFIX_CACHE, CacheStrategy) and isinstance(PREFIX_CACHE, PrefixCache)
    assert PREFIX_CACHE.kind == "prefix" and PREFIX_CACHE.caches is True
    assert isinstance(ANTHROPIC_BREAKPOINTS, CacheStrategy)
    assert isinstance(ANTHROPIC_BREAKPOINTS, AnthropicBreakpoints)
    assert ANTHROPIC_BREAKPOINTS.kind == "anthropic" and ANTHROPIC_BREAKPOINTS.caches is True
