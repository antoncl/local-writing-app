"""The Anthropic dispatch helper wraps the system prompt as a cacheable
content block so prompt caching kicks in. This test pins the SDK-shape
contract; if Anthropic changes their caching markup spec we want a red
test, not silent regression.
"""

from __future__ import annotations

from app.services.ai.profiles.anthropic import (
    anthropic_system_blocks as _anthropic_system_blocks,
)
from app.services.ai.profiles.anthropic import (
    anthropic_system_with_cache as _anthropic_system_with_cache,
)

# ---- legacy single-string helper (back-compat) ---------------------------


def test_empty_system_is_unchanged():
    # Empty prompt stays empty so callers can skip the `system` kwarg.
    assert _anthropic_system_with_cache("") == ""


def test_nonempty_system_becomes_cacheable_block():
    # ADR-0060 §5: a system prompt is the most stable content → the stable (1h) ttl.
    out = _anthropic_system_with_cache("You are a helpful assistant.")
    assert out == [
        {
            "type": "text",
            "text": "You are a helpful assistant.",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]


def test_system_block_is_list_of_one():
    out = _anthropic_system_with_cache("Large stable preamble")
    assert isinstance(out, list)
    assert len(out) == 1


# ---- multi-block builder: tier → cache_control mapping (ADR-0060 §5) ------


def test_blocks_empty_list_returns_empty_string():
    assert _anthropic_system_blocks([]) == ""


def test_blocks_drops_empty_text_entries():
    out = _anthropic_system_blocks(
        [
            {"text": "real", "tier": "stable"},
            {"text": "", "tier": "stable"},
        ]
    )
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["text"] == "real"


def test_tiered_blocks_get_a_marker_untiered_do_not():
    out = _anthropic_system_blocks(
        [
            {"text": "system header", "tier": "stable"},
            {"text": "lore block", "tier": "volatile"},
            {"text": "no tier", "tier": None},
        ]
    )
    assert len(out) == 3
    assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert out[1]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert "cache_control" not in out[2]


def test_unknown_tier_gets_no_marker():
    # A tier the adapter doesn't recognise isn't cached rather than sent as garbage.
    out = _anthropic_system_blocks([{"text": "x", "tier": "bogus"}])
    assert "cache_control" not in out[0]


def test_breakpoints_capped_at_four_keeping_the_last_four():
    # Anthropic allows ≤4 cache_control markers. With 5 tiered blocks, only the
    # LAST 4 are marked — Anthropic caches the longest prefix at the latest marker,
    # so the earliest boundary is the cheapest to drop.
    blocks = [{"text": f"b{i}", "tier": "stable"} for i in range(5)]
    out = _anthropic_system_blocks(blocks)
    assert len(out) == 5
    assert [("cache_control" in b) for b in out] == [False, True, True, True, True]


def test_legacy_helper_uses_blocks_builder():
    # The legacy single-string helper produces the same shape as one stable block —
    # proves the back-compat wrapper is faithful and won't silently diverge.
    legacy = _anthropic_system_with_cache("hello")
    multi = _anthropic_system_blocks([{"text": "hello", "tier": "stable"}])
    assert legacy == multi
