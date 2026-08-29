"""Shared base for providers that speak the OpenAI chat-completions wire.

OpenAI, Ollama, and OpenRouter all reach their endpoint through the
`openai` SDK against a different base URL. This class owns the one `chat`
call; each subclass supplies its endpoint and key, and overrides the
message / extra-body hooks where it differs (only OpenRouter does).
Anthropic is deliberately not here — it has its own SDK and cache shape.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from app.services.ai.profiles.base import (
    ChatCall,
    ChatOutcome,
    ProviderError,
    ProviderProfile,
    StreamDelta,
    StreamFinal,
    StreamThinking,
    ThinkTagSplitter,
)

# Chat calls are long-running (large context, slow models); match the
# timeout the free-function dispatcher used before the reshape.
_CHAT_TIMEOUT = 180.0

log = logging.getLogger(__name__)


class _StreamDiag:
    """Cheap per-stream accumulator for the "empty output" investigation (#1588).

    Observes every raw chunk and records the signals that tell the candidate
    causes apart, so that when a stream yields NO content we can log one line
    that names the reason instead of guessing:

    - ``content_idx0`` vs ``content_other`` — the adapter consumes only
      ``choices[0]``; if content lands in ``choices[1:]`` (the doubled
      ``finish_reason`` OpenRouter/deepseek emits) this split reveals it.
    - ``reasoning`` — chars on ``reasoning``/``reasoning_content`` (the
      OpenRouter override drops these; a reasoning-only turn would look empty).
    - ``refusal`` — a moderation refusal (a fiction app is a prime trigger).
    - ``finishes`` — ``(choice_index, finish_reason)``, e.g. ``content_filter``.

    Every field is derived from a handful of ``getattr`` calls per chunk, so it
    is safe on the normal (non-empty) hot path; the log only fires when empty.
    """

    def __init__(self) -> None:
        self.chunks = 0
        self.max_choices = 0
        self.content_idx0 = 0
        self.content_other = 0
        self.reasoning = 0
        self.refusal: Any = None
        self.finishes: list[tuple[int, str]] = []
        self.last: Any = None

    def observe(self, chunk: Any) -> None:
        self.chunks += 1
        self.last = chunk
        choices = getattr(chunk, "choices", None) or []
        self.max_choices = max(self.max_choices, len(choices))
        for idx, choice in enumerate(choices):
            delta = getattr(choice, "delta", None)
            if delta is not None:
                text = getattr(delta, "content", None) or ""
                if idx == 0:
                    self.content_idx0 += len(text)
                else:
                    self.content_other += len(text)
                reasoning = (
                    getattr(delta, "reasoning_content", None)
                    or getattr(delta, "reasoning", None)
                )
                if reasoning:
                    self.reasoning += len(reasoning)
                refusal = getattr(delta, "refusal", None)
                if refusal:
                    self.refusal = refusal
            finish = getattr(choice, "finish_reason", None)
            if finish:
                self.finishes.append((idx, finish))

    def log_empty(self, call: ChatCall, extra_body: dict) -> None:
        """Emit one WARNING describing an empty stream. Fires only on the bug."""
        log.warning(
            "empty provider stream (#1588): model=%s chunks=%d max_choices=%d "
            "content_idx0=%d content_other=%d reasoning=%d refusal=%r finishes=%s "
            "req[msgs=%d sys_blocks=%d max_tokens=%s temp=%s extra=%s] last=%.400r",
            call.model, self.chunks, self.max_choices,
            self.content_idx0, self.content_other, self.reasoning, self.refusal,
            self.finishes,
            len(call.messages), len(call.system_blocks or []),
            call.max_tokens, call.temperature, sorted(extra_body),
            self.last,
        )


def _inband_error_message(obj: Any) -> str | None:
    """Pull an in-band error message off a streamed chunk, a choice, or a
    non-stream response, if one is present.

    OpenRouter (unlike a raw OpenAI endpoint) reports some upstream failures —
    rate-limit, "no available provider", an upstream 5xx, content moderation — as
    an HTTP 200 response carrying an `error` object `{code, message, metadata}`.
    When that object rides at the *top level* of a stream frame the `openai` SDK
    raises for us; when it is nested on the *choice* it does not, so the caller
    must look. `ChatCompletionChunk`/`Choice` allow extra fields, so the `error`
    survives parsing and is readable here — it was just never inspected, which
    turned a real failure into an empty "successful" turn (#1581).

    Returns a human-readable message, or None when there is no error.
    """
    err = getattr(obj, "error", None)
    if not err:
        return None
    if isinstance(err, dict):
        message = err.get("message") or err.get("code")
    else:
        message = getattr(err, "message", None) or getattr(err, "code", None)
    return str(message) if message else str(err)


def _raise_on_inband(obj: Any) -> None:
    """Raise ProviderError if `obj` (a chunk, choice, or response) carries an
    in-band error — see `_inband_error_message`. A no-op otherwise."""
    message = _inband_error_message(obj)
    if message:
        raise ProviderError(message)


class OpenAICompatibleProfile(ProviderProfile):
    """A provider reachable through the `openai` SDK against a base URL.

    Concrete subclasses implement the metadata methods (`list_models`,
    `caching_style`, `count_tokens`, `extract_usage`, `from_settings`) and
    supply `_chat_base_url` / `_chat_api_key`. They inherit one `chat` and one
    `chat_stream`; OpenRouter overrides `_build_messages` / `_extra_body`
    (and `_stream_delta_events` / `_stream_timeout` for its plainer stream).
    """

    # Streaming timeout for the OpenAI/Ollama path. OpenRouter overrides (300s).
    _stream_timeout: float = 180.0

    def _chat_base_url(self) -> str:
        """The OpenAI-compatible endpoint for this provider."""
        raise NotImplementedError

    def _chat_api_key(self) -> str:
        """The key to send on the request. Defaults to the configured key;
        Ollama overrides with its placeholder since it needs none."""
        return getattr(self, "_api_key", "")

    def configured_key(self) -> str:
        return getattr(self, "_api_key", "")

    def _build_messages(self, call: ChatCall) -> list[dict]:
        """Default: prepend the system prompt as a single system message.

        The plain OpenAI wire doesn't understand multi-block cache markers,
        so when `system_blocks` are supplied they're collapsed to one string
        (matching the pre-reshape dispatcher). OpenRouter overrides this to
        pass the markers through on explicit-cache routes.
        """
        system = call.system_prompt
        if call.system_blocks:
            collapsed = "\n\n".join(
                b.get("text", "") for b in call.system_blocks if b.get("text")
            )
            system = collapsed or call.system_prompt
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend(call.messages)
        return messages

    def _extra_body(self, call: ChatCall) -> dict:
        """Default: no provider-specific fields. OpenRouter overrides this
        to pin `session_id` for provider stickiness."""
        return {}

    def chat(self, call: ChatCall) -> ChatOutcome:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(f"openai package not installed: {exc}") from exc

        client = OpenAI(
            base_url=self._chat_base_url(),
            api_key=self._chat_api_key() or "sk-none",
            timeout=_CHAT_TIMEOUT,
        )
        kwargs: dict = {
            "model": call.model,
            "max_tokens": call.max_tokens,
            "messages": self._build_messages(call),
        }
        if call.temperature is not None and self.supports_temperature(call.model):
            kwargs["temperature"] = call.temperature
        extra_body = self._extra_body(call)
        if extra_body:
            kwargs["extra_body"] = extra_body
        response = client.chat.completions.create(**kwargs)
        _raise_on_inband(response)
        choices = getattr(response, "choices", None) or []
        if not choices:
            # A 200 with neither choices nor an error object — nothing to return.
            # Guard the `choices[0]` index so this surfaces as a clean provider
            # error rather than an IndexError.
            raise ProviderError("Provider returned an empty response (no choices).")
        choice = choices[0]
        _raise_on_inband(choice)
        stop_reason = getattr(choice, "finish_reason", None)
        return ChatOutcome(choice.message.content or "", stop_reason, response)

    def health_ping(self, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(f"openai package not installed: {exc}") from exc

        client = OpenAI(
            base_url=self._chat_base_url(),
            api_key=self._chat_api_key() or "sk-none",
            timeout=15.0,
        )
        client.chat.completions.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )

    def _open_stream(self, call: ChatCall) -> tuple[Any, dict]:
        """Build the OpenAI client and open the streaming request. Returns the
        chunk iterator and the `extra_body` (kept so an empty-stream diagnostic
        can report which provider-specific fields were on the wire)."""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(f"openai package not installed: {exc}") from exc

        client = OpenAI(
            base_url=self._chat_base_url(),
            api_key=self._chat_api_key() or "sk-none",
            timeout=self._stream_timeout,
        )
        kwargs: dict = {
            "model": call.model,
            "max_tokens": call.max_tokens,
            "messages": self._build_messages(call),
            "stream": True,
            # Ask the endpoint for a final usage chunk; without this the
            # streaming path never sees usage.
            "stream_options": {"include_usage": True},
        }
        if call.temperature is not None and self.supports_temperature(call.model):
            kwargs["temperature"] = call.temperature
        extra_body = self._extra_body(call)
        if extra_body:
            kwargs["extra_body"] = extra_body
        return client.chat.completions.create(**kwargs), extra_body

    def chat_stream(
        self, call: ChatCall
    ) -> Iterator[StreamDelta | StreamThinking | StreamFinal]:
        stream, extra_body = self._open_stream(call)
        splitter = ThinkTagSplitter()
        stop_reason: str | None = None
        final_chunk: Any = None
        # #1588: track whether any visible content/thinking reached the client, and
        # accumulate diagnostics, so a no-content completion logs its cause instead
        # of ending as a silent "Model returned empty output".
        emitted = False
        diag = _StreamDiag()
        for chunk in stream:
            diag.observe(chunk)
            # A choice-nested error frame (OpenRouter's shape for rate-limit /
            # no-provider / upstream 5xx) does not make the SDK raise — surface it
            # as a real error instead of a fake-success empty turn (#1581). The
            # top-level frame already raises in the SDK; guard both levels here.
            _raise_on_inband(chunk)
            if getattr(chunk, "usage", None) is not None:
                final_chunk = chunk
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            _raise_on_inband(choice)
            for event in self._stream_delta_events(getattr(choice, "delta", None), splitter):
                if event.text:
                    emitted = True
                yield event
            finish = getattr(choice, "finish_reason", None)
            if finish:
                stop_reason = finish
        # Flush any pending buffered text after the stream ends.
        for event in splitter.flush():
            if event.text:
                emitted = True
            yield event
        if not emitted:
            diag.log_empty(call, extra_body)
        usage = (
            self.extract_usage(final_chunk, call.model)
            if final_chunk is not None
            else None
        )
        yield StreamFinal(stop_reason=stop_reason, usage=usage)

    def _stream_delta_events(
        self, delta: Any, splitter: ThinkTagSplitter
    ) -> Iterator[StreamDelta | StreamThinking]:
        """Turn one streamed delta into events. The default handles the
        OpenAI-compatible extensions: a `reasoning`/`reasoning_content` field
        (DeepSeek, Ollama's /v1 shim) becomes thinking, and content is routed
        through the <think>-tag splitter for models that emit inline reasoning.
        OpenRouter overrides this with a plain content-only version.
        """
        reasoning = (
            getattr(delta, "reasoning_content", None)
            or getattr(delta, "reasoning", None)
        ) if delta else None
        if reasoning:
            yield StreamThinking(text=reasoning)
        text = getattr(delta, "content", None) if delta else None
        if text:
            yield from splitter.feed(text)
