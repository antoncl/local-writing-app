"""The Anthropic dispatch helper wraps the system prompt as a cacheable
content block so prompt caching kicks in. This test pins the SDK-shape
contract; if Anthropic changes their caching markup spec we want a red
test, not silent regression.
"""

from __future__ import annotations

from app.services.ai.providers import (
    _anthropic_system_blocks,
    _anthropic_system_with_cache,
)


# ---- legacy single-string helper (back-compat) ---------------------------


def test_empty_system_is_unchanged():
    # Empty prompt stays empty so callers can skip the `system` kwarg.
    assert _anthropic_system_with_cache("") == ""


def test_nonempty_system_becomes_cacheable_block():
    out = _anthropic_system_with_cache("You are a helpful assistant.")
    assert out == [
        {
            "type": "text",
            "text": "You are a helpful assistant.",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_system_block_is_list_of_one():
    out = _anthropic_system_with_cache("Large stable preamble")
    assert isinstance(out, list)
    assert len(out) == 1


# ---- multi-block builder (implicit-context cache layering) ---------------


def test_blocks_empty_list_returns_empty_string():
    assert _anthropic_system_blocks([]) == ""


def test_blocks_drops_empty_text_entries():
    out = _anthropic_system_blocks(
        [
            {"text": "real", "cache_break_after": True},
            {"text": "", "cache_break_after": True},
        ]
    )
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["text"] == "real"


def test_blocks_emit_cache_control_only_where_marked():
    # First two blocks are stable (markers wanted); third is volatile.
    out = _anthropic_system_blocks(
        [
            {"text": "system header", "cache_break_after": True},
            {"text": "lore block", "cache_break_after": True},
            {"text": "volatile tail", "cache_break_after": False},
        ]
    )
    assert len(out) == 3
    assert out[0]["cache_control"] == {"type": "ephemeral"}
    assert out[1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in out[2]


def test_blocks_propagate_ttl():
    out = _anthropic_system_blocks(
        [
            {"text": "stable canon", "cache_break_after": True, "ttl": "1h"},
            {"text": "session journal", "cache_break_after": True, "ttl": "5m"},
            {"text": "no-ttl-default", "cache_break_after": True},
        ]
    )
    assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert out[1]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    # No explicit ttl → SDK's own default applies (Anthropic uses 5m); we
    # don't add the key so we don't lock to a specific default.
    assert out[2]["cache_control"] == {"type": "ephemeral"}


def test_blocks_ignore_unknown_ttl():
    out = _anthropic_system_blocks(
        [{"text": "x", "cache_break_after": True, "ttl": "bogus"}]
    )
    # Unknown ttl is silently dropped; we don't pass garbage to the SDK.
    assert out[0]["cache_control"] == {"type": "ephemeral"}


def test_legacy_helper_uses_blocks_builder():
    # The legacy helper should produce the same SDK shape as a single
    # cache-marked block via the new builder — proves the back-compat
    # wrapper is faithful and won't silently diverge.
    legacy = _anthropic_system_with_cache("hello")
    multi = _anthropic_system_blocks([{"text": "hello", "cache_break_after": True}])
    assert legacy == multi
