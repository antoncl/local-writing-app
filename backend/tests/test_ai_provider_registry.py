"""Registry + `from_settings`: the single registration point (ADR-0058).

`profile_for` resolves each provider through the `{name → class}` table and
each subclass's `from_settings` reads its own credential slot. These are the
oracle for the S1 reshape — a dropped table entry or a mis-wired slot fails
here, not silently at call time.
"""

from __future__ import annotations

import pytest

import app.services.machine_settings as ms
from app.services.ai.profiles.anthropic import AnthropicProfile
from app.services.ai.profiles.ollama import OllamaProfile
from app.services.ai.profiles.openai import OpenAIProfile
from app.services.ai.profiles.openrouter import OpenRouterProfile
from app.services.ai.profiles.registry import known_provider_names, profile_for


def _settings() -> ms.MachineSettings:
    return ms.MachineSettings(
        providers=ms.ProviderCredentials(
            anthropic_api_key="sk-ant",
            openai_api_key="sk-oai",
            openrouter_api_key="sk-or",
            ollama_host="http://box:11434",
        )
    )


def test_known_provider_names_are_the_registered_four():
    assert known_provider_names() == ["anthropic", "ollama", "openai", "openrouter"]


def test_profile_for_resolves_each_provider_to_its_class():
    settings = _settings()
    assert isinstance(profile_for("anthropic", settings), AnthropicProfile)
    assert isinstance(profile_for("openai", settings), OpenAIProfile)
    assert isinstance(profile_for("openrouter", settings), OpenRouterProfile)
    assert isinstance(profile_for("ollama", settings), OllamaProfile)


def test_profile_for_reads_each_providers_own_credential_slot():
    settings = _settings()
    # A mis-wired from_settings (e.g. anthropic reading the openai key)
    # fails here.
    assert profile_for("anthropic", settings)._api_key == "sk-ant"
    assert profile_for("openai", settings)._api_key == "sk-oai"
    assert profile_for("openrouter", settings)._api_key == "sk-or"
    assert profile_for("ollama", settings)._base == "http://box:11434"


def test_profile_for_raises_on_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        profile_for("nope", _settings())


def test_ollama_from_settings_falls_back_to_default_host_when_empty():
    settings = ms.MachineSettings(providers=ms.ProviderCredentials(ollama_host=""))
    assert profile_for("ollama", settings)._base == "http://127.0.0.1:11434"
