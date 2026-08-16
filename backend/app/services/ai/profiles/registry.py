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

# The one place a provider is registered. Adding a provider = write the
# `ProviderProfile` subclass (with its `from_settings`) and add one line
# here; removing a vendor that shut down = delete both. The name is the
# authoritative `.name` on the class, so there is no second list to keep
# in sync (ADR-0058).
_REGISTRY: dict[str, type[ProviderProfile]] = {
    AnthropicProfile.name: AnthropicProfile,
    OpenAIProfile.name: OpenAIProfile,
    OpenRouterProfile.name: OpenRouterProfile,
    OllamaProfile.name: OllamaProfile,
}


def known_provider_names() -> list[str]:
    return sorted(_REGISTRY)


def recognizing_provider(api_key: str) -> str | None:
    """Name of the provider whose key signature most specifically matches
    `api_key`, or None if none does.

    Each provider declares its own `key_prefixes`; the longest matching
    prefix wins, so a specific sub-prefix (`sk-ant-`) beats a looser one
    (`sk-`). The dispatch layer uses this to tell a user they pasted one
    provider's key into another provider's field.
    """
    key = api_key.strip()
    best_name: str | None = None
    best_len = 0
    for provider_name, profile_cls in _REGISTRY.items():
        for prefix in profile_cls.key_prefixes:
            if key.startswith(prefix) and len(prefix) > best_len:
                best_name = provider_name
                best_len = len(prefix)
    return best_name


def profile_for(provider: str, settings: MachineSettings) -> ProviderProfile:
    """Construct a fresh profile for the given provider name.

    Returns a new instance each call — callers that want caching should
    hold the reference. The profile's `_cache` field is per-instance.
    Each subclass's `from_settings` reads its own credential slot, so this
    resolves polymorphically rather than branching per provider.
    """

    try:
        profile_cls = _REGISTRY[provider]
    except KeyError:
        raise ValueError(f"Unknown provider: {provider}") from None
    return profile_cls.from_settings(settings)


def capability_profile_for(provider: str) -> ProviderProfile | None:
    """A credential-less profile for capability queries — `requires_temperature`,
    `supports_temperature`, caching style — that need no API key and must not
    raise on an unknown provider (they run on user-supplied metadata).

    Delegates to `profile_for` with default settings, whose provider credentials
    are empty, so there is one provider→profile constructor rather than two.
    Returns `None` on an unknown provider, where `profile_for` raises.
    """
    try:
        return profile_for(provider, MachineSettings())
    except ValueError:
        return None
