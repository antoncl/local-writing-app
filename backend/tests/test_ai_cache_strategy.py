"""The cache-strategy objects (ADR-0084 §2-§3). Each strategy is a pure
function: blocks in, plan out. `AnthropicBreakpoints` pins the tier→ttl table
and the <=4-marker budget that used to live in `explicit_cache.py`; the other
two strategies pin the collapse shape shared by every non-marker provider."""

from __future__ import annotations

from app.services.ai.profiles.cache_strategy import (
    ANTHROPIC_BREAKPOINTS,
    GEMINI_BREAKPOINT,
    MAX_BREAKPOINTS,
    NO_CACHE,
    PREFIX_CACHE,
    STYLE_BY_KIND,
    TIER_TTL,
    AnthropicBreakpoints,
    CacheStrategy,
    GeminiBreakpoint,
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
    for strategy in (NO_CACHE, PREFIX_CACHE, ANTHROPIC_BREAKPOINTS, GEMINI_BREAKPOINT):
        assert strategy.kind in STYLE_BY_KIND
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


# ---- GeminiBreakpoint.plan (ADR-0084 Slice 2) ------------------------------


def test_gemini_marks_only_the_last_stable_block():
    blocks = [
        {"text": "system", "tier": "stable"},
        {"text": "staged", "tier": "stable"},
        {"text": "stable lore", "tier": "stable"},
        {"text": "volatile lore", "tier": "volatile"},
    ]
    plan = GEMINI_BREAKPOINT.plan(blocks)
    assert plan.mode == "markers"
    assert plan.cached is True
    marked = [i for i, b in enumerate(plan.blocks) if b.marker]
    assert marked == [2]
    assert plan.blocks[2].marker == {"type": "ephemeral"}
    assert "ttl" not in plan.blocks[2].marker
    assert [b.ttl_seconds for b in plan.blocks] == [300, 300, 300, None]


def test_gemini_no_stable_block_means_no_marker_or_projection():
    blocks = [
        {"text": "volatile 1", "tier": "volatile"},
        {"text": "volatile 2", "tier": "volatile"},
    ]
    plan = GEMINI_BREAKPOINT.plan(blocks)
    assert all(b.marker is None for b in plan.blocks)
    assert all(b.ttl_seconds is None for b in plan.blocks)


def test_gemini_empty_block_between_stables_is_dropped_and_marker_lands_on_last_stable():
    blocks = [
        {"text": "stable 1", "tier": "stable"},
        {"text": "", "tier": "stable"},
        {"text": "stable 2", "tier": "stable"},
    ]
    plan = GEMINI_BREAKPOINT.plan(blocks)
    assert [b.text for b in plan.blocks] == ["stable 1", "stable 2"]
    marked = [i for i, b in enumerate(plan.blocks) if b.marker]
    assert marked == [1]
    assert plan.blocks[1].marker == {"type": "ephemeral"}
    assert [b.ttl_seconds for b in plan.blocks] == [300, 300]


def test_gemini_single_stable_block_is_marked():
    plan = GEMINI_BREAKPOINT.plan([{"text": "only", "tier": "stable"}])
    assert plan.blocks[0].marker == {"type": "ephemeral"}
    assert plan.blocks[0].ttl_seconds == 300


def test_gemini_kind_caches_and_style():
    assert isinstance(GEMINI_BREAKPOINT, CacheStrategy)
    assert isinstance(GEMINI_BREAKPOINT, GeminiBreakpoint)
    assert GEMINI_BREAKPOINT.kind == "gemini"
    assert GEMINI_BREAKPOINT.caches is True
    assert STYLE_BY_KIND["gemini"] == "explicit"
