"""Tests for the token-estimator facade at services/ai/tokens.py.

These cover the (provider, model) → counter resolution + the
descriptor lookup + the input-cost estimate. They do NOT hit real
provider endpoints; descriptor lookups exercise either bake-in
catalogues (which return synchronously) or are monkeypatched.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import machine_settings as ms
from app.services.ai import tokens as token_service
from app.services.ai.profiles import CapabilityTier, ModelDescriptor


def _settings() -> ms.MachineSettings:
    # No real keys — list_models falls back to bake-in for cloud profiles.
    return ms.MachineSettings(
        providers=ms.ProviderCredentials(
            anthropic_api_key="",
            openai_api_key="",
            openrouter_api_key="",
            ollama_host="http://127.0.0.1:11434",
        ),
        default_provider="anthropic",
    )


# --- count_tokens ------------------------------------------------------


def test_count_tokens_empty_text_is_zero():
    assert token_service.count_tokens(
        "", provider="anthropic", model="claude-sonnet-4-6", settings=_settings()
    ) == 0


def test_count_tokens_blank_provider_is_zero():
    assert token_service.count_tokens(
        "hello", provider="", model="claude-sonnet-4-6", settings=_settings()
    ) == 0


def test_count_tokens_unknown_provider_is_zero():
    assert token_service.count_tokens(
        "hello", provider="fakeprovider", model="x", settings=_settings()
    ) == 0


def test_count_tokens_returns_positive_for_normal_text():
    n = token_service.count_tokens(
        "The quick brown fox jumps over the lazy dog.",
        provider="anthropic",
        model="claude-sonnet-4-6",
        settings=_settings(),
    )
    assert n > 0


def test_count_tokens_consistent_across_providers_for_same_text():
    # All four providers currently delegate to default_token_count, so
    # the same text yields the same count. This is an invariant we WANT
    # — if a provider plugs in its own tokenizer later, the test will
    # need to relax (per-provider expectations).
    text = "hello world"
    settings = _settings()
    a = token_service.count_tokens(text, provider="anthropic", model="x", settings=settings)
    b = token_service.count_tokens(text, provider="openai", model="x", settings=settings)
    c = token_service.count_tokens(text, provider="openrouter", model="x", settings=settings)
    d = token_service.count_tokens(text, provider="ollama", model="x", settings=settings)
    assert a == b == c == d > 0


# --- count_tokens_per_block --------------------------------------------


def test_count_tokens_per_block_returns_one_count_per_block():
    blocks = ["alpha", "bravo charlie", "delta echo foxtrot"]
    counts = token_service.count_tokens_per_block(
        blocks, provider="anthropic", model="x", settings=_settings()
    )
    assert len(counts) == 3
    assert all(c > 0 for c in counts)
    # Longer block should produce more tokens.
    assert counts[2] > counts[0]


def test_count_tokens_per_block_handles_empty_strings():
    counts = token_service.count_tokens_per_block(
        ["", "hello", ""],
        provider="anthropic",
        model="x",
        settings=_settings(),
    )
    assert counts[0] == 0
    assert counts[2] == 0
    assert counts[1] > 0


def test_count_tokens_per_block_unknown_provider_returns_zeros():
    counts = token_service.count_tokens_per_block(
        ["a", "b", "c"], provider="bogus", model="x", settings=_settings()
    )
    assert counts == [0, 0, 0]


def test_count_tokens_per_block_blank_provider_returns_zeros():
    counts = token_service.count_tokens_per_block(
        ["a", "b"], provider="", model="x", settings=_settings()
    )
    assert counts == [0, 0]


# --- descriptor_for ----------------------------------------------------


def test_descriptor_for_known_anthropic_model():
    # No key → falls back to bake-in, which includes claude-sonnet-4-6.
    desc = asyncio.run(
        token_service.descriptor_for(
            provider="anthropic",
            model="claude-sonnet-4-6",
            settings=_settings(),
        )
    )
    assert desc is not None
    assert desc.id == "claude-sonnet-4-6"
    assert desc.cost_in_per_mtok is not None
    assert desc.cost_in_per_mtok > 0


def test_descriptor_for_unknown_model_is_none():
    desc = asyncio.run(
        token_service.descriptor_for(
            provider="anthropic",
            model="does-not-exist",
            settings=_settings(),
        )
    )
    assert desc is None


def test_descriptor_for_blank_provider_is_none():
    desc = asyncio.run(
        token_service.descriptor_for(provider="", model="x", settings=_settings())
    )
    assert desc is None


def test_descriptor_for_blank_model_is_none():
    desc = asyncio.run(
        token_service.descriptor_for(
            provider="anthropic", model="", settings=_settings()
        )
    )
    assert desc is None


def test_descriptor_for_unknown_provider_is_none():
    desc = asyncio.run(
        token_service.descriptor_for(
            provider="fakeprovider", model="x", settings=_settings()
        )
    )
    assert desc is None


# --- estimate_input_cost -----------------------------------------------


def _desc(cost_in: float | None) -> ModelDescriptor:
    return ModelDescriptor(
        id="t",
        display_name="T",
        provider="t",
        context_window=100_000,
        tier=CapabilityTier.BALANCED,
        cost_in_per_mtok=cost_in,
    )


def test_estimate_input_cost_none_descriptor_returns_none():
    # No descriptor → pricing UNKNOWN, not a confident zero (#697).
    assert token_service.estimate_input_cost(10_000, None) is None


def test_estimate_input_cost_no_pricing_returns_none():
    # Ollama descriptors lack cost_in_per_mtok → no estimate possible;
    # unknown, not 0.0 (the preview hides an unknown cost).
    assert token_service.estimate_input_cost(10_000, _desc(None)) is None


def test_estimate_input_cost_zero_tokens_returns_zero():
    assert token_service.estimate_input_cost(0, _desc(3.0)) == 0.0


def test_estimate_input_cost_negative_tokens_returns_zero():
    # Sanity-check the boundary — callers shouldn't pass negatives,
    # but if they do we want 0 not a negative cost.
    assert token_service.estimate_input_cost(-5, _desc(3.0)) == 0.0


def test_estimate_input_cost_basic():
    # 1M tokens at $3/Mtok → $3.
    assert token_service.estimate_input_cost(1_000_000, _desc(3.0)) == 3.0


# --- estimate_send_cost (cache-aware, #1052) ---------------------------


def _desc_cache(cost_in: float | None, read_mult: float | None) -> ModelDescriptor:
    return ModelDescriptor(
        id="t",
        display_name="T",
        provider="t",
        context_window=100_000,
        tier=CapabilityTier.BALANCED,
        cost_in_per_mtok=cost_in,
        cache_read_multiplier=read_mult,
    )


def test_estimate_send_cost_no_pricing_returns_none_pair():
    assert token_service.estimate_send_cost(1000, 1000, None, True) == (None, None)
    assert token_service.estimate_send_cost(1000, 1000, _desc(None), True) == (None, None)


def test_estimate_send_cost_non_caching_model_is_flat():
    # caches=False → the stable prefix is NOT discounted; settled == first == flat.
    settled, first = token_service.estimate_send_cost(1_000_000, 1_000_000, _desc(3.0), False)
    assert settled == first == 6.0


def test_estimate_send_cost_prices_the_stable_prefix_by_tier():
    # 1M stable + 1M other at $3/Mtok, read multiplier 0.1: the stable prefix is
    # a cache READ on a settled send (0.1×) and a WRITE on the first send (1.25×);
    # the other tokens are full rate in both.
    settled, first = token_service.estimate_send_cost(
        1_000_000, 1_000_000, _desc_cache(3.0, 0.1), True
    )
    assert settled == pytest.approx(3.0 * 0.1 + 3.0)  # read prefix + other
    assert first == pytest.approx(3.0 * 1.25 + 3.0)  # write prefix + other


def test_estimate_send_cost_read_mult_defaults_to_one():
    # A caching model with no cache_read_multiplier: reads are full rate, so only
    # the first-send write premium (1.25×) shows.
    settled, first = token_service.estimate_send_cost(
        1_000_000, 0, _desc_cache(3.0, None), True
    )
    assert settled == pytest.approx(3.0)
    assert first == pytest.approx(3.75)


def test_estimate_send_cost_no_stable_prefix_is_flat_even_when_caching():
    # An all-volatile send has nothing cacheable, so settled == first.
    settled, first = token_service.estimate_send_cost(
        0, 1_000_000, _desc_cache(3.0, 0.1), True
    )
    assert settled == first == pytest.approx(3.0)


def test_estimate_input_cost_small_amount():
    # 1500 tokens at $3/Mtok → $0.0045
    cost = token_service.estimate_input_cost(1500, _desc(3.0))
    assert abs(cost - 0.0045) < 1e-9
