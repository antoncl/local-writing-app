from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from app.models import AIHealthResponse, AIPolicy
from app.services.machine_settings import MachineSettings


CLOUD_PROVIDERS = {"anthropic", "openai", "openrouter"}
LOCAL_PROVIDERS = {"ollama"}
KNOWN_PROVIDERS = CLOUD_PROVIDERS | LOCAL_PROVIDERS

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


# ----- Chat completion -----


def chat(
    *,
    provider_name: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    settings: MachineSettings,
    policy: AIPolicy,
    temperature: float = 0.7,
    system_blocks: list[dict] | None = None,
    session_id: str | None = None,
) -> ChatResult:
    """Run a chat completion against the chosen provider.

    `messages` is a list of `{role, content}` dicts where role is 'user' or
    'assistant'. The system prompt is kept separate (Anthropic places it on
    its own param; OpenAI-compatible prepends a system message).

    `system_blocks` is the multi-block form with per-block cache markers
    (see `_anthropic_system_blocks`). When provided, it overrides
    `system_prompt`. Currently honored only by the Anthropic adapter;
    other adapters collapse blocks back to a string (OpenRouter caching
    support arrives in a follow-up — step 5b).
    """
    if not provider_name:
        return ChatResult(
            content="", provider="", model=model, latency_ms=0, ok=False,
            error="No provider specified and no default_provider configured.",
        )
    if provider_name not in KNOWN_PROVIDERS:
        return ChatResult(
            content="", provider=provider_name, model=model, latency_ms=0, ok=False,
            error=f"Unknown provider '{provider_name}'. Known: {sorted(KNOWN_PROVIDERS)}.",
        )

    allowed, reason = _policy_allows(policy, provider_name)
    if not allowed:
        return ChatResult(
            content="", provider=provider_name, model=model, latency_ms=0, ok=False,
            error=reason,
        )

    if not model:
        return ChatResult(
            content="", provider=provider_name, model="", latency_ms=0, ok=False,
            error=f"No model specified and no default model configured for '{provider_name}'.",
        )

    if not messages:
        return ChatResult(
            content="", provider=provider_name, model=model, latency_ms=0, ok=False,
            error="messages must not be empty.",
        )

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
    try:
        if provider_name == "anthropic":
            content, stop_reason = _anthropic_chat(
                api_key=settings.providers.anthropic_api_key,
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_blocks=system_blocks,
            )
        elif provider_name == "openai":
            content, stop_reason = _openai_compatible_chat(
                base_url="https://api.openai.com/v1",
                api_key=settings.providers.openai_api_key,
                model=model,
                system_prompt=effective_system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                requires_key=True,
                temperature=temperature,
            )
        elif provider_name == "openrouter":
            from app.services.ai.profiles.openrouter import caching_style_for_model
            content, stop_reason = _openrouter_chat(
                api_key=settings.providers.openrouter_api_key,
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_blocks=system_blocks,
                caching_style=caching_style_for_model(model),
                session_id=session_id,
            )
        elif provider_name == "ollama":
            base = settings.providers.ollama_host.rstrip("/")
            if not base.endswith("/v1"):
                base = base + "/v1"
            content, stop_reason = _openai_compatible_chat(
                base_url=base,
                api_key="ollama",
                model=model,
                system_prompt=effective_system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                requires_key=False,
                temperature=temperature,
            )
        else:
            raise RuntimeError(f"Provider '{provider_name}' is recognized but not wired.")
    except _ProviderError as exc:
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

    return ChatResult(
        content=content,
        provider=provider_name,
        model=model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        ok=True,
        stop_reason=stop_reason,
    )


def _anthropic_chat(
    *, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, temperature: float = 0.7,
    system_blocks: list[dict] | None = None,
) -> tuple[str, str | None]:
    if not api_key:
        raise _ProviderError("Anthropic API key is not configured.")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise _ProviderError(f"anthropic package not installed: {exc}") from exc

    client = Anthropic(api_key=api_key, timeout=120.0)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    # system_blocks (multi-block with per-block cache markers) overrides
    # the legacy single-string system_prompt. Caller picks one or the other.
    if system_blocks:
        system_payload = _anthropic_system_blocks(system_blocks)
        if system_payload:
            kwargs["system"] = system_payload
    elif system_prompt:
        kwargs["system"] = _anthropic_system_with_cache(system_prompt)
    response = client.messages.create(**kwargs)
    blocks = getattr(response, "content", None) or []
    parts = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    stop_reason = getattr(response, "stop_reason", None)
    return "".join(parts), stop_reason


def _openrouter_system_messages(
    system_prompt: str,
    system_blocks: list[dict] | None,
    caching_style: str,
) -> list[dict]:
    """Build the [system] message list for an OpenRouter chat call.

    OpenRouter accepts Anthropic-style `cache_control` markers on
    individual content blocks when the routed-to provider needs them
    explicitly (anthropic/google/qwen). For auto-cache providers
    (openai/deepseek/grok/etc.) markers are ignored, so we collapse to
    a plain string to keep the wire small.

    Returns [] when there's nothing to send so the caller can append the
    user/assistant messages without an empty system entry.

    Pure function — testable without network or SDK.
    """
    if system_blocks and caching_style == "explicit":
        parts: list[dict] = []
        for block in system_blocks:
            text = block.get("text") or ""
            if not text:
                continue
            part: dict = {"type": "text", "text": text}
            if block.get("cache_break_after"):
                cache_control: dict = {"type": "ephemeral"}
                ttl = block.get("ttl")
                if ttl in ("5m", "1h"):
                    cache_control["ttl"] = ttl
                part["cache_control"] = cache_control
            parts.append(part)
        if parts:
            return [{"role": "system", "content": parts}]
        return []
    # caching_style != "explicit": collapse blocks to a single string
    # (auto-cache providers index on prefix bytes, no markers needed;
    # "none" providers don't cache anyway).
    collapsed = system_prompt
    if system_blocks and not collapsed:
        collapsed = "\n\n".join(
            b.get("text", "") for b in system_blocks if b.get("text")
        )
    if not collapsed:
        return []
    return [{"role": "system", "content": collapsed}]


def _openrouter_extra_body(session_id: str | None) -> dict:
    """OpenRouter-specific fields outside the standard chat-completions
    schema. Currently just `session_id` for provider stickiness — pinning
    a chat to one underlying provider so the cache prefix stays valid
    across turns. See https://openrouter.ai/docs/guides/best-practices/prompt-caching
    """
    extra: dict = {}
    if session_id:
        extra["session_id"] = session_id
    return extra


def _openrouter_chat(
    *, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, temperature: float = 0.7,
    system_blocks: list[dict] | None = None,
    caching_style: str = "none",
    session_id: str | None = None,
) -> tuple[str, str | None]:
    """OpenRouter chat completion, with cache-marker pass-through when the
    routed-to provider supports explicit caching."""
    if not api_key:
        raise _ProviderError("API key is not configured for this provider.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise _ProviderError(f"openai package not installed: {exc}") from exc

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        timeout=180.0,
    )
    full_messages = list(_openrouter_system_messages(system_prompt, system_blocks, caching_style))
    full_messages.extend(messages)
    extra_body = _openrouter_extra_body(session_id)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": full_messages,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    stop_reason = getattr(choice, "finish_reason", None)
    return choice.message.content or "", stop_reason


def _openrouter_chat_stream(
    *, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, requires_key: bool,
    temperature: float = 0.7,
    system_blocks: list[dict] | None = None,
    caching_style: str = "none",
    session_id: str | None = None,
) -> Iterator[StreamDelta | StreamThinking | str | None]:
    """Streaming variant of _openrouter_chat. Same cache-marker semantics."""
    if requires_key and not api_key:
        raise _ProviderError("API key is not configured for this provider.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise _ProviderError(f"openai package not installed: {exc}") from exc

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
        "temperature": temperature,
        "messages": full_messages,
        "stream": True,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    stop_reason: str | None = None
    for chunk in client.chat.completions.create(**kwargs):
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
    yield stop_reason


def _openai_compatible_chat(
    *, base_url: str, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, requires_key: bool,
    temperature: float = 0.7,
) -> tuple[str, str | None]:
    if requires_key and not api_key:
        raise _ProviderError("API key is not configured for this provider.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise _ProviderError(f"openai package not installed: {exc}") from exc

    client = OpenAI(base_url=base_url, api_key=api_key or "sk-none", timeout=180.0)
    full_messages: list[dict[str, str]] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=full_messages,
    )
    choice = response.choices[0]
    stop_reason = getattr(choice, "finish_reason", None)
    return choice.message.content or "", stop_reason


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


def _anthropic_system_with_cache(system_prompt: str):
    """Wrap a single system prompt as a cacheable content block.

    Thin compatibility wrapper around `_anthropic_system_blocks` for the
    single-block path (one cache marker after the whole system prompt).
    Kept stable for callers that haven't migrated to passing structured
    blocks. See `_anthropic_system_blocks` for the multi-block variant.
    """

    if not system_prompt:
        return ""
    return _anthropic_system_blocks(
        [{"text": system_prompt, "cache_break_after": True}]
    )


def _anthropic_system_blocks(blocks: list[dict]):
    """Convert structured system blocks into Anthropic's content-array shape.

    Each input block is a dict:
        {
            "text": str,
            "cache_break_after": bool = False,
            "ttl": "5m" | "1h" = "5m",   # only honored when cache_break_after
        }

    Output is a list of `{type, text, cache_control?}` dicts suitable for
    the Anthropic SDK's `system` kwarg. A cache_control marker is emitted
    only on blocks where `cache_break_after` is True. Anthropic caches
    the prefix UP TO each marker; placing markers between stable
    sections (system header → lore → conversation pre-tail) lets later
    turns reuse the cached prefix up to the last unchanged marker.

    Empty blocks (no text) are dropped. Empty input list returns ""
    so the caller can skip the `system` kwarg entirely.

    Min-cache-size and breakpoint-budget enforcement are the caller's
    responsibility — this function just emits what's asked.
    """

    if not blocks:
        return ""
    out: list[dict] = []
    for block in blocks:
        text = block.get("text") or ""
        if not text:
            continue
        sdk_block: dict = {"type": "text", "text": text}
        if block.get("cache_break_after"):
            cache_control: dict = {"type": "ephemeral"}
            ttl = block.get("ttl")
            if ttl in ("5m", "1h"):
                cache_control["ttl"] = ttl
            sdk_block["cache_control"] = cache_control
        out.append(sdk_block)
    return out if out else ""


def chat_stream(
    *,
    provider_name: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    settings: MachineSettings,
    policy: AIPolicy,
    temperature: float = 0.7,
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
    if not provider_name:
        yield StreamError(provider="", model=model, latency_ms=0,
                          error="No provider specified and no default_provider configured.")
        return
    if provider_name not in KNOWN_PROVIDERS:
        yield StreamError(provider=provider_name, model=model, latency_ms=0,
                          error=f"Unknown provider '{provider_name}'. Known: {sorted(KNOWN_PROVIDERS)}.")
        return
    allowed, reason = _policy_allows(policy, provider_name)
    if not allowed:
        yield StreamError(provider=provider_name, model=model, latency_ms=0, error=reason or "")
        return
    if not model:
        yield StreamError(provider=provider_name, model="", latency_ms=0,
                          error=f"No model specified and no default model configured for '{provider_name}'.")
        return
    if not messages:
        yield StreamError(provider=provider_name, model=model, latency_ms=0,
                          error="messages must not be empty.")
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
    try:
        if provider_name == "anthropic":
            for ev in _anthropic_chat_stream(
                api_key=settings.providers.anthropic_api_key,
                model=model, system_prompt=system_prompt, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
                thinking_enabled=thinking_enabled,
                system_blocks=system_blocks,
            ):
                if isinstance(ev, (StreamDelta, StreamThinking)):
                    yield ev
                else:
                    stop_reason = ev  # final stop_reason string
        elif provider_name == "openrouter":
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
                else:
                    stop_reason = ev
        elif provider_name in {"openai", "ollama"}:
            if provider_name == "openai":
                base_url = "https://api.openai.com/v1"
                api_key = settings.providers.openai_api_key
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
            ):
                if isinstance(ev, (StreamDelta, StreamThinking)):
                    yield ev
                else:
                    stop_reason = ev
        else:
            raise RuntimeError(f"Provider '{provider_name}' is recognized but not wired.")
    except _ProviderError as exc:
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
    )


def _anthropic_chat_stream(
    *, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, temperature: float = 0.7,
    thinking_enabled: bool = False,
    system_blocks: list[dict] | None = None,
) -> Iterator[StreamDelta | StreamThinking | str | None]:
    """Yield StreamDelta / StreamThinking events, then a final stop_reason str.

    When thinking_enabled is True, sends Anthropic's extended-thinking parameter
    and forwards `thinking_delta` events as StreamThinking. Otherwise behaves
    like a normal text stream.

    `system_blocks` (multi-block cache markers) overrides `system_prompt`
    when provided. See `_anthropic_system_blocks`.
    """
    if not api_key:
        raise _ProviderError("Anthropic API key is not configured.")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise _ProviderError(f"anthropic package not installed: {exc}") from exc

    client = Anthropic(api_key=api_key, timeout=120.0)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
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
            # Anthropic requires temperature=1 when thinking is enabled.
            kwargs["temperature"] = 1.0
    stop_reason: str | None = None
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
        final = stream.get_final_message()
        stop_reason = getattr(final, "stop_reason", None)
    yield stop_reason


def _openai_compatible_chat_stream(
    *, base_url: str, api_key: str, model: str, system_prompt: str,
    messages: list[dict[str, str]], max_tokens: int, requires_key: bool,
    temperature: float = 0.7,
) -> Iterator[StreamDelta | StreamThinking | str | None]:
    if requires_key and not api_key:
        raise _ProviderError("API key is not configured for this provider.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise _ProviderError(f"openai package not installed: {exc}") from exc

    client = OpenAI(base_url=base_url, api_key=api_key or "sk-none", timeout=180.0)
    full_messages: list[dict[str, str]] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)
    stream = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=full_messages,
        stream=True,
    )
    splitter = _ThinkTagSplitter()
    stop_reason: str | None = None
    for chunk in stream:
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
    yield stop_reason


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
