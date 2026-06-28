"""OpenRouter dispatch path — system message construction and session
stickiness. We can't call the live API in tests, so we pin the pure
body-builder functions instead. If OpenRouter's caching protocol
changes (or a routed-to provider's caching_style changes), these
red-line clearly.
"""

from __future__ import annotations

from app.services.ai.profiles.openrouter import caching_style_for_model
from app.services.ai.providers import (
    _openrouter_extra_body,
    _openrouter_system_messages,
)

# ---- caching_style_for_model (prefix lookup) ------------------------------


def test_caching_style_anthropic_is_explicit():
    assert caching_style_for_model("anthropic/claude-sonnet-4-6") == "explicit"


def test_caching_style_google_is_explicit():
    # Gemini 2.5 routes need explicit breakpoints per the OpenRouter doc.
    assert caching_style_for_model("google/gemini-2.5-flash") == "explicit"


def test_caching_style_openai_is_auto():
    assert caching_style_for_model("openai/gpt-4.1") == "auto"


def test_caching_style_unknown_prefix_is_none():
    assert caching_style_for_model("unknown/some-model") == "none"


def test_caching_style_empty_id_is_none():
    assert caching_style_for_model("") == "none"


# ---- _openrouter_system_messages (the meaty part) -------------------------


def test_no_system_returns_empty_list():
    assert _openrouter_system_messages("", None, "explicit") == []
    assert _openrouter_system_messages("", [], "explicit") == []


def test_plain_string_system_yields_string_content():
    out = _openrouter_system_messages("You are helpful.", None, "auto")
    assert out == [{"role": "system", "content": "You are helpful."}]


def test_blocks_with_explicit_caching_emit_cache_control():
    out = _openrouter_system_messages(
        "",
        [
            {"text": "stable header", "cache_break_after": True, "ttl": "1h"},
            {"text": "lore block", "cache_break_after": True},
            {"text": "volatile tail", "cache_break_after": False},
        ],
        "explicit",
    )
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
        "cache_control": {"type": "ephemeral"},
    }
    assert parts[2] == {"type": "text", "text": "volatile tail"}
    assert "cache_control" not in parts[2]


def test_blocks_with_auto_caching_collapse_to_string():
    # Auto-cache providers (OpenAI/DeepSeek/Grok) index on prefix bytes,
    # so cache_control markers would be wire bloat with no upside.
    out = _openrouter_system_messages(
        "",
        [
            {"text": "stable", "cache_break_after": True},
            {"text": "volatile", "cache_break_after": False},
        ],
        "auto",
    )
    assert out == [{"role": "system", "content": "stable\n\nvolatile"}]


def test_blocks_with_none_caching_also_collapse():
    out = _openrouter_system_messages(
        "",
        [{"text": "stable", "cache_break_after": True}],
        "none",
    )
    assert out == [{"role": "system", "content": "stable"}]


def test_explicit_blocks_drop_empty_text():
    out = _openrouter_system_messages(
        "",
        [
            {"text": "real", "cache_break_after": True},
            {"text": "", "cache_break_after": True},
        ],
        "explicit",
    )
    parts = out[0]["content"]
    assert len(parts) == 1
    assert parts[0]["text"] == "real"


def test_explicit_all_empty_blocks_returns_empty_list():
    out = _openrouter_system_messages(
        "",
        [{"text": "", "cache_break_after": True}],
        "explicit",
    )
    assert out == []


def test_unknown_ttl_drops_ttl_keeps_marker():
    out = _openrouter_system_messages(
        "",
        [{"text": "x", "cache_break_after": True, "ttl": "bogus"}],
        "explicit",
    )
    parts = out[0]["content"]
    # Unknown ttl silently dropped — we don't pass garbage to the API.
    assert parts[0]["cache_control"] == {"type": "ephemeral"}


def test_system_prompt_used_when_blocks_absent_explicit():
    # No blocks → string path still works even with explicit caching style.
    out = _openrouter_system_messages(
        "fallback string", None, "explicit"
    )
    assert out == [{"role": "system", "content": "fallback string"}]


# ---- _openrouter_extra_body (session_id) ----------------------------------


def test_extra_body_no_session_returns_empty():
    assert _openrouter_extra_body(None) == {}
    assert _openrouter_extra_body("") == {}


def test_extra_body_session_id_passes_through():
    out = _openrouter_extra_body("chat_abc123")
    assert out == {"session_id": "chat_abc123"}
