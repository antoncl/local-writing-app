"""The Anthropic dispatch helper wraps the system prompt as a cacheable
content block so prompt caching kicks in. This test pins the SDK-shape
contract; if Anthropic changes their caching markup spec we want a red
test, not silent regression.
"""

from __future__ import annotations

from app.services.ai.providers import _anthropic_system_with_cache


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
    # Anthropic accepts a single block or many; we use one block per the
    # design (system is the single largest stable payload). Future v2
    # may add additional cacheable blocks for static user content.
    out = _anthropic_system_with_cache("Large stable preamble")
    assert isinstance(out, list)
    assert len(out) == 1
