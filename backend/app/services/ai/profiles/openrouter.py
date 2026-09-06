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
from app.services.ai.profiles.cache_strategy import (
    ANTHROPIC_BREAKPOINTS,
    GEMINI_BREAKPOINT,
    NO_CACHE,
    PREFIX_CACHE,
    CachePlan,
    CacheStrategy,
)
from app.services.ai.profiles.openai_compatible import OpenAICompatibleProfile

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings

log = logging.getLogger(__name__)


# Provider-prefix → cache strategy. Drawn from OpenRouter's caching guide
# (https://openrouter.ai/docs/guides/best-practices/prompt-caching).
# Prefix is the slash-separated leading segment of the OpenRouter model id.
_STRATEGY_BY_PREFIX: dict[str, CacheStrategy] = {
    "anthropic": ANTHROPIC_BREAKPOINTS,
    "alibaba": ANTHROPIC_BREAKPOINTS,
    "qwen": ANTHROPIC_BREAKPOINTS,       # alias used by some routes
    # Gemini: ONE marker (last breakpoint wins), no ttl, fixed 5-min term (ADR-0084 §3)
    "google": GEMINI_BREAKPOINT,
    "openai": PREFIX_CACHE,
    "deepseek": PREFIX_CACHE,
    "x-ai": PREFIX_CACHE,
    "xai": PREFIX_CACHE,
    "groq": PREFIX_CACHE,
    "moonshotai": PREFIX_CACHE,
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
        messages = list(openrouter_system_messages(self.cache_plan_for(call)))
        messages.extend(call.messages)
        return messages

    def _extra_body(self, call: ChatCall) -> dict:
        return openrouter_extra_body(call.session_id)

    # OpenRouter streams get a longer timeout and plain content handling.
    _stream_timeout = 300.0

    def _content_events(
        self, text: str, splitter: ThinkTagSplitter
    ) -> Iterator[StreamDelta | StreamThinking]:
        # Content stays PLAIN — no inline <think>-tag splitting. A route that
        # emits literal <think> markers in content must not have them re-parsed;
        # the splitter is intentionally unused. Reasoning is surfaced as thinking
        # by the inherited base handler (#1588), so a reasoning-only or truncated
        # turn is no longer a blank "Model returned empty output".
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

    def cache_strategy(self, model_id: str) -> CacheStrategy:
        if not model_id:
            return NO_CACHE
        prefix = model_id.split("/", 1)[0].lower()
        return _STRATEGY_BY_PREFIX.get(prefix, NO_CACHE)

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


def openrouter_system_messages(plan: CachePlan) -> list[dict]:
    """Render a `CachePlan` onto the OpenRouter `[system]` message list
    (ADR-0084 §5). Never inspects `tier` — the plan already decided which
    blocks carry a marker and what it says.

    In `markers` mode: one system message whose `content` is the block list,
    with `cache_control` attached where the plan set one. In `collapse` mode:
    one system message with the joined string. Returns [] when there's
    nothing to send. Pure — no network/SDK.
    """
    if not plan.blocks:
        return []
    if plan.mode == "markers":
        parts: list[dict] = []
        for block in plan.blocks:
            part: dict = {"type": "text", "text": block.text}
            if block.marker:
                part["cache_control"] = block.marker
            parts.append(part)
        return [{"role": "system", "content": parts}]
    collapsed = plan.collapsed_text()
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
    if _STRATEGY_BY_PREFIX.get(prefix, NO_CACHE).caches:
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
