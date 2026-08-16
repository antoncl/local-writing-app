from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.models import AIHealthResponse, AIPolicy
from app.services.ai.profiles import UsageMetrics
from app.services.ai.profiles.base import (
    ChatCall,
    ProviderError,
    StreamDelta,
    StreamFinal,
    StreamThinking,
)
from app.services.ai.profiles.registry import (
    capability_profile_for,
    profile_for,
    recognizing_provider,
)
from app.services.machine_settings import MachineSettings

CLOUD_PROVIDERS = {"anthropic", "openai", "openrouter"}
LOCAL_PROVIDERS = {"ollama"}
KNOWN_PROVIDERS = CLOUD_PROVIDERS | LOCAL_PROVIDERS
PROVIDER_DISPLAY_NAMES = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
}

DEFAULT_CHAT_MAX_TOKENS = 1024


@dataclass
class ChatResult:
    content: str
    provider: str
    model: str
    latency_ms: int
    ok: bool
    error: str | None = None
    stop_reason: str | None = None
    # V2: per-call token + cost telemetry. None on failure paths and on
    # streaming completions (those land in step 5). Cost is computed
    # downstream from the descriptor — the dispatch layer doesn't know
    # about pricing.
    usage: UsageMetrics | None = None


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
    error = _validate_provider_request(provider_name, model, policy)
    if error is not None:
        return AIHealthResponse(
            provider=provider_name,
            model=model,
            ok=False,
            latency_ms=0,
            policy=policy,
            error=error,
        )

    started = time.perf_counter()
    try:
        profile = profile_for(provider_name, settings)
        _ensure_provider_key(provider_name, profile.configured_key())
        profile.health_ping(model)
    except ProviderError as exc:
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


def _ensure_provider_key(provider_name: str, api_key: str) -> None:
    if provider_name not in CLOUD_PROVIDERS:
        return
    display_name = PROVIDER_DISPLAY_NAMES.get(provider_name, provider_name)
    if not api_key:
        raise ProviderError(f"{display_name} API key is not configured.")
    # Each provider recognizes its own key signature; the registry scan
    # attributes a key to the provider it most specifically matches. If that
    # isn't this provider, the user has pasted the wrong key into this field.
    hint = recognizing_provider(api_key)
    if hint is None or hint == provider_name:
        return
    hinted_name = PROVIDER_DISPLAY_NAMES.get(hint, hint)
    expected = {
        "anthropic": "sk-ant-...",
        "openai": "sk-... or sk-proj-...",
        "openrouter": "sk-or-...",
    }.get(provider_name, "the provider's key")
    raise ProviderError(
        f"{display_name} API key appears to contain a {hinted_name} key. "
        f"Check the AI tab in Settings and put a {expected} key in the {display_name} field."
    )


# ----- Chat completion -----


def _validate_provider_request(
    provider_name: str,
    model: str,
    policy: AIPolicy,
) -> str | None:
    """Shared pre-flight for any provider call — provider known, allowed by
    policy, model present. Returns an error message or None. `chat`/`chat_stream`
    layer a messages check on top; `health_check` uses this directly.
    """
    if not provider_name:
        return "No provider specified and no default_provider configured."
    if provider_name not in KNOWN_PROVIDERS:
        return f"Unknown provider '{provider_name}'. Known: {sorted(KNOWN_PROVIDERS)}."
    allowed, reason = _policy_allows(policy, provider_name)
    if not allowed:
        return reason
    if not model:
        return f"No model specified and no default model configured for '{provider_name}'."
    return None


def _validate_chat_request(
    provider_name: str,
    model: str,
    messages: list[dict[str, str]],
    policy: AIPolicy,
) -> str | None:
    """Pre-flight for chat and chat_stream: the shared provider checks plus a
    non-empty messages check. Returns an error message or None.
    """
    error = _validate_provider_request(provider_name, model, policy)
    if error is not None:
        return error
    if not messages:
        return "messages must not be empty."
    return None


def chat(
    call: ChatCall,
    *,
    provider_name: str,
    settings: MachineSettings,
    policy: AIPolicy,
) -> ChatResult:
    """Run a chat completion against the chosen provider.

    `call` is the provider-agnostic request (model, prompt, messages, token
    cap, temperature, and the multi-block `system_blocks` form with per-block
    cache markers); `provider_name`/`settings`/`policy` say who to route it to
    and whether that's allowed. Validates the request, resolves the provider's
    profile from the registry, and delegates the wire call to `profile.chat`.
    Callers build `call` once via `ResolvedCall.to_call`.
    """
    error = _validate_chat_request(provider_name, call.model, call.messages, policy)
    if error is not None:
        return ChatResult(
            content="", provider=provider_name, model=call.model, latency_ms=0,
            ok=False, error=error,
        )

    started = time.perf_counter()
    try:
        profile = profile_for(provider_name, settings)
        _ensure_provider_key(provider_name, profile.configured_key())
        outcome = profile.chat(call)
    except ProviderError as exc:
        return ChatResult(
            content="", provider=provider_name, model=call.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ok=False, error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return ChatResult(
            content="", provider=provider_name, model=call.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ok=False, error=f"{type(exc).__name__}: {exc}",
        )

    usage = _extract_usage_for_provider(provider_name, outcome.raw, call.model)

    return ChatResult(
        content=outcome.content,
        provider=provider_name,
        model=call.model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        ok=True,
        stop_reason=outcome.stop_reason,
        usage=usage,
    )


def _extract_usage_for_provider(
    provider_name: str, raw_response: Any, model: str
) -> UsageMetrics | None:
    """Per-provider response → UsageMetrics. Returns None when extraction
    raises (malformed response, unknown provider) — usage is best-effort
    telemetry, never a failure surface for the call itself.

    Resolves the provider through the registry rather than branching per
    provider. The credential-less `capability_profile_for` is enough
    because `extract_usage` is pure parsing — no credentials needed, no
    state held — and it returns None on an unknown provider.
    """
    profile = capability_profile_for(provider_name)
    if profile is None:
        return None
    try:
        return profile.extract_usage(raw_response, model)
    except Exception:  # noqa: BLE001
        return None


# ----- Streaming chat completion -----


@dataclass
class StreamDone:
    provider: str
    model: str
    latency_ms: int
    stop_reason: str | None
    truncated: bool
    # V2: per-stream telemetry. None when the provider didn't return usage
    # in the terminal chunk (rare; we always ask for it on OpenAI-compat
    # via stream_options.include_usage). Cost is computed downstream from
    # the descriptor — the dispatch layer doesn't know about pricing.
    usage: UsageMetrics | None = None


@dataclass
class StreamError:
    provider: str
    model: str
    latency_ms: int
    error: str


StreamEvent = StreamDelta | StreamThinking | StreamDone | StreamError


def chat_stream(
    call: ChatCall,
    *,
    provider_name: str,
    settings: MachineSettings,
    policy: AIPolicy,
) -> Iterator[StreamEvent]:
    """Stream a chat completion.

    Same request/routing split as `chat` — `call` carries the request (here
    including `thinking_enabled`), the keyword args carry the routing. Yields
    zero or more `StreamDelta`/`StreamThinking` events as chunks arrive,
    followed by exactly one terminal event: `StreamDone` on success or
    `StreamError` on failure. Validation errors (unknown provider, policy,
    missing key) produce a `StreamError` and no deltas.
    """
    error = _validate_chat_request(provider_name, call.model, call.messages, policy)
    if error is not None:
        yield StreamError(provider=provider_name, model=call.model, latency_ms=0, error=error)
        return

    started = time.perf_counter()
    stop_reason: str | None = None
    usage: UsageMetrics | None = None
    try:
        profile = profile_for(provider_name, settings)
        _ensure_provider_key(provider_name, profile.configured_key())
        for ev in profile.chat_stream(call):
            if isinstance(ev, (StreamDelta, StreamThinking)):
                yield ev
            elif isinstance(ev, StreamFinal):
                stop_reason = ev.stop_reason
                usage = ev.usage
    except ProviderError as exc:
        yield StreamError(provider=provider_name, model=call.model,
                          latency_ms=int((time.perf_counter() - started) * 1000),
                          error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        yield StreamError(provider=provider_name, model=call.model,
                          latency_ms=int((time.perf_counter() - started) * 1000),
                          error=f"{type(exc).__name__}: {exc}")
        return

    truncated = stop_reason in {"max_tokens", "length"}
    yield StreamDone(
        provider=provider_name, model=call.model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        stop_reason=stop_reason, truncated=truncated,
        usage=usage,
    )
