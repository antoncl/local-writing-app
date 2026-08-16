"""Shared base for providers that speak the OpenAI chat-completions wire.

OpenAI, Ollama, and OpenRouter all reach their endpoint through the
`openai` SDK against a different base URL. This class owns the one `chat`
call; each subclass supplies its endpoint and key, and overrides the
message / extra-body hooks where it differs (only OpenRouter does).
Anthropic is deliberately not here — it has its own SDK and cache shape.
"""

from __future__ import annotations

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
        if call.temperature is not None:
            kwargs["temperature"] = call.temperature
        extra_body = self._extra_body(call)
        if extra_body:
            kwargs["extra_body"] = extra_body
        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
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

    def chat_stream(
        self, call: ChatCall
    ) -> Iterator[StreamDelta | StreamThinking | StreamFinal]:
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
        if call.temperature is not None:
            kwargs["temperature"] = call.temperature
        extra_body = self._extra_body(call)
        if extra_body:
            kwargs["extra_body"] = extra_body
        splitter = ThinkTagSplitter()
        stop_reason: str | None = None
        final_chunk: Any = None
        for chunk in client.chat.completions.create(**kwargs):
            if getattr(chunk, "usage", None) is not None:
                final_chunk = chunk
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            yield from self._stream_delta_events(delta, splitter)
            finish = getattr(choice, "finish_reason", None)
            if finish:
                stop_reason = finish
        # Flush any pending buffered text after the stream ends.
        yield from splitter.flush()
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
