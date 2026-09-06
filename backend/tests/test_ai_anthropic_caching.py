"""The Anthropic encoder renders a `CachePlan` onto the SDK's `system` shape.
This test pins the SDK-shape contract; if Anthropic changes their caching
markup spec we want a red test, not silent regression. (ADR-0084 Slice 1: the
plan is built by `cache_plan_for`/`ANTHROPIC_BREAKPOINTS.plan`, the encoder
only renders it — these expected wire dicts are unchanged from before the
split.)
"""

from __future__ import annotations

from app.services.ai.profiles.anthropic import AnthropicProfile
from app.services.ai.profiles.anthropic import (
    anthropic_system_blocks as _anthropic_system_blocks,
)
from app.services.ai.profiles.base import ChatCall
from app.services.ai.profiles.cache_strategy import ANTHROPIC_BREAKPOINTS

# ---- system-prompt-only path (cache_plan_for's wrap) -----------------------


def _plan_for_system_prompt(system_prompt: str):
    profile = AnthropicProfile(api_key="")
    call = ChatCall(
        model="claude-sonnet-4-6", system_prompt=system_prompt, messages=[], max_tokens=1
    )
    return profile.cache_plan_for(call)


def test_empty_system_is_unchanged():
    # Empty prompt stays empty so callers can skip the `system` kwarg.
    assert _anthropic_system_blocks(_plan_for_system_prompt("")) == ""


def test_nonempty_system_becomes_cacheable_block():
    # ADR-0060 §5: a system prompt is the most stable content → the stable (1h) ttl.
    out = _anthropic_system_blocks(_plan_for_system_prompt("You are a helpful assistant."))
    assert out == [
        {
            "type": "text",
            "text": "You are a helpful assistant.",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]


def test_system_block_is_list_of_one():
    out = _anthropic_system_blocks(_plan_for_system_prompt("Large stable preamble"))
    assert isinstance(out, list)
    assert len(out) == 1


# ---- multi-block builder: tier → cache_control mapping (ADR-0060 §5) ------


def test_blocks_empty_list_returns_empty_string():
    assert _anthropic_system_blocks(ANTHROPIC_BREAKPOINTS.plan([])) == ""


def test_blocks_drops_empty_text_entries():
    plan = ANTHROPIC_BREAKPOINTS.plan(
        [
            {"text": "real", "tier": "stable"},
            {"text": "", "tier": "stable"},
        ]
    )
    out = _anthropic_system_blocks(plan)
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["text"] == "real"


def test_tiered_blocks_get_a_marker_untiered_do_not():
    plan = ANTHROPIC_BREAKPOINTS.plan(
        [
            {"text": "system header", "tier": "stable"},
            {"text": "lore block", "tier": "volatile"},
            {"text": "no tier", "tier": None},
        ]
    )
    out = _anthropic_system_blocks(plan)
    assert len(out) == 3
    assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert out[1]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert "cache_control" not in out[2]


def test_unknown_tier_gets_no_marker():
    # A tier the adapter doesn't recognise isn't cached rather than sent as garbage.
    plan = ANTHROPIC_BREAKPOINTS.plan([{"text": "x", "tier": "bogus"}])
    out = _anthropic_system_blocks(plan)
    assert "cache_control" not in out[0]


def test_breakpoints_capped_at_four_keeping_the_last_four():
    # Anthropic allows ≤4 cache_control markers. With 5 tiered blocks, only the
    # LAST 4 are marked — Anthropic caches the longest prefix at the latest marker,
    # so the earliest boundary is the cheapest to drop.
    blocks = [{"text": f"b{i}", "tier": "stable"} for i in range(5)]
    out = _anthropic_system_blocks(ANTHROPIC_BREAKPOINTS.plan(blocks))
    assert len(out) == 5
    assert [("cache_control" in b) for b in out] == [False, True, True, True, True]


def test_system_prompt_wrap_matches_explicit_stable_block():
    # `cache_plan_for`'s system-prompt-only wrap produces the same shape as an
    # explicit one-block stable-tier call — proves the wrap is faithful and
    # won't silently diverge.
    from_prompt = _anthropic_system_blocks(_plan_for_system_prompt("hello"))
    from_blocks = _anthropic_system_blocks(
        ANTHROPIC_BREAKPOINTS.plan([{"text": "hello", "tier": "stable"}])
    )
    assert from_prompt == from_blocks
