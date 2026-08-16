"""Call-parameter resolution (#178 slice 2).

Resolve provider / model / temperature / max_tokens for an AI request from the
override → assistant-metadata → settings-default priority chain. Extracted from
the HTTP layer as a free function taking the project service, matching the
`services/ai/` style (`build_preview`, `expand_context`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.ai.assistant_validation import coerce_optional_temperature
from app.services.ai.profiles.base import ChatCall

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings
    from app.services.project_service import ProjectService


@dataclass
class ResolvedCall:
    provider: str
    model: str
    # None means: the assistant didn't set a temperature. The provider
    # call sites omit the param entirely so the provider applies its own
    # default. Don't substitute a hardcoded fallback here — the whole
    # point of None is "don't assume."
    temperature: float | None
    max_tokens: int
    thinking_enabled: bool = False

    def to_call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        system_blocks: list[dict] | None = None,
        session_id: str | None = None,
    ) -> ChatCall:
        """Merge the resolved provider params (model, token cap, temperature,
        thinking) with this turn's prompt + messages into one provider-agnostic
        `ChatCall`. The single place the two halves meet, so the dispatch
        boundary takes one object instead of a fistful of positional twins —
        no bundle → unbundle → rebundle across the call sites.
        """
        return ChatCall(
            model=self.model,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system_blocks=system_blocks,
            session_id=session_id,
            thinking_enabled=self.thinking_enabled,
        )


def resolve_call_params(
    project: ProjectService,
    settings: MachineSettings,
    *,
    assistant_id: str | None,
    provider_override: str | None,
    model_override: str | None,
    max_tokens_override: int | None,
) -> ResolvedCall:
    """Resolve provider / model / temperature / max_tokens from a request.

    Priority for each field, highest first:
      1. Explicit override on the request (provider, model, max_tokens).
      2. The assistant indicated by assistant_id, or the topmost assistant
         in the file-backed roster when none is given (ADR-0024).
      3. The legacy default_provider / default_models matrix on settings.

    Temperature has no fallback: when the assistant doesn't set it (or
    there's no assistant at all), we pass None and let the provider's
    own default apply. Some newer models (e.g. claude-opus-4-7+) actually
    400 on an explicit temperature; assuming 0.7 broke them silently.
    """
    assistant = project.resolve_assistant(assistant_id)
    if assistant is not None:
        meta = assistant.metadata or {}
        a_provider = meta.get("ai_provider")
        a_model = meta.get("ai_model")
        provider = provider_override or (str(a_provider) if isinstance(a_provider, str) else "")
        model = model_override or (str(a_model) if isinstance(a_model, str) else "")
        temperature = coerce_optional_temperature(meta.get("ai_temperature"))
        if max_tokens_override is not None:
            max_tokens = max_tokens_override
        else:
            try:
                max_tokens = int(meta.get("ai_max_tokens", 4096))
            except (TypeError, ValueError):
                max_tokens = 4096
        return ResolvedCall(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_enabled=bool(meta.get("ai_thinking", False)),
        )
    provider = provider_override or settings.default_provider
    model = model_override or settings.default_models.get(provider or "", "")
    return ResolvedCall(
        provider=provider,
        model=model,
        temperature=None,
        max_tokens=max_tokens_override if max_tokens_override is not None else 4096,
    )
