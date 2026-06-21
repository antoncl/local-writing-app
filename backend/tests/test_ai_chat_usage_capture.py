"""Step 4 of V2: ChatResult.usage is populated from the provider's
response via the matching ProviderProfile's extract_usage. Tests cover
each of the four providers + the failure path (usage stays None on
error)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services import machine_settings as ms
from app.services.ai import providers as ai_providers
from app.services.ai.providers import _extract_usage_for_provider


def _settings(**keys: str) -> ms.MachineSettings:
    return ms.MachineSettings(
        providers=ms.ProviderCredentials(
            anthropic_api_key=keys.get("anthropic", "sk-ant-test"),
            openai_api_key=keys.get("openai", "sk-openai-test"),
            openrouter_api_key=keys.get("openrouter", "or-test"),
            ollama_host=keys.get("ollama_host", "http://127.0.0.1:11434"),
        ),
        default_provider=keys.get("default_provider", "anthropic"),
    )


def _anthropic_response_with_usage(
    *, input_tokens=120, cache_read=8000, cache_write=45, output_tokens=300
) -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
            output_tokens=output_tokens,
        )
    )


def _openai_response_with_usage(
    *, prompt_tokens=10_000, cached=8000, completion_tokens=500
) -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        )
    )


# --- chat() with anthropic populates usage from raw response ----------


def test_chat_anthropic_captures_usage_into_result():
    raw = _anthropic_response_with_usage()
    with patch(
        "app.services.ai.providers._anthropic_chat",
        return_value=("Hello.", "end_turn", raw),
    ):
        result = ai_providers.chat(
            provider_name="anthropic",
            model="claude-sonnet-4-6",
            system_prompt="You are X.",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=512,
            settings=_settings(),
            policy="allow-all",
        )
    assert result.ok
    assert result.usage is not None
    assert result.usage.input_tokens == 120
    assert result.usage.cached_input_tokens == 8000
    assert result.usage.cache_write_tokens == 45
    assert result.usage.output_tokens == 300


def test_chat_openai_captures_usage_into_result():
    raw = _openai_response_with_usage()
    with patch(
        "app.services.ai.providers._openai_compatible_chat",
        return_value=("Hello.", "stop", raw),
    ):
        result = ai_providers.chat(
            provider_name="openai",
            model="gpt-4o",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=512,
            settings=_settings(),
            policy="allow-all",
        )
    assert result.ok
    assert result.usage is not None
    # OpenAI's prompt_tokens INCLUDES cached → fresh = prompt - cached
    assert result.usage.input_tokens == 2000
    assert result.usage.cached_input_tokens == 8000
    assert result.usage.output_tokens == 500


def test_chat_openrouter_captures_usage_anthropic_style_split():
    # OpenRouter Anthropic route — extract_usage prefers the
    # cache_creation/read fields over the OpenAI-style cached subfield.
    raw = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10_000,
            completion_tokens=500,
            cache_read_input_tokens=8000,
            cache_creation_input_tokens=200,
        )
    )
    with patch(
        "app.services.ai.providers._openrouter_chat",
        return_value=("Hello.", "stop", raw),
    ):
        result = ai_providers.chat(
            provider_name="openrouter",
            model="anthropic/claude-sonnet-4",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=512,
            settings=_settings(),
            policy="allow-all",
        )
    assert result.ok
    assert result.usage is not None
    assert result.usage.cached_input_tokens == 8000
    assert result.usage.cache_write_tokens == 200
    # prompt_tokens - cache_read - cache_write = 10000 - 8000 - 200 = 1800
    assert result.usage.input_tokens == 1800
    assert result.usage.output_tokens == 500


def test_chat_ollama_captures_usage_from_openai_compat_response():
    raw = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=300)
    )
    with patch(
        "app.services.ai.providers._openai_compatible_chat",
        return_value=("Hello.", "stop", raw),
    ):
        result = ai_providers.chat(
            provider_name="ollama",
            model="llama3.2",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=512,
            settings=_settings(),
            policy="allow-all",
        )
    assert result.ok
    assert result.usage is not None
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 300
    assert result.usage.cached_input_tokens == 0


# --- Failure paths leave usage as None --------------------------------


def test_chat_provider_error_leaves_usage_none():
    # Provider error path returns ChatResult with ok=False and never
    # touches the usage field — it stays at the dataclass default (None).
    with patch(
        "app.services.ai.providers._anthropic_chat",
        side_effect=ai_providers._ProviderError("simulated"),
    ):
        result = ai_providers.chat(
            provider_name="anthropic",
            model="claude-sonnet-4-6",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=512,
            settings=_settings(),
            policy="allow-all",
        )
    assert not result.ok
    assert result.usage is None


# --- _extract_usage_for_provider tolerates bad input -----------------


def test_extract_usage_returns_none_for_unknown_provider():
    assert _extract_usage_for_provider("nope", SimpleNamespace(), "x") is None


def test_extract_usage_returns_empty_metrics_for_response_without_usage():
    # No `usage` attribute on response → extract returns UsageMetrics() with
    # all zeros (provider's extract_usage handles this gracefully).
    metrics = _extract_usage_for_provider("anthropic", SimpleNamespace(), "x")
    assert metrics is not None
    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
