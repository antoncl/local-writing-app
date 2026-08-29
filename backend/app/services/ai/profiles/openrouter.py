"""OpenRouter profile — the meta-provider.

Unlike Anthropic/OpenAI, OpenRouter publishes pricing, context window,
and capability flags on its `/api/v1/models` endpoint. Live data is the
source of truth; bake-in is just a tiny offline seed.

Tier and caching style are derived from the live data (cost buckets +
provider-prefix heuristic) since OpenRouter doesn't publish either
directly. The heuristics are intentionally conservative — wrong tier
just shows the wrong model name in the default picker, which the user
can override under Advanced.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import httpx

from app.services.ai.profiles._loader import baked_in_for, looks_like_reasoning
from app.services.ai.profiles.base import (
    CachingStyle,
    Capability,
    CapabilityTier,
    ChatCall,
    ModelDescriptor,
    StreamDelta,
    StreamThinking,
    ThinkTagSplitter,
    UsageMetrics,
    default_token_count,
)
from app.services.ai.profiles.explicit_cache import TIER_TTL, cache_control_indices
from app.services.ai.profiles.openai_compatible import OpenAICompatibleProfile

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings

log = logging.getLogger(__name__)


# Provider-prefix → caching style. Drawn from OpenRouter's caching guide
# (https://openrouter.ai/docs/guides/best-practices/prompt-caching).
# Prefix is the slash-separated leading segment of the OpenRouter model id.
_CACHING_BY_PREFIX: dict[str, CachingStyle] = {
    "anthropic": "explicit",
    "alibaba": "explicit",
    "qwen": "explicit",       # alias used by some routes
    "google": "explicit",     # Gemini 2.5 needs explicit breakpoints
    "openai": "auto",
    "deepseek": "auto",
    "x-ai": "auto",
    "xai": "auto",
    "groq": "auto",
    "moonshotai": "auto",
}


class OpenRouterProfile(OpenAICompatibleProfile):
    name = "openrouter"
    display_name = "OpenRouter"
    key_prefixes = ("sk-or-",)
    live_catalog = True

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._cache: list[ModelDescriptor] | None = None

    @classmethod
    def from_settings(cls, settings: MachineSettings) -> OpenRouterProfile:
        return cls(api_key=settings.providers.openrouter_api_key or "")

    def _chat_base_url(self) -> str:
        return "https://openrouter.ai/api/v1"

    def _build_messages(self, call: ChatCall) -> list[dict]:
        # Pass Anthropic-style cache_control markers through to routes that
        # cache explicitly; collapse to a plain string otherwise.
        messages = list(
            openrouter_system_messages(
                call.system_prompt,
                call.system_blocks,
                self.caching_style(call.model),
            )
        )
        messages.extend(call.messages)
        return messages

    def _extra_body(self, call: ChatCall) -> dict:
        return openrouter_extra_body(call.session_id)

    # OpenRouter streams get a longer timeout and plain content handling.
    _stream_timeout = 300.0

    def _stream_delta_events(
        self, delta: Any, splitter: ThinkTagSplitter
    ) -> Iterator[StreamDelta | StreamThinking]:
        # Surface a structured `reasoning` field as thinking. Reasoning routes
        # (deepseek-v4-pro and others) stream their chain-of-thought here, and
        # some spend the whole token budget reasoning before any content — so
        # dropping it turned a reasoning-only or truncated turn into a blank
        # "Model returned empty output" (#1588). Content stays PLAIN — no inline
        # <think>-tag splitting — which is the one property the original
        # content-only override protected (a route that emits literal <think>
        # markers in content must not have them re-parsed). The splitter stays
        # unused; that deliberate divergence from the base handler is preserved.
        if delta is None:
            return
        reasoning = (
            getattr(delta, "reasoning", None)
            or getattr(delta, "reasoning_content", None)
        )
        if reasoning:
            yield StreamThinking(text=reasoning)
        text = getattr(delta, "content", None)
        if text:
            yield StreamDelta(text=text)

    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        if not force_refresh and self._cache is not None:
            return self._cache
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                # The /api/v1/models endpoint is public — no auth required —
                # but pass the key when we have one so OpenRouter can scope
                # to the user's available models (some routes are gated).
                headers = {}
                if self._api_key:
                    headers["Authorization"] = f"Bearer {self._api_key}"
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("OpenRouter /api/v1/models failed (%s); using bake-in", exc)
            baked = baked_in_for("openrouter")
            self._cache = baked
            return baked

        descriptors = [
            _row_to_descriptor(row) for row in payload.get("data") or []
        ]
        # Drop only rows with no usable input price (missing/unparseable — they
        # can't be tiered). Genuinely free models (price "0" → 0.0) are kept:
        # `0.0 is not None` (#1386).
        descriptors = [d for d in descriptors if d.cost_in_per_mtok is not None]
        self._cache = descriptors
        return descriptors

    def caching_style(self, model_id: str) -> CachingStyle:
        return caching_style_for_model(model_id)

    def count_tokens(self, text: str, model_id: str) -> int:
        # OpenRouter routes to many providers; cl100k_base is wrong for
        # most non-OpenAI ones but in the same ballpark. Accurate per-route
        # tokenization would mean shipping every vendor's tokenizer.
        return default_token_count(text)

    def extract_usage(self, raw_response: Any, model_id: str) -> UsageMetrics:
        # OpenRouter normalizes to OpenAI shape; Anthropic routes additionally
        # surface cache_creation_input_tokens / cache_read_input_tokens at the
        # usage level. Prefer the Anthropic-style split when present since it
        # distinguishes reads from writes.
        usage = getattr(raw_response, "usage", None)
        if usage is None:
            return UsageMetrics()
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        if cache_read or cache_write:
            return UsageMetrics(
                input_tokens=max(0, prompt_tokens - cache_read - cache_write),
                cached_input_tokens=cache_read,
                cache_write_tokens=cache_write,
                output_tokens=completion_tokens,
            )
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        return UsageMetrics(
            input_tokens=max(0, prompt_tokens - cached),
            cached_input_tokens=cached,
            output_tokens=completion_tokens,
        )


def caching_style_for_model(model_id: str) -> CachingStyle:
    """Module-level helper so the streaming dispatcher can branch without
    instantiating a ProviderProfile. Mirrors the prefix lookup the
    OpenRouterProfile.caching_style method does."""
    if not model_id:
        return "none"
    prefix = model_id.split("/", 1)[0].lower()
    return _CACHING_BY_PREFIX.get(prefix, "none")


def openrouter_system_messages(
    system_prompt: str,
    system_blocks: list[dict] | None,
    caching_style: str,
) -> list[dict]:
    """Build the [system] message list for an OpenRouter chat call.

    OpenRouter accepts Anthropic-style `cache_control` markers on individual
    content blocks when the routed-to provider needs them explicitly
    (anthropic/google/qwen). For auto-cache providers (openai/deepseek/grok)
    markers are ignored, so we collapse to a plain string to keep the wire
    small. Returns [] when there's nothing to send. Pure — no network/SDK.

    ADR-0060 §5: the shared blocks carry only `{text, tier}`; the explicit routes
    are the Anthropic family, so this uses the shared `explicit_cache` mapping
    (tier → cache_control ttl, ≤4-marker cap) — the same translation the Anthropic
    adapter uses.
    """
    if system_blocks and caching_style == "explicit":
        budget = cache_control_indices(system_blocks)
        parts: list[dict] = []
        for i, block in enumerate(system_blocks):
            text = block.get("text") or ""
            if not text:
                continue
            part: dict = {"type": "text", "text": text}
            if i in budget:
                part["cache_control"] = {
                    "type": "ephemeral",
                    "ttl": TIER_TTL[block["tier"]],
                }
            parts.append(part)
        if parts:
            return [{"role": "system", "content": parts}]
        return []
    # caching_style != "explicit": collapse blocks to a single string
    # (auto-cache providers index on prefix bytes, no markers needed;
    # "none" providers don't cache anyway). The blocks already include the
    # system prompt as their first block, so when present they are the whole
    # system message — collapse ALL of them, not just fall back to the bare
    # `system_prompt` (which would silently drop the lore + every later block
    # on auto-cache providers like deepseek/openai/grok).
    collapsed = system_prompt
    if system_blocks:
        collapsed = (
            "\n\n".join(b.get("text", "") for b in system_blocks if b.get("text"))
            or system_prompt
        )
    if not collapsed:
        return []
    return [{"role": "system", "content": collapsed}]


def openrouter_extra_body(session_id: str | None) -> dict:
    """OpenRouter-specific fields outside the standard chat-completions
    schema. Currently just `session_id` for provider stickiness — pinning a
    chat to one underlying provider so the cache prefix stays valid across
    turns. See https://openrouter.ai/docs/guides/best-practices/prompt-caching
    """
    extra: dict = {}
    if session_id:
        extra["session_id"] = session_id
    return extra


def _row_to_descriptor(row: dict) -> ModelDescriptor:
    model_id = str(row.get("id") or "")
    name = str(row.get("name") or model_id)
    context_window = int(row.get("context_length") or 0)
    pricing = row.get("pricing") or {}
    cost_in = _per_mtok(pricing.get("prompt"))
    cost_out = _per_mtok(pricing.get("completion"))
    arch = row.get("architecture") or {}
    modalities = {str(m).lower() for m in arch.get("input_modalities") or []}
    supported = {str(p).lower() for p in row.get("supported_parameters") or []}
    capabilities: set[Capability] = set()
    if "image" in modalities:
        capabilities.add(Capability.VISION)
    if "tools" in supported or "tool_choice" in supported:
        capabilities.add(Capability.TOOLS)
    if "reasoning" in supported or "include_reasoning" in supported:
        capabilities.add(Capability.THINKING)
    # OpenRouter doesn't expose a "caches" flag — infer from the prefix
    # heuristic. Anything we route to a known-cacheable provider gets
    # the capability flag for picker hints.
    prefix = model_id.split("/", 1)[0].lower()
    if _CACHING_BY_PREFIX.get(prefix, "none") != "none":
        capabilities.add(Capability.CACHING)
    return ModelDescriptor(
        id=model_id,
        display_name=name,
        provider="openrouter",
        context_window=context_window,
        tier=_tier_from_cost_and_id(cost_in, model_id, capabilities),
        capabilities=capabilities,
        cost_in_per_mtok=cost_in,
        cost_out_per_mtok=cost_out,
        # OpenRouter publishes the accepted params per route; honour that as the
        # provider signal. The family rule (`accepts_temperature`) still overrides
        # it, so a no-sampling `anthropic/…` route is read-only even if the list
        # happens to include `temperature` (#1554).
        supports_temperature="temperature" in supported,
    )


def _per_mtok(raw) -> float | None:
    """OpenRouter prices are USD per token as a string. Convert to USD per 1M
    tokens.

    Returns `0.0` for a genuinely **free** model (OpenRouter reports its `:free`
    routes with price "0") so the caller can keep it, and `None` only when the
    price is missing or unparseable. This distinction matters: free models are
    among the most useful options for a local-first, cost-conscious user, so
    conflating "free" with "unknown" — and dropping both — hid them (#1386).
    """

    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value * 1_000_000


def _tier_from_cost_and_id(
    cost_in: float | None,
    model_id: str,
    capabilities: set[Capability],
) -> CapabilityTier:
    """Cost-bucketed tier with a REASONING override for thinking models.

    OpenRouter doesn't publish tiers; this is a pragmatic bucketing.
    Wrong-tier classification just shows a different model under the
    default tier picker; users can override in Advanced. Buckets:

    - <$1/Mtok input → FAST
    - $1-$5/Mtok    → BALANCED
    - $5-$30/Mtok   → PREMIUM
    - thinking-capable models always bucket to REASONING regardless
      of cost (some are cheap, e.g. o3-mini).
    """

    if Capability.THINKING in capabilities:
        return CapabilityTier.REASONING
    # ID-based heuristics for reasoning markers OpenRouter doesn't flag (shared
    # with the S4 live-only tier so both agree on what "looks like reasoning").
    if looks_like_reasoning(model_id):
        return CapabilityTier.REASONING
    if cost_in is None:
        return CapabilityTier.BALANCED
    if cost_in < 1.0:
        return CapabilityTier.FAST
    if cost_in < 5.0:
        return CapabilityTier.BALANCED
    return CapabilityTier.PREMIUM
