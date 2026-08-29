"""Call-parameter resolution (#178 slice 2).

Resolve provider / model / temperature / max_tokens for an AI request from the
override → assistant-metadata → settings-default priority chain. Extracted from
the HTTP layer as a free function taking the project service, matching the
`services/ai/` style (`build_preview`, `expand_context`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.ai.assistant_validation import coerce_optional_temperature
from app.services.ai.profiles.base import ChatCall

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings
    from app.services.project_service import ProjectService

# Default per-request output-token cap when neither the request nor the assistant
# sets one. Generous because the chat send path streams (large outputs don't risk
# HTTP timeouts) and reasoning models spend part of the budget thinking before
# they answer — a 4096 default let them exhaust it mid-thought and return nothing
# (#1591). Always clamped down to the model's own max output (`_model_max_output`)
# so raising the floor can't 400 a model with a smaller ceiling.
DEFAULT_MAX_TOKENS = 32768


# A trailing dated-snapshot suffix — OpenAI's `-YYYY-MM-DD`
# (`gpt-4o-2024-08-06`) or Anthropic's `-YYYYMMDD` (`claude-haiku-4-5-20251001`).
_MODEL_DATE_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")


def _normalize_model_id(model_id: str) -> str:
    """Drop a trailing dated-snapshot suffix so a dated id matches its baked base
    entry: `gpt-4o-2024-08-06` → `gpt-4o`, `claude-haiku-4-5-20251001` →
    `claude-haiku-4-5`. Without this, a dated id the picker surfaces (OpenAI's
    live catalogue includes them) escapes the clamp and 400s at the raised
    floor (#1591). Distinct base models (`gpt-4o` vs `gpt-4o-mini`) are unaffected
    — neither carries a date, so normalization is identity for them."""
    return _MODEL_DATE_SUFFIX.sub("", model_id.strip().lower())


def _model_max_output(provider: str, model: str) -> int | None:
    """The model's published max output tokens from the baked catalogue — the
    audited source for Anthropic/OpenAI, the only providers that 400 when
    max_tokens exceeds the model's ceiling. Matches on the date-normalized id so
    a dated snapshot resolves to its base entry. None (a live-only OpenRouter
    route, Ollama, or an un-audited model) means 'unknown', and the caller keeps
    the desired value — safe for OpenRouter (clamps server-side) and Ollama
    (never errors)."""
    from app.services.ai.profiles._loader import baked_in_for

    target = _normalize_model_id(model)
    for descriptor in baked_in_for(provider):
        if _normalize_model_id(descriptor.id) == target:
            return descriptor.max_output_tokens
    return None


def _clamp_to_model_max(desired: int, provider: str, model: str) -> int:
    """Cap `desired` at the model's max output when known; a 0/None cap (unknown)
    leaves it untouched. Applies to explicit overrides too — a hand-set value
    above a model's ceiling should be reduced, not 400'd."""
    cap = _model_max_output(provider, model)
    return min(desired, cap) if cap else desired


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
                max_tokens = int(meta.get("ai_max_tokens", DEFAULT_MAX_TOKENS))
            except (TypeError, ValueError):
                max_tokens = DEFAULT_MAX_TOKENS
        return ResolvedCall(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=_clamp_to_model_max(max_tokens, provider, model),
            thinking_enabled=bool(meta.get("ai_thinking", False)),
        )
    provider = provider_override or settings.default_provider
    model = model_override or settings.default_models.get(provider or "", "")
    desired = max_tokens_override if max_tokens_override is not None else DEFAULT_MAX_TOKENS
    return ResolvedCall(
        provider=provider,
        model=model,
        temperature=None,
        max_tokens=_clamp_to_model_max(desired, provider, model),
    )
