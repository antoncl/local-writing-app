"""Tests for the token-estimator facade at services/ai/tokens.py.

These cover the (provider, model) → counter resolution + the
descriptor lookup + the input-cost estimate. They do NOT hit real
provider endpoints; descriptor lookups exercise either bake-in
catalogues (which return synchronously) or are monkeypatched.
"""

from __future__ import annotations

import asyncio

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


def test_estimate_input_cost_none_descriptor_returns_zero():
    assert token_service.estimate_input_cost(10_000, None) == 0.0


def test_estimate_input_cost_no_pricing_returns_zero():
    # Ollama descriptors lack cost_in_per_mtok → no estimate possible.
    assert token_service.estimate_input_cost(10_000, _desc(None)) == 0.0


def test_estimate_input_cost_zero_tokens_returns_zero():
    assert token_service.estimate_input_cost(0, _desc(3.0)) == 0.0


def test_estimate_input_cost_negative_tokens_returns_zero():
    # Sanity-check the boundary — callers shouldn't pass negatives,
    # but if they do we want 0 not a negative cost.
    assert token_service.estimate_input_cost(-5, _desc(3.0)) == 0.0


def test_estimate_input_cost_basic():
    # 1M tokens at $3/Mtok → $3.
    assert token_service.estimate_input_cost(1_000_000, _desc(3.0)) == 3.0


def test_estimate_input_cost_small_amount():
    # 1500 tokens at $3/Mtok → $0.0045
    cost = token_service.estimate_input_cost(1500, _desc(3.0))
    assert abs(cost - 0.0045) < 1e-9
