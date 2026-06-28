"""Registry: provider name → `ProviderProfile` instance.

Profiles are constructed lazily on first access using credentials from
machine settings. A profile's internal cache stays alive for the process
lifetime; `force_refresh=True` on `list_models()` bypasses it.
"""

from __future__ import annotations

from app.services.ai.profiles.anthropic import AnthropicProfile
from app.services.ai.profiles.base import ProviderProfile
from app.services.ai.profiles.ollama import OllamaProfile
from app.services.ai.profiles.openai import OpenAIProfile
from app.services.ai.profiles.openrouter import OpenRouterProfile
from app.services.machine_settings import MachineSettings

_KNOWN = {"anthropic", "openai", "openrouter", "ollama"}


def known_provider_names() -> list[str]:
    return sorted(_KNOWN)


def profile_for(provider: str, settings: MachineSettings) -> ProviderProfile:
    """Construct a fresh profile for the given provider name.

    Returns a new instance each call — callers that want caching should
    hold the reference. The profile's `_cache` field is per-instance.
    """

    providers = settings.providers
    if provider == "anthropic":
        return AnthropicProfile(api_key=providers.anthropic_api_key or "")
    if provider == "openai":
        return OpenAIProfile(api_key=providers.openai_api_key or "")
    if provider == "openrouter":
        return OpenRouterProfile(api_key=providers.openrouter_api_key or "")
    if provider == "ollama":
        return OllamaProfile(host=providers.ollama_host or "http://127.0.0.1:11434")
    raise ValueError(f"Unknown provider: {provider}")
