"""The explicit-cache mapping shared by the Anthropic-family adapters (ADR-0060
§5). Pins the tier→ttl table and the ≤4-marker budget in one place, since both
`anthropic.py` and `openrouter.py` translate `tier` through it."""

from __future__ import annotations

from app.services.ai.profiles.explicit_cache import (
    MAX_BREAKPOINTS,
    TIER_TTL,
    cache_control_indices,
)


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
    assert cache_control_indices(blocks) == {0, 4}


def test_budget_keeps_the_last_n_when_over_cap():
    blocks = [{"text": f"b{i}", "tier": "stable"} for i in range(MAX_BREAKPOINTS + 1)]
    # Six eligible → only the last MAX_BREAKPOINTS keep a marker.
    assert cache_control_indices(blocks) == set(range(1, MAX_BREAKPOINTS + 1))


def test_at_or_below_cap_marks_all_eligible():
    blocks = [{"text": f"b{i}", "tier": "stable"} for i in range(MAX_BREAKPOINTS)]
    assert cache_control_indices(blocks) == set(range(MAX_BREAKPOINTS))


def test_empty_is_empty():
    assert cache_control_indices([]) == set()
