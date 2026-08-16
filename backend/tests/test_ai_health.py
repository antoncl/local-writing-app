"""health_check resolves the provider profile and pings it with a 1-token
call. Covers the validation/error paths and the happy path per provider
family. Added with the ADR-0058 S4a reshape (health_check moved onto the
provider classes) — this path had no prior coverage.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import app.services.machine_settings as ms
from app.services.ai.providers import health_check


def _settings(**keys: str) -> ms.MachineSettings:
    return ms.MachineSettings(
        providers=ms.ProviderCredentials(
            anthropic_api_key=keys.get("anthropic", "sk-ant-test"),
            openai_api_key=keys.get("openai", "sk-openai-test"),
            openrouter_api_key=keys.get("openrouter", "sk-or-test"),
            ollama_host=keys.get("ollama_host", "http://127.0.0.1:11434"),
        )
    )


class _FakeAnthropic:
    def __init__(self, **_kwargs) -> None:
        self.messages = SimpleNamespace(create=lambda **_k: SimpleNamespace())


def test_health_ok_for_anthropic():
    with patch("anthropic.Anthropic", _FakeAnthropic):
        res = health_check(
            provider_name="anthropic",
            model="claude-sonnet-4-6",
            settings=_settings(),
            policy="cloud-allowed",
        )
    assert res.ok
    assert res.error is None
    assert res.provider == "anthropic"


def test_health_ok_for_ollama_pings_openai_compat_endpoint():
    captured: dict = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_k: SimpleNamespace())
            )

    with patch("openai.OpenAI", _FakeOpenAI):
        res = health_check(
            provider_name="ollama",
            model="llama3.2",
            settings=_settings(),
            policy="cloud-allowed",
        )
    assert res.ok
    # Health ping hits the OpenAI-compatible shim at host/v1 with the
    # placeholder key — no real credential required for local Ollama.
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["api_key"] == "ollama"


def test_health_reports_missing_key():
    res = health_check(
        provider_name="anthropic",
        model="claude-sonnet-4-6",
        settings=_settings(anthropic=""),
        policy="cloud-allowed",
    )
    assert not res.ok
    assert "not configured" in res.error


def test_health_flags_mispasted_key():
    # An OpenRouter key in the OpenAI slot is rejected before any provider call.
    res = health_check(
        provider_name="openai",
        model="gpt-4o",
        settings=_settings(openai="sk-or-wrongslot"),
        policy="cloud-allowed",
    )
    assert not res.ok
    assert "appears to contain" in res.error


def test_health_rejects_unknown_provider():
    res = health_check(
        provider_name="nope",
        model="x",
        settings=_settings(),
        policy="cloud-allowed",
    )
    assert not res.ok
    assert "Unknown provider" in res.error


def test_health_blocked_by_policy_off():
    res = health_check(
        provider_name="anthropic",
        model="claude-sonnet-4-6",
        settings=_settings(),
        policy="off",
    )
    assert not res.ok
    assert "disabled" in res.error


def test_health_requires_model():
    res = health_check(
        provider_name="anthropic",
        model="",
        settings=_settings(),
        policy="cloud-allowed",
    )
    assert not res.ok
    assert "No model" in res.error
