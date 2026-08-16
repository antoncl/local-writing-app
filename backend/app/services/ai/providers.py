from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.models import AIHealthResponse, AIPolicy
from app.services.ai.profiles import UsageMetrics
from app.services.ai.profiles.anthropic import (
    anthropic_system_blocks as _anthropic_system_blocks,
)
from app.services.ai.profiles.anthropic import (
    anthropic_system_with_cache as _anthropic_system_with_cache,
)
from app.services.ai.profiles.base import ChatCall, ProviderError
from app.services.ai.profiles.openrouter import (
    openrouter_extra_body as _openrouter_extra_body,
)
from app.services.ai.profiles.openrouter import (
    openrouter_system_messages as _openrouter_system_messages,
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
                provider_name="openai",
                model=model,
                requires_key=True,
            )
        elif provider_name == "openrouter":
            _ping_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.providers.openrouter_api_key,
                provider_name="openrouter",
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
                provider_name="ollama",
                model=model,
                requires_key=False,
            )
        else:
            raise RuntimeError(f"Provider '{provider_name}' is recognized but not wired.")
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


def _ping_anthropic(api_key: str, model: str) -> None:
    _ensure_provider_key("anthropic", api_key)
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ProviderError(f"anthropic package not installed: {exc}") from exc

    client = Anthropic(api_key=api_key, timeout=15.0)
    client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )


def _ping_openai_compatible(
    *, base_url: str, api_key: str, provider_name: str, model: str, requires_key: bool
) -> None:
    if requires_key:
        _ensure_provider_key(provider_name, api_key)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderError(f"openai package not installed: {exc}") from exc

    client = OpenAI(base_url=base_url, api_key=api_key or "sk-none", timeout=15.0)
    client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )


# ----- Chat completion -----


def _validate_chat_request(
    provider_name: str,
    model: str,
    messages: list[dict[str, str]],
    policy: AIPolicy,
) -> str | None:
    """Shared pre-flight for chat and chat_stream. Returns an error message
    when the request can't proceed, or None when it's good to dispatch.
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
    if not messages:
        return "messages must not be empty."
    return None


def chat(
    *,
    provider_name: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    settings: MachineSettings,
    policy: AIPolicy,
    temperature: float | None = None,
    system_blocks: list[dict] | None = None,
    session_id: str | None = None,
) -> ChatResult:
    """Run a chat completion against the chosen provider.

    Validates the request, resolves the provider's profile from the
    registry, and delegates the wire call to `profile.chat`. `messages` is a
    list of `{role, content}` dicts; the system prompt is kept separate.
    `system_blocks` is the multi-block form with per-block cache markers,
    honored by the providers that support it (Anthropic; OpenRouter on
    explicit-cache routes) and collapsed to a string by the plain OpenAI
    path.
    """
    error = _validate_chat_request(provider_name, model, messages, policy)
    if error is not None:
        return ChatResult(
            content="", provider=provider_name, model=model, latency_ms=0,
            ok=False, error=error,
        )

    started = time.perf_counter()
    try:
        profile = profile_for(provider_name, settings)
        _ensure_provider_key(provider_name, profile.configured_key())
        outcome = profile.chat(
            ChatCall(
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_blocks=system_blocks,
                session_id=session_id,
            )
        )
    except ProviderError as exc:
        return ChatResult(
            content="", provider=provider_name, model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ok=False, error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return ChatResult(
            content="", provider=provider_name, model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ok=False, error=f"{type(exc).__name__}: {exc}",
        )

    usage = _extract_usage_for_provider(provider_name, outcome.raw, model)

    return ChatResult(
        content=outcome.content,
        provider=provider_name,
        model=model,
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


def _openrouter_chat_stream(
    *, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, requires_key: bool,
    temperature: float | None = None,
    system_blocks: list[dict] | None = None,
    caching_style: str = "none",
    session_id: str | None = None,
) -> Iterator[StreamDelta | StreamThinking | _StreamFinal]:
    """Streaming variant of _openrouter_chat. Same cache-marker semantics."""
    if requires_key:
        _ensure_provider_key("openrouter", api_key)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderError(f"openai package not installed: {exc}") from exc

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key or "sk-none",
        timeout=300.0,
    )
    full_messages = list(_openrouter_system_messages(system_prompt, system_blocks, caching_style))
    full_messages.extend(messages)
    extra_body = _openrouter_extra_body(session_id)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": full_messages,
        "stream": True,
        # Ask the OpenAI-compatible endpoint to send a final usage chunk.
        # On OpenAI direct this is `stream_options.include_usage`; OpenRouter
        # forwards it. Without this, the streaming path never sees usage.
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if extra_body:
        kwargs["extra_body"] = extra_body
    stop_reason: str | None = None
    final_chunk: Any = None
    for chunk in client.chat.completions.create(**kwargs):
        # Final usage chunks have an empty choices array but carry .usage.
        if getattr(chunk, "usage", None) is not None:
            final_chunk = chunk
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        text = getattr(delta, "content", None) if delta else None
        if text:
            yield StreamDelta(text=text)
        finish = getattr(choice, "finish_reason", None)
        if finish:
            stop_reason = finish
    usage = (
        _extract_usage_for_provider("openrouter", final_chunk, model)
        if final_chunk is not None
        else None
    )
    yield _StreamFinal(stop_reason=stop_reason, usage=usage)


# ----- Streaming chat completion -----


@dataclass
class StreamDelta:
    text: str


@dataclass
class StreamThinking:
    text: str


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
class _StreamFinal:
    """Internal terminator from inner stream helpers, carrying everything
    the public StreamDone needs from the provider side. The chat_stream
    wrapper unpacks this into StreamDone.

    Inner helpers used to yield a bare `stop_reason: str | None` as their
    final element; bundling usage in here lets us add new terminal fields
    without churning every helper's protocol.
    """

    stop_reason: str | None
    usage: UsageMetrics | None = None


@dataclass
class StreamError:
    provider: str
    model: str
    latency_ms: int
    error: str


StreamEvent = StreamDelta | StreamThinking | StreamDone | StreamError


# Default Anthropic extended-thinking budget when ai_thinking is enabled.
# Anthropic requires budget_tokens >= 1024 and budget_tokens < max_tokens.
_ANTHROPIC_THINKING_BUDGET = 1024


def chat_stream(
    *,
    provider_name: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    settings: MachineSettings,
    policy: AIPolicy,
    temperature: float | None = None,
    thinking_enabled: bool = False,
    system_blocks: list[dict] | None = None,
    session_id: str | None = None,
) -> Iterator[StreamEvent]:
    """Stream a chat completion.

    Yields zero or more `StreamDelta` events as text chunks arrive, followed by
    exactly one terminal event: `StreamDone` on success or `StreamError` on
    failure. Validation errors (unknown provider, policy, missing key) produce
    a `StreamError` and no deltas.
    """
    error = _validate_chat_request(provider_name, model, messages, policy)
    if error is not None:
        yield StreamError(provider=provider_name, model=model, latency_ms=0, error=error)
        return

    # OpenAI-compatible adapters don't currently understand system_blocks;
    # collapse to a single string. OpenRouter caching support (step 5b)
    # will branch on this so blocks survive when routing to providers
    # that need them.
    effective_system_prompt = system_prompt
    if system_blocks and provider_name != "anthropic":
        effective_system_prompt = "\n\n".join(
            b.get("text", "") for b in system_blocks if b.get("text")
        ) or system_prompt

    started = time.perf_counter()
    stop_reason: str | None = None
    usage: UsageMetrics | None = None
    try:
        if provider_name == "anthropic":
            _ensure_provider_key("anthropic", settings.providers.anthropic_api_key)
            for ev in _anthropic_chat_stream(
                api_key=settings.providers.anthropic_api_key,
                model=model, system_prompt=system_prompt, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
                thinking_enabled=thinking_enabled,
                system_blocks=system_blocks,
            ):
                if isinstance(ev, (StreamDelta, StreamThinking)):
                    yield ev
                elif isinstance(ev, _StreamFinal):
                    stop_reason = ev.stop_reason
                    usage = ev.usage
        elif provider_name == "openrouter":
            _ensure_provider_key("openrouter", settings.providers.openrouter_api_key)
            from app.services.ai.profiles.openrouter import caching_style_for_model
            for ev in _openrouter_chat_stream(
                api_key=settings.providers.openrouter_api_key,
                model=model, system_prompt=system_prompt, messages=messages,
                max_tokens=max_tokens, requires_key=True,
                temperature=temperature,
                system_blocks=system_blocks,
                caching_style=caching_style_for_model(model),
                session_id=session_id,
            ):
                if isinstance(ev, (StreamDelta, StreamThinking)):
                    yield ev
                elif isinstance(ev, _StreamFinal):
                    stop_reason = ev.stop_reason
                    usage = ev.usage
        elif provider_name in {"openai", "ollama"}:
            if provider_name == "openai":
                base_url = "https://api.openai.com/v1"
                api_key = settings.providers.openai_api_key
                _ensure_provider_key("openai", api_key)
                requires_key = True
            else:
                base = settings.providers.ollama_host.rstrip("/")
                if not base.endswith("/v1"):
                    base = base + "/v1"
                base_url = base
                api_key = "ollama"
                requires_key = False
            for ev in _openai_compatible_chat_stream(
                base_url=base_url, api_key=api_key, model=model,
                system_prompt=effective_system_prompt, messages=messages,
                max_tokens=max_tokens, requires_key=requires_key,
                temperature=temperature,
                provider_name=provider_name,
            ):
                if isinstance(ev, (StreamDelta, StreamThinking)):
                    yield ev
                elif isinstance(ev, _StreamFinal):
                    stop_reason = ev.stop_reason
                    usage = ev.usage
        else:
            raise RuntimeError(f"Provider '{provider_name}' is recognized but not wired.")
    except ProviderError as exc:
        yield StreamError(provider=provider_name, model=model,
                          latency_ms=int((time.perf_counter() - started) * 1000),
                          error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        yield StreamError(provider=provider_name, model=model,
                          latency_ms=int((time.perf_counter() - started) * 1000),
                          error=f"{type(exc).__name__}: {exc}")
        return

    truncated = stop_reason in {"max_tokens", "length"}
    yield StreamDone(
        provider=provider_name, model=model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        stop_reason=stop_reason, truncated=truncated,
        usage=usage,
    )


def _anthropic_chat_stream(
    *, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int,
    temperature: float | None = None,
    thinking_enabled: bool = False,
    system_blocks: list[dict] | None = None,
) -> Iterator[StreamDelta | StreamThinking | _StreamFinal]:
    """Yield StreamDelta / StreamThinking events, then a final stop_reason str.

    When thinking_enabled is True, sends Anthropic's extended-thinking parameter
    and forwards `thinking_delta` events as StreamThinking. Otherwise behaves
    like a normal text stream.

    `system_blocks` (multi-block cache markers) overrides `system_prompt`
    when provided. See `_anthropic_system_blocks`.
    """
    if not api_key:
        raise ProviderError("Anthropic API key is not configured.")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ProviderError(f"anthropic package not installed: {exc}") from exc

    from app.services.ai.profiles.anthropic import anthropic_supports_temperature

    client = Anthropic(api_key=api_key, timeout=120.0)
    temp_ok = anthropic_supports_temperature(model)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if temperature is not None and temp_ok:
        kwargs["temperature"] = temperature
    if system_blocks:
        system_payload = _anthropic_system_blocks(system_blocks)
        if system_payload:
            kwargs["system"] = system_payload
    elif system_prompt:
        kwargs["system"] = _anthropic_system_with_cache(system_prompt)
    if thinking_enabled:
        budget = max(1024, min(_ANTHROPIC_THINKING_BUDGET, max_tokens - 256))
        if budget >= 1024:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # Anthropic requires temperature=1 when thinking is enabled —
            # but only on models that still accept the parameter at all.
            if temp_ok:
                kwargs["temperature"] = 1.0
    stop_reason: str | None = None
    final_message: Any = None
    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            etype = getattr(event, "type", None)
            if etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", None) if delta else None
                if dtype == "text_delta":
                    text = getattr(delta, "text", "") or ""
                    if text:
                        yield StreamDelta(text=text)
                elif dtype == "thinking_delta":
                    text = getattr(delta, "thinking", "") or ""
                    if text:
                        yield StreamThinking(text=text)
        final_message = stream.get_final_message()
        stop_reason = getattr(final_message, "stop_reason", None)
    usage = _extract_usage_for_provider("anthropic", final_message, model)
    yield _StreamFinal(stop_reason=stop_reason, usage=usage)


def _openai_compatible_chat_stream(
    *, base_url: str, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, requires_key: bool,
    temperature: float | None = None,
    provider_name: str = "openai",
) -> Iterator[StreamDelta | StreamThinking | _StreamFinal]:
    """`provider_name` selects the response-shape parser for usage extraction.
    Pass "openai" or "ollama" — callers route both through this helper.
    """
    if requires_key:
        _ensure_provider_key(provider_name, api_key)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderError(f"openai package not installed: {exc}") from exc

    client = OpenAI(base_url=base_url, api_key=api_key or "sk-none", timeout=180.0)
    full_messages: list[dict[str, str]] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)
    create_kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": full_messages,
        "stream": True,
        # Final chunk carries .usage when this is set.
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        create_kwargs["temperature"] = temperature
    stream = client.chat.completions.create(**create_kwargs)
    splitter = _ThinkTagSplitter()
    stop_reason: str | None = None
    final_chunk: Any = None
    for chunk in stream:
        if getattr(chunk, "usage", None) is not None:
            final_chunk = chunk
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        # Thinking on the delta — a non-standard OpenAI extension with two
        # competing field names: DeepSeek uses `reasoning_content`, Ollama's
        # /v1 compat shim uses `reasoning`. Forward either as a thinking event.
        reasoning = (
            getattr(delta, "reasoning_content", None)
            or getattr(delta, "reasoning", None)
        ) if delta else None
        if reasoning:
            yield StreamThinking(text=reasoning)
        text = getattr(delta, "content", None) if delta else None
        if text:
            yield from splitter.feed(text)
        finish = getattr(choice, "finish_reason", None)
        if finish:
            stop_reason = finish
    # Flush any pending buffered text after the stream ends.
    yield from splitter.flush()
    usage = (
        _extract_usage_for_provider(provider_name, final_chunk, model)
        if final_chunk is not None
        else None
    )
    yield _StreamFinal(stop_reason=stop_reason, usage=usage)


class _ThinkTagSplitter:
    """Stream-safe splitter that reroutes <think>…</think> regions as thinking.

    Many local models (DeepSeek-R1, QwQ, Ollama) emit reasoning inline as
    `<think>…</think>` tags inside the content stream. This splitter consumes
    chunks of text and yields StreamDelta for normal content, StreamThinking
    for content inside tags, and holds back enough trailing characters that
    a tag split across chunk boundaries is still recognized.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, text: str) -> Iterator[StreamDelta | StreamThinking]:
        self._buf += text
        while self._buf:
            if self._in_think:
                idx = self._buf.find(self._CLOSE)
                if idx == -1:
                    # Emit everything except a possible partial closing tag.
                    hold = len(self._CLOSE) - 1
                    if len(self._buf) > hold:
                        out = self._buf[:-hold] if hold else self._buf
                        if out:
                            yield StreamThinking(text=out)
                        self._buf = self._buf[-hold:] if hold else ""
                    return
                if idx > 0:
                    yield StreamThinking(text=self._buf[:idx])
                self._buf = self._buf[idx + len(self._CLOSE):]
                self._in_think = False
            else:
                idx = self._buf.find(self._OPEN)
                if idx == -1:
                    hold = len(self._OPEN) - 1
                    if len(self._buf) > hold:
                        out = self._buf[:-hold] if hold else self._buf
                        if out:
                            yield StreamDelta(text=out)
                        self._buf = self._buf[-hold:] if hold else ""
                    return
                if idx > 0:
                    yield StreamDelta(text=self._buf[:idx])
                self._buf = self._buf[idx + len(self._OPEN):]
                self._in_think = True

    def flush(self) -> Iterator[StreamDelta | StreamThinking]:
        if not self._buf:
            return
        if self._in_think:
            yield StreamThinking(text=self._buf)
        else:
            yield StreamDelta(text=self._buf)
        self._buf = ""
