"""Anthropic profile.

Live discovery via `/v1/models` confirms which model ids exist; tier +
cost data come from `_baked_in.yaml` (Anthropic doesn't publish pricing
on the models endpoint). When discovery fails (offline, bad key), fall
back to the bake-in catalogue alone.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import httpx

from app.services.ai.profiles._loader import baked_in_for, merge_live_catalogue
from app.services.ai.profiles.base import (
    CachingStyle,
    ChatCall,
    ChatOutcome,
    ModelDescriptor,
    ProviderError,
    ProviderProfile,
    StreamDelta,
    StreamFinal,
    StreamThinking,
    UsageMetrics,
    default_token_count,
    family_supports_temperature,
)
from app.services.ai.profiles.explicit_cache import TIER_TTL, cache_control_indices

# Default Anthropic extended-thinking budget when ai_thinking is enabled.
# Anthropic requires budget_tokens >= 1024 and budget_tokens < max_tokens.
_ANTHROPIC_THINKING_BUDGET = 1024

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings

log = logging.getLogger(__name__)


def _set_temperature(kwargs: dict, value: float) -> None:
    """Attach `temperature` to an Anthropic request.

    The anthropic 1.x SDK dropped `temperature` from the typed
    `messages.create`/`.stream` signatures, so passing it as a top-level kwarg
    raises `TypeError: unexpected keyword argument 'temperature'`. The endpoint
    still honours it on the families that allow sampling (Haiku 4.5, Sonnet/Opus
    4.6 and older), so it goes through the SDK's `extra_body` escape hatch. The
    families that 400 on it are filtered by `anthropic_supports_temperature`
    before we ever get here.
    """
    kwargs.setdefault("extra_body", {})["temperature"] = value


def anthropic_supports_temperature(model_id: str) -> bool:
    """Whether an Anthropic model accepts a `temperature` parameter.

    A thin module-level alias for the provider-neutral
    `family_supports_temperature` (base.py), so the send-path call sites here
    read in Anthropic terms without instantiating a profile (which would need
    an api_key). The no-sampling family list is single-sourced in base.py.
    """
    return family_supports_temperature(model_id)


class AnthropicProfile(ProviderProfile):
    name = "anthropic"
    display_name = "Anthropic"
    key_prefixes = ("sk-ant-",)
    live_catalog = True

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._cache: list[ModelDescriptor] | None = None

    def configured_key(self) -> str:
        return self._api_key

    @classmethod
    def from_settings(cls, settings: MachineSettings) -> AnthropicProfile:
        return cls(api_key=settings.providers.anthropic_api_key or "")

    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        if not force_refresh and self._cache is not None:
            return self._cache
        baked = baked_in_for("anthropic")
        if not self._api_key:
            # No key → can't discover, just use bake-in.
            self._cache = baked
            return baked
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Anthropic /v1/models failed (%s); using bake-in", exc)
            self._cache = baked
            return baked

        # Bake-in is the source of tier/cost truth; live confirms existence and
        # (ADR-0073 S4, live_catalog) surfaces models newer than the audit file
        # as unverified rows instead of hiding them.
        merged = merge_live_catalogue(
            "anthropic",
            baked,
            payload.get("data") or [],
            surface_live_only=self.live_catalog,
        )
        self._cache = merged
        return merged

    def caching_style(self, model_id: str) -> CachingStyle:
        # All current Anthropic models support explicit prompt caching via
        # `cache_control: ephemeral`. We don't gate per-model because every
        # production model in the bake-in supports it.
        return "explicit"

    def count_tokens(self, text: str, model_id: str) -> int:
        # Anthropic's SDK has an async count_tokens endpoint that's accurate
        # but requires a network roundtrip per call. Pre-send estimates want
        # a sync answer fast; cl100k_base is ~5-10% off for Claude but close
        # enough for budgeting. Swap to the SDK counter if accuracy becomes
        # a real complaint.
        return default_token_count(text)

    # supports_temperature is inherited from ProviderProfile — the base already
    # delegates to the same provider-neutral family rule, so no override here.

    def extract_usage(self, raw_response: Any, model_id: str) -> UsageMetrics:
        # Anthropic's response.usage:
        #   input_tokens (excludes cache reads/writes — fresh full-rate input)
        #   cache_creation_input_tokens (written this call — all TTLs)
        #   cache_read_input_tokens (served from cache, discounted)
        #   output_tokens
        # With the extended-cache-TTL beta the write total also breaks down by
        # TTL under `cache_creation` (`ephemeral_1h_input_tokens` /
        # `ephemeral_5m_input_tokens`). We read the 1h portion so `compute_cost`
        # can bill it at the higher premium (#814); absent (older SDK / no beta)
        # it stays 0 and every write bills at the 5m rate, as before.
        usage = getattr(raw_response, "usage", None)
        if usage is None:
            return UsageMetrics()
        breakdown = getattr(usage, "cache_creation", None)
        cache_write_1h = (
            int(getattr(breakdown, "ephemeral_1h_input_tokens", 0) or 0)
            if breakdown is not None
            else 0
        )
        return UsageMetrics(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            cached_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            cache_write_tokens_1h=cache_write_1h,
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )

    def _message_kwargs(self, call: ChatCall) -> dict:
        """The Anthropic `messages.create`/`messages.stream` kwargs shared by
        `chat` and `chat_stream`: model, token cap, messages, the gated
        temperature, and the system payload. Streaming layers `thinking` on top
        via `_apply_thinking`.
        """
        kwargs: dict = {
            "model": call.model,
            "max_tokens": call.max_tokens,
            "messages": call.messages,
        }
        # Only send temperature if the caller set one AND the model accepts
        # it. The model gate is a backstop for legacy assistants that pre-date
        # save-time validation; new incompatible combos are refused at save.
        if call.temperature is not None and anthropic_supports_temperature(call.model):
            _set_temperature(kwargs, call.temperature)
        # system_blocks (multi-block, per-block cache markers) overrides the
        # single-string system_prompt. Caller picks one or the other.
        if call.system_blocks:
            system_payload = anthropic_system_blocks(call.system_blocks)
            if system_payload:
                kwargs["system"] = system_payload
        elif call.system_prompt:
            kwargs["system"] = anthropic_system_with_cache(call.system_prompt)
        return kwargs

    def _apply_thinking(self, kwargs: dict, call: ChatCall) -> None:
        """Enable extended thinking on the streaming request, picking the mode the
        model's API generation accepts.

        The same 4.7+/5 families that dropped sampling (`NO_TEMPERATURE_FAMILIES`)
        also dropped the fixed-budget thinking mode: on them a
        `{"type": "enabled", "budget_tokens": N}` request is rejected with a 400,
        and adaptive thinking (the model paces its own depth) is the only on-mode.
        4.6 and older still take — in fact require, on 4.5/Haiku — the fixed budget,
        alongside the temperature=1 those models want when thinking is on. So the
        temperature gate doubles as the thinking-mode gate.
        """
        if anthropic_supports_temperature(call.model):
            # 4.6 and older: fixed-budget extended thinking + temperature=1.
            budget = max(1024, min(_ANTHROPIC_THINKING_BUDGET, call.max_tokens - 256))
            if budget < 1024:
                return
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            _set_temperature(kwargs, 1.0)
        else:
            # 4.7+/5: enabled+budget_tokens AND temperature both 400. Adaptive is
            # the only on-mode. Ask for a summary so the app's thinking surface
            # shows reasoning instead of a silent pause (default here is "omitted").
            kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}

    def chat(self, call: ChatCall) -> ChatOutcome:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderError(f"anthropic package not installed: {exc}") from exc

        client = Anthropic(api_key=self._api_key, timeout=120.0)
        response = client.messages.create(**self._message_kwargs(call))
        blocks = getattr(response, "content", None) or []
        parts = []
        for block in blocks:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        stop_reason = getattr(response, "stop_reason", None)
        return ChatOutcome("".join(parts), stop_reason, response)

    def health_ping(self, model: str) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderError(f"anthropic package not installed: {exc}") from exc

        client = Anthropic(api_key=self._api_key, timeout=15.0)
        client.messages.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )

    def _stream_text_events(
        self, event: Any
    ) -> Iterator[StreamDelta | StreamThinking]:
        """Map one Anthropic stream event to the text/thinking deltas we
        surface. Non-delta events (message start/stop, content-block
        boundaries) yield nothing.
        """
        if getattr(event, "type", None) != "content_block_delta":
            return
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

    def chat_stream(
        self, call: ChatCall
    ) -> Iterator[StreamDelta | StreamThinking | StreamFinal]:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderError(f"anthropic package not installed: {exc}") from exc

        client = Anthropic(api_key=self._api_key, timeout=120.0)
        kwargs = self._message_kwargs(call)
        if call.thinking_enabled:
            self._apply_thinking(kwargs, call)
        final_message: Any = None
        with client.messages.stream(**kwargs) as stream:
            for event in stream:
                yield from self._stream_text_events(event)
            final_message = stream.get_final_message()
        stop_reason = getattr(final_message, "stop_reason", None)
        usage = self.extract_usage(final_message, call.model)
        yield StreamFinal(stop_reason=stop_reason, usage=usage)


def anthropic_system_with_cache(system_prompt: str):
    """Wrap a single system prompt as one cacheable (stable-tier) content block —
    the single-block path for the plain-system-string case. A system prompt is the
    most stable content, so it caches at the stable (1h) ttl."""

    if not system_prompt:
        return ""
    return anthropic_system_blocks([{"text": system_prompt, "tier": "stable"}])


def anthropic_system_blocks(blocks: list[dict]):
    """Convert the shared volatility-ordered blocks into Anthropic's content-array.

    Each input block is `{"text": str, "tier": "stable"|"volatile"|None}` (ADR-0060
    §5): the shared layer carries only the volatility tier, never Anthropic's ttl or
    breakpoint vocabulary. The adapter-side mapping (`explicit_cache`) turns a tier
    into a `cache_control` ephemeral marker at the tier's ttl (`stable` → 1h,
    `volatile` → 5m) and enforces Anthropic's ≤4-marker cap; a block with no tier,
    or beyond the cap, gets none. Anthropic caches the prefix UP TO each marker, so
    markers between stable sections let later turns reuse the cached prefix up to
    the last unchanged marker.

    Empty blocks (no text) are dropped. Empty input returns "" so the caller can
    skip the `system` kwarg entirely.
    """

    if not blocks:
        return ""
    budget = cache_control_indices(blocks)
    out: list[dict] = []
    for i, block in enumerate(blocks):
        text = block.get("text") or ""
        if not text:
            continue
        sdk_block: dict = {"type": "text", "text": text}
        if i in budget:
            sdk_block["cache_control"] = {
                "type": "ephemeral",
                "ttl": TIER_TTL[block["tier"]],
            }
        out.append(sdk_block)
    return out if out else ""
