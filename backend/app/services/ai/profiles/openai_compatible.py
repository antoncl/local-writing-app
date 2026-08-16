"""Shared base for providers that speak the OpenAI chat-completions wire.

OpenAI, Ollama, and OpenRouter all reach their endpoint through the
`openai` SDK against a different base URL. This class owns the one `chat`
call; each subclass supplies its endpoint and key, and overrides the
message / extra-body hooks where it differs (only OpenRouter does).
Anthropic is deliberately not here — it has its own SDK and cache shape.
"""

from __future__ import annotations

from app.services.ai.profiles.base import (
    ChatCall,
    ChatOutcome,
    ProviderError,
    ProviderProfile,
)

# Chat calls are long-running (large context, slow models); match the
# timeout the free-function dispatcher used before the reshape.
_CHAT_TIMEOUT = 180.0


class OpenAICompatibleProfile(ProviderProfile):
    """A provider reachable through the `openai` SDK against a base URL.

    Concrete subclasses implement the metadata methods (`list_models`,
    `caching_style`, `count_tokens`, `extract_usage`, `from_settings`) and
    supply `_chat_base_url` / `_chat_api_key`. They inherit one `chat`;
    OpenRouter overrides `_build_messages` / `_extra_body`.
    """

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
