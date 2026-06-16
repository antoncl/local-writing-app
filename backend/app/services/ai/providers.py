from __future__ import annotations

import time
from typing import Literal

from app.models import AIHealthResponse, AIPolicy
from app.services.machine_settings import MachineSettings


CLOUD_PROVIDERS = {"anthropic", "openai", "openrouter"}
LOCAL_PROVIDERS = {"ollama"}
KNOWN_PROVIDERS = CLOUD_PROVIDERS | LOCAL_PROVIDERS


def _policy_allows(policy: AIPolicy, provider: str) -> tuple[bool, str | None]:
    if policy == "off":
        return False, "AI is disabled for this project (policy: off)."
    if policy == "local-only" and provider in CLOUD_PROVIDERS:
        return False, f"Project policy is local-only; provider '{provider}' is a cloud provider."
    return True, None


def health_check(
    *,
    provider_name: str,
    model: str,
    settings: MachineSettings,
    policy: AIPolicy,
) -> AIHealthResponse:
    if not provider_name:
        return AIHealthResponse(
            provider="",
            model=model,
            ok=False,
            latency_ms=0,
            policy=policy,
            error="No provider specified and no default_provider configured.",
        )
    if provider_name not in KNOWN_PROVIDERS:
        return AIHealthResponse(
            provider=provider_name,
            model=model,
            ok=False,
            latency_ms=0,
            policy=policy,
            error=f"Unknown provider '{provider_name}'. Known: {sorted(KNOWN_PROVIDERS)}.",
        )

    allowed, reason = _policy_allows(policy, provider_name)
    if not allowed:
        return AIHealthResponse(
            provider=provider_name,
            model=model,
            ok=False,
            latency_ms=0,
            policy=policy,
            error=reason,
        )

    if not model:
        return AIHealthResponse(
            provider=provider_name,
            model="",
            ok=False,
            latency_ms=0,
            policy=policy,
            error=f"No model specified and no default model configured for '{provider_name}'.",
        )

    started = time.perf_counter()
    try:
        if provider_name == "anthropic":
            _ping_anthropic(settings.providers.anthropic_api_key, model)
        elif provider_name == "openai":
            _ping_openai_compatible(
                base_url="https://api.openai.com/v1",
                api_key=settings.providers.openai_api_key,
                model=model,
                requires_key=True,
            )
        elif provider_name == "openrouter":
            _ping_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.providers.openrouter_api_key,
                model=model,
                requires_key=True,
            )
        elif provider_name == "ollama":
            base = settings.providers.ollama_host.rstrip("/")
            if not base.endswith("/v1"):
                base = base + "/v1"
            _ping_openai_compatible(
                base_url=base,
                api_key="ollama",
                model=model,
                requires_key=False,
            )
        else:
            raise RuntimeError(f"Provider '{provider_name}' is recognized but not wired.")
    except _ProviderError as exc:
        return AIHealthResponse(
            provider=provider_name,
            model=model,
            ok=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            policy=policy,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return AIHealthResponse(
            provider=provider_name,
            model=model,
            ok=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            policy=policy,
            error=f"{type(exc).__name__}: {exc}",
        )
    return AIHealthResponse(
        provider=provider_name,
        model=model,
        ok=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
        policy=policy,
    )


class _ProviderError(RuntimeError):
    pass


def _ping_anthropic(api_key: str, model: str) -> None:
    if not api_key:
        raise _ProviderError("Anthropic API key is not configured.")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise _ProviderError(f"anthropic package not installed: {exc}") from exc

    client = Anthropic(api_key=api_key, timeout=15.0)
    client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )


def _ping_openai_compatible(
    *, base_url: str, api_key: str, model: str, requires_key: bool
) -> None:
    if requires_key and not api_key:
        raise _ProviderError("API key is not configured for this provider.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise _ProviderError(f"openai package not installed: {exc}") from exc

    client = OpenAI(base_url=base_url, api_key=api_key or "sk-none", timeout=15.0)
    client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )
