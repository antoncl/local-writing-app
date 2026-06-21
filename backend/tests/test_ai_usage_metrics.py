"""UsageMetrics + compute_cost + default_token_count + per-provider
count_tokens / extract_usage. Covers the V2 cost-surfacing foundation.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.profiles import (
    CapabilityTier,
    ModelDescriptor,
    UsageMetrics,
    compute_cost,
    default_token_count,
)
from app.services.ai.profiles.anthropic import AnthropicProfile
from app.services.ai.profiles.ollama import OllamaProfile
from app.services.ai.profiles.openai import OpenAIProfile
from app.services.ai.profiles.openrouter import OpenRouterProfile


# --- UsageMetrics + compute_cost ---------------------------------------


def test_usage_metrics_defaults_to_zeros():
    u = UsageMetrics()
    assert u.input_tokens == 0
    assert u.cached_input_tokens == 0
    assert u.cache_write_tokens == 0
    assert u.output_tokens == 0


def _desc(*, cost_in=None, cost_out=None, cache_read_mult=None) -> ModelDescriptor:
    return ModelDescriptor(
        id="test-model",
        display_name="Test",
        provider="test",
        context_window=100_000,
        tier=CapabilityTier.BALANCED,
        cost_in_per_mtok=cost_in,
        cost_out_per_mtok=cost_out,
        cache_read_multiplier=cache_read_mult,
    )


def test_compute_cost_returns_zero_when_pricing_absent():
    # Ollama-shaped descriptor: no prices known.
    usage = UsageMetrics(input_tokens=1000, output_tokens=500)
    assert compute_cost(usage, _desc()) == 0.0


def test_compute_cost_basic_input_output():
    # $3/Mtok in, $15/Mtok out — Sonnet-class pricing.
    desc = _desc(cost_in=3.0, cost_out=15.0)
    usage = UsageMetrics(input_tokens=1_000_000, output_tokens=1_000_000)
    assert compute_cost(usage, desc) == pytest.approx(18.0)


def test_compute_cost_applies_cache_read_multiplier():
    # 1M cached input @ 0.1x multiplier (Gemini-style) → $0.30, not $3.00
    desc = _desc(cost_in=3.0, cost_out=15.0, cache_read_mult=0.1)
    usage = UsageMetrics(cached_input_tokens=1_000_000)
    assert compute_cost(usage, desc) == pytest.approx(0.3)


def test_compute_cost_defaults_cache_mult_to_one_when_unset():
    # No cache_read_multiplier on descriptor → cached tokens cost the
    # same as fresh input. Safe over-estimate; descriptor SHOULD set it.
    desc = _desc(cost_in=3.0, cost_out=15.0)
    usage = UsageMetrics(cached_input_tokens=1_000_000)
    assert compute_cost(usage, desc) == pytest.approx(3.0)


def test_compute_cost_applies_cache_write_premium():
    # Cache writes are billed at 1.25x input rate (Anthropic 5min TTL).
    desc = _desc(cost_in=3.0, cost_out=15.0, cache_read_mult=0.25)
    usage = UsageMetrics(cache_write_tokens=1_000_000)
    assert compute_cost(usage, desc) == pytest.approx(3.75)


def test_compute_cost_combines_all_token_slots():
    # Anthropic-style: 100 fresh + 1000 cache-read + 50 cache-write + 200 out
    # cost = 100*3e-6 + 1000*3e-6*0.25 + 50*3e-6*1.25 + 200*15e-6
    #      = 0.0003 + 0.00075 + 0.0001875 + 0.003 = 0.0042375
    desc = _desc(cost_in=3.0, cost_out=15.0, cache_read_mult=0.25)
    usage = UsageMetrics(
        input_tokens=100,
        cached_input_tokens=1000,
        cache_write_tokens=50,
        output_tokens=200,
    )
    assert compute_cost(usage, desc) == pytest.approx(0.0042375)


# --- default_token_count -----------------------------------------------


def test_default_token_count_empty_string_is_zero():
    assert default_token_count("") == 0


def test_default_token_count_positive_for_normal_text():
    # We don't pin an exact value — tokenizer choice can vary. Just
    # check it's roughly proportional to text length.
    short = default_token_count("hello world")
    longer = default_token_count("hello world " * 100)
    assert short > 0
    assert longer > short * 50  # roughly 100x more tokens


# --- per-provider count_tokens (smoke) ---------------------------------


def test_all_profiles_count_tokens_returns_positive_int():
    text = "The quick brown fox jumps over the lazy dog."
    profiles = [
        AnthropicProfile(api_key=""),
        OpenAIProfile(api_key=""),
        OpenRouterProfile(api_key=""),
        OllamaProfile(host="http://localhost:11434"),
    ]
    for profile in profiles:
        n = profile.count_tokens(text, "any-model-id")
        assert isinstance(n, int)
        assert n > 0


# --- Anthropic extract_usage -------------------------------------------


def test_anthropic_extract_usage_full_shape():
    profile = AnthropicProfile(api_key="")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=120,
            cache_creation_input_tokens=45,
            cache_read_input_tokens=8000,
            output_tokens=300,
        )
    )
    usage = profile.extract_usage(response, "claude-sonnet-4-6")
    assert usage.input_tokens == 120
    assert usage.cache_write_tokens == 45
    assert usage.cached_input_tokens == 8000
    assert usage.output_tokens == 300


def test_anthropic_extract_usage_missing_cache_fields():
    # No caching this call — cache_* fields just don't appear.
    profile = AnthropicProfile(api_key="")
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=120, output_tokens=300)
    )
    usage = profile.extract_usage(response, "claude-sonnet-4-6")
    assert usage.input_tokens == 120
    assert usage.cached_input_tokens == 0
    assert usage.cache_write_tokens == 0
    assert usage.output_tokens == 300


def test_anthropic_extract_usage_no_usage_attribute():
    profile = AnthropicProfile(api_key="")
    usage = profile.extract_usage(SimpleNamespace(), "claude-sonnet-4-6")
    assert usage == UsageMetrics()


# --- OpenAI extract_usage ----------------------------------------------


def test_openai_extract_usage_with_cached_subfield():
    # OpenAI's prompt_tokens INCLUDES cached_tokens; we subtract.
    profile = OpenAIProfile(api_key="")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10_000,
            completion_tokens=500,
            prompt_tokens_details=SimpleNamespace(cached_tokens=8000),
        )
    )
    usage = profile.extract_usage(response, "gpt-4o")
    assert usage.input_tokens == 2000  # 10000 - 8000
    assert usage.cached_input_tokens == 8000
    assert usage.cache_write_tokens == 0
    assert usage.output_tokens == 500


def test_openai_extract_usage_without_cache_details():
    profile = OpenAIProfile(api_key="")
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=200)
    )
    usage = profile.extract_usage(response, "gpt-4o")
    assert usage.input_tokens == 500
    assert usage.cached_input_tokens == 0
    assert usage.output_tokens == 200


# --- OpenRouter extract_usage ------------------------------------------


def test_openrouter_extract_usage_anthropic_route_shape():
    # Anthropic via OpenRouter exposes the Anthropic-style split. The
    # cache_read / cache_write fields override the OpenAI-style cached
    # subfield.
    profile = OpenRouterProfile(api_key="")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10_000,
            completion_tokens=500,
            cache_read_input_tokens=8000,
            cache_creation_input_tokens=200,
        )
    )
    usage = profile.extract_usage(response, "anthropic/claude-sonnet-4")
    assert usage.input_tokens == 1800  # 10000 - 8000 - 200
    assert usage.cached_input_tokens == 8000
    assert usage.cache_write_tokens == 200
    assert usage.output_tokens == 500


def test_openrouter_extract_usage_openai_route_shape():
    # OpenAI-style fallback path: only prompt_tokens_details.cached_tokens.
    profile = OpenRouterProfile(api_key="")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10_000,
            completion_tokens=500,
            prompt_tokens_details=SimpleNamespace(cached_tokens=8000),
        )
    )
    usage = profile.extract_usage(response, "openai/gpt-4o")
    assert usage.input_tokens == 2000
    assert usage.cached_input_tokens == 8000
    assert usage.cache_write_tokens == 0
    assert usage.output_tokens == 500


def test_openrouter_extract_usage_plain_route():
    # No caching info at all — just prompt + completion.
    profile = OpenRouterProfile(api_key="")
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=200)
    )
    usage = profile.extract_usage(response, "deepseek/deepseek-chat")
    assert usage.input_tokens == 500
    assert usage.cached_input_tokens == 0
    assert usage.output_tokens == 200


# --- Ollama extract_usage ----------------------------------------------


def test_ollama_extract_usage_openai_compat_shape():
    # /v1/chat/completions shim returns OpenAI-style usage.
    profile = OllamaProfile(host="http://localhost:11434")
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=300)
    )
    usage = profile.extract_usage(response, "llama3.2")
    assert usage.input_tokens == 120
    assert usage.output_tokens == 300
    assert usage.cached_input_tokens == 0


def test_ollama_extract_usage_native_dict_shape():
    profile = OllamaProfile(host="http://localhost:11434")
    response = {"prompt_eval_count": 120, "eval_count": 300}
    usage = profile.extract_usage(response, "llama3.2")
    assert usage.input_tokens == 120
    assert usage.output_tokens == 300


def test_ollama_extract_usage_unknown_shape_returns_zeros():
    profile = OllamaProfile(host="http://localhost:11434")
    assert profile.extract_usage("garbage", "llama3.2") == UsageMetrics()
