"""OpenRouter dispatch path — system message construction and session
stickiness. We can't call the live API in tests, so we pin the pure
plan-encoder function instead (ADR-0084 Slice 1: it takes a `CachePlan`, not
raw blocks + a style string). If OpenRouter's caching protocol changes (or a
routed-to provider's cache strategy changes), these red-line clearly.
"""

from __future__ import annotations

from app.services.ai.profiles.base import ChatCall
from app.services.ai.profiles.cache_strategy import (
    ANTHROPIC_BREAKPOINTS,
    GEMINI_BREAKPOINT,
    NO_CACHE,
    PREFIX_CACHE,
)
from app.services.ai.profiles.openrouter import OpenRouterProfile
from app.services.ai.profiles.openrouter import (
    openrouter_extra_body as _openrouter_extra_body,
)
from app.services.ai.profiles.openrouter import (
    openrouter_system_messages as _openrouter_system_messages,
)

# ---- cache_strategy (prefix lookup) ----------------------------------------


def test_cache_strategy_anthropic_is_anthropic_breakpoints():
    profile = OpenRouterProfile(api_key="")
    assert profile.cache_strategy("anthropic/claude-sonnet-4-6") is ANTHROPIC_BREAKPOINTS


def test_cache_strategy_google_is_gemini_breakpoint():
    profile = OpenRouterProfile(api_key="")
    assert profile.cache_strategy("google/gemini-2.5-flash") is GEMINI_BREAKPOINT


def test_cache_strategy_openai_is_prefix_cache():
    profile = OpenRouterProfile(api_key="")
    assert profile.cache_strategy("openai/gpt-4.1") is PREFIX_CACHE
    assert profile.cache_strategy("deepseek/deepseek-chat") is PREFIX_CACHE


def test_cache_strategy_unknown_prefix_is_no_cache():
    profile = OpenRouterProfile(api_key="")
    assert profile.cache_strategy("unknown/some-model") is NO_CACHE


def test_cache_strategy_empty_id_is_no_cache():
    profile = OpenRouterProfile(api_key="")
    assert profile.cache_strategy("") is NO_CACHE


# ---- _openrouter_system_messages (the meaty part) -------------------------


def test_no_system_returns_empty_list():
    assert _openrouter_system_messages(ANTHROPIC_BREAKPOINTS.plan([])) == []
    assert _openrouter_system_messages(NO_CACHE.plan([])) == []


def test_plain_string_system_yields_string_content():
    call = ChatCall(
        model="openai/gpt-4.1", system_prompt="You are helpful.", messages=[], max_tokens=1
    )
    plan = OpenRouterProfile(api_key="").cache_plan_for(call)
    out = _openrouter_system_messages(plan)
    assert out == [{"role": "system", "content": "You are helpful."}]


def test_blocks_with_explicit_caching_emit_cache_control():
    # ADR-0060 §5: blocks carry only a `tier`; this strategy maps it to cache_control
    # + ttl (stable → 1h, volatile → 5m); a tier-less block gets no marker.
    plan = ANTHROPIC_BREAKPOINTS.plan(
        [
            {"text": "stable header", "tier": "stable"},
            {"text": "lore block", "tier": "volatile"},
            {"text": "no tier", "tier": None},
        ]
    )
    out = _openrouter_system_messages(plan)
    assert len(out) == 1
    msg = out[0]
    assert msg["role"] == "system"
    parts = msg["content"]
    assert isinstance(parts, list)
    assert len(parts) == 3
    assert parts[0] == {
        "type": "text",
        "text": "stable header",
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
    assert parts[1] == {
        "type": "text",
        "text": "lore block",
        "cache_control": {"type": "ephemeral", "ttl": "5m"},
    }
    assert parts[2] == {"type": "text", "text": "no tier"}
    assert "cache_control" not in parts[2]


def test_blocks_with_auto_caching_collapse_to_string():
    # Auto-cache providers (OpenAI/DeepSeek/Grok) index on prefix bytes,
    # so cache_control markers would be wire bloat with no upside.
    plan = PREFIX_CACHE.plan(
        [
            {"text": "stable", "tier": "stable"},
            {"text": "volatile", "tier": "volatile"},
        ]
    )
    out = _openrouter_system_messages(plan)
    assert out == [{"role": "system", "content": "stable\n\nvolatile"}]


def test_blocks_with_none_caching_also_collapse():
    plan = NO_CACHE.plan([{"text": "stable", "tier": "stable"}])
    out = _openrouter_system_messages(plan)
    assert out == [{"role": "system", "content": "stable"}]


def test_explicit_blocks_drop_empty_text():
    plan = ANTHROPIC_BREAKPOINTS.plan(
        [
            {"text": "real", "tier": "stable"},
            {"text": "", "tier": "stable"},
        ]
    )
    out = _openrouter_system_messages(plan)
    parts = out[0]["content"]
    assert len(parts) == 1
    assert parts[0]["text"] == "real"


def test_explicit_all_empty_blocks_returns_empty_list():
    plan = ANTHROPIC_BREAKPOINTS.plan([{"text": "", "tier": "stable"}])
    out = _openrouter_system_messages(plan)
    assert out == []


def test_unknown_tier_gets_no_marker():
    plan = ANTHROPIC_BREAKPOINTS.plan([{"text": "x", "tier": "bogus"}])
    out = _openrouter_system_messages(plan)
    parts = out[0]["content"]
    # A tier the adapter doesn't recognise isn't cached — no garbage to the API.
    assert "cache_control" not in parts[0]


def test_system_prompt_used_when_blocks_absent_auto():
    # No blocks → string path still works on a non-marker (auto/prefix-cache) route.
    call = ChatCall(
        model="openai/gpt-4.1",
        system_prompt="fallback string",
        messages=[],
        max_tokens=1,
    )
    plan = OpenRouterProfile(api_key="").cache_plan_for(call)
    out = _openrouter_system_messages(plan)
    assert out == [{"role": "system", "content": "fallback string"}]


def test_system_prompt_wrapped_and_marked_when_blocks_absent_on_explicit_route():
    # DEPARTURE from the pre-split pure-function test (ADR-0084 Slice 1, #1832):
    # the old `openrouter_system_messages(system_prompt, None, "explicit")` never
    # wrapped a bare prompt into a marker — only a non-empty `system_blocks` list
    # took the markers branch. `cache_plan_for` is now the ONE place that builds
    # a strategy's input (ADR-0084 §2), shared verbatim with the Anthropic native
    # profile, which already wrapped-and-marked a bare system prompt via
    # `anthropic_system_with_cache`. Unifying the two fixes a real inconsistency
    # between "the same effective strategy" on two transports; it does not change
    # production wire, because both live call sites (`chat.py`,
    # `system_prompt_cache_blocks`) already pre-wrap the prompt into
    # `system_blocks` before it reaches a profile — `system_blocks=None` here is
    # a synthetic case the profile has never received from the app in practice.
    call = ChatCall(
        model="anthropic/claude-sonnet-4-6",
        system_prompt="fallback string",
        messages=[],
        max_tokens=1,
    )
    plan = OpenRouterProfile(api_key="").cache_plan_for(call)
    out = _openrouter_system_messages(plan)
    assert out == [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "fallback string",
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }
            ],
        }
    ]


def test_all_empty_blocks_falls_back_to_system_prompt():
    # OpenRouter's fall-back to the bare prompt when every block is empty
    # (ADR-0084 §2) — built once in `cache_plan_for`, not re-implemented here.
    call = ChatCall(
        model="deepseek/deepseek-chat",
        system_prompt="P",
        system_blocks=[{"text": "", "tier": "stable"}],
        messages=[],
        max_tokens=1,
    )
    plan = OpenRouterProfile(api_key="").cache_plan_for(call)
    out = _openrouter_system_messages(plan)
    assert out == [{"role": "system", "content": "P"}]


# ---- Gemini wire test (ADR-0084 Slice 2, #1834) ----------------------------


def _gemini_system_blocks():
    return [
        {"text": "S", "tier": "stable"},
        {"text": "STAGED", "tier": "stable"},
        {"text": "LORE", "tier": "stable"},
        {"text": "VOL", "tier": "volatile"},
    ]


def test_gemini_route_gets_exactly_one_marker_on_last_stable_block():
    call = ChatCall(
        model="google/gemini-2.5-pro",
        system_prompt="S",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1,
        system_blocks=_gemini_system_blocks(),
    )
    messages = OpenRouterProfile(api_key="")._build_messages(call)
    parts = messages[0]["content"]
    assert len(parts) == 4
    marked = [p for p in parts if "cache_control" in p]
    assert len(marked) == 1
    part = marked[0]
    assert part["text"] == "LORE"
    assert part["cache_control"] == {"type": "ephemeral"}
    assert "ttl" not in part["cache_control"]


def test_anthropic_route_still_gets_four_markers_with_ttl():
    call = ChatCall(
        model="anthropic/claude-sonnet-4-6",
        system_prompt="S",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1,
        system_blocks=_gemini_system_blocks(),
    )
    messages = OpenRouterProfile(api_key="")._build_messages(call)
    parts = messages[0]["content"]
    assert len(parts) == 4
    marked = [p for p in parts if "cache_control" in p]
    assert len(marked) == 4
    assert all("ttl" in p["cache_control"] for p in marked)


# ---- _openrouter_extra_body (session_id) ----------------------------------


def test_extra_body_no_session_returns_empty():
    assert _openrouter_extra_body(None) == {}
    assert _openrouter_extra_body("") == {}


def test_extra_body_session_id_passes_through():
    out = _openrouter_extra_body("chat_abc123")
    assert out == {"session_id": "chat_abc123"}
