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

import httpx

from app.services.ai.profiles._loader import baked_in_for
from app.services.ai.profiles.base import (
    CachingStyle,
    Capability,
    CapabilityTier,
    ModelDescriptor,
    ProviderProfile,
)


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


class OpenRouterProfile(ProviderProfile):
    name = "openrouter"
    display_name = "OpenRouter"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._cache: list[ModelDescriptor] | None = None

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
        # Filter out null-pricing rows (free-tier promo entries that don't
        # map cleanly to a tier).
        descriptors = [d for d in descriptors if d.cost_in_per_mtok is not None]
        self._cache = descriptors
        return descriptors

    def caching_style(self, model_id: str) -> CachingStyle:
        return caching_style_for_model(model_id)


def caching_style_for_model(model_id: str) -> CachingStyle:
    """Module-level helper so the chat dispatcher can branch without
    instantiating a ProviderProfile. Mirrors the prefix lookup the
    OpenRouterProfile.caching_style method does."""
    if not model_id:
        return "none"
    prefix = model_id.split("/", 1)[0].lower()
    return _CACHING_BY_PREFIX.get(prefix, "none")


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
    )


def _per_mtok(raw) -> float | None:
    """OpenRouter prices are USD per token as a string. Convert to USD
    per 1M tokens, or None when missing/zero."""

    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
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

    lower = model_id.lower()
    if Capability.THINKING in capabilities:
        return CapabilityTier.REASONING
    # ID-based heuristics for reasoning markers OpenRouter doesn't flag.
    if any(token in lower for token in ("/o1", "/o3", "thinking", "fable")):
        return CapabilityTier.REASONING
    if cost_in is None:
        return CapabilityTier.BALANCED
    if cost_in < 1.0:
        return CapabilityTier.FAST
    if cost_in < 5.0:
        return CapabilityTier.BALANCED
    return CapabilityTier.PREMIUM
