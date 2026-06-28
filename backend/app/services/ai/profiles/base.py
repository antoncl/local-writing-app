"""Abstract `ProviderProfile` + the dataclasses every concrete profile
returns. See [docs/ai-model-selection.md](../../../../../docs/ai-model-selection.md)
for the rationale and the conversation that fed it.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Literal

log = logging.getLogger(__name__)


class CapabilityTier(str, Enum):
    """High-level model picker: what the user picks before names.

    Cloud providers expose FAST/BALANCED/PREMIUM/REASONING; Ollama is
    LOCAL-only (no auto-rank within local since everything is free).
    """

    FAST = "fast"
    BALANCED = "balanced"
    PREMIUM = "premium"
    REASONING = "reasoning"
    LOCAL = "local"


class Capability(str, Enum):
    """Per-model flags. Drives Advanced disclosure surfacing later."""

    VISION = "vision"
    TOOLS = "tools"
    THINKING = "thinking"
    CACHING = "caching"


CachingStyle = Literal["none", "auto", "explicit"]
"""How the dispatch layer should mark cacheable content for a given model.

- `none`: provider does not cache; no markup
- `auto`: provider caches transparently (most OpenRouter routes, OpenAI direct)
- `explicit`: wrap stable content with `cache_control: ephemeral` (Anthropic
  direct, Anthropic/Alibaba/Gemini via OpenRouter)
"""


@dataclass
class ModelDescriptor:
    """One row in a provider's catalogue. Fields that are unknown at
    discovery time (e.g. pricing for providers that don't publish it) stay
    None; v1 tolerates this and falls back to bake-in data.
    """

    id: str
    display_name: str
    provider: str
    context_window: int
    tier: CapabilityTier
    capabilities: set[Capability] = field(default_factory=set)
    deprecated: bool = False
    sunset_date: date | None = None
    successor: str | None = None
    cost_in_per_mtok: float | None = None
    cost_out_per_mtok: float | None = None
    cache_read_multiplier: float | None = None


@dataclass
class UsageMetrics:
    """Normalized per-call token counts. Each provider parses its own
    response shape into this; `compute_cost` consumes it alongside a
    `ModelDescriptor` to produce USD.

    `input_tokens` is non-cached input billed at full rate.
    `cached_input_tokens` are input tokens served from cache (discounted
    by `cache_read_multiplier`). `cache_write_tokens` are input tokens
    written to the cache this call (a small premium on Anthropic; 0
    elsewhere). The three slots are disjoint — sum them for total input.
    """

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0


# Anthropic's 5min-TTL cache-write premium is 1.25x input rate; 1hour is 2x.
# We bake in the conservative 5min default — overestimating writes is safer
# than underestimating, and explicit-TTL refinement can come later when the
# UI actually distinguishes them.
_CACHE_WRITE_MULTIPLIER = 1.25


def compute_cost(usage: UsageMetrics, descriptor: ModelDescriptor) -> float:
    """USD cost for one call, computed from descriptor pricing.

    Returns 0.0 when the descriptor has no pricing (Ollama, or live
    discovery failed to supply prices). Caller should freeze the
    returned value into their accumulator — recomputing later would
    drift when the model's listed price changes.
    """

    cost_in = (descriptor.cost_in_per_mtok or 0.0) / 1_000_000
    cost_out = (descriptor.cost_out_per_mtok or 0.0) / 1_000_000
    if cost_in == 0.0 and cost_out == 0.0:
        return 0.0
    cache_read_mult = (
        descriptor.cache_read_multiplier
        if descriptor.cache_read_multiplier is not None
        else 1.0
    )
    return (
        usage.input_tokens * cost_in
        + usage.cached_input_tokens * cost_in * cache_read_mult
        + usage.cache_write_tokens * cost_in * _CACHE_WRITE_MULTIPLIER
        + usage.output_tokens * cost_out
    )


_TIKTOKEN_ENCODER = None
_TIKTOKEN_TRIED = False


def _tiktoken_encoder():
    global _TIKTOKEN_ENCODER, _TIKTOKEN_TRIED
    if _TIKTOKEN_TRIED:
        return _TIKTOKEN_ENCODER
    _TIKTOKEN_TRIED = True
    try:
        import tiktoken
    except ImportError:
        log.warning("tiktoken unavailable; token counts use char/4 approximation")
        return None
    _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
    return _TIKTOKEN_ENCODER


def default_token_count(text: str) -> int:
    """Universal fallback token estimator — cl100k_base via tiktoken,
    or character/4 when tiktoken isn't installed. Providers without a
    native tokenizer call this from their `count_tokens`.
    """

    if not text:
        return 0
    encoder = _tiktoken_encoder()
    if encoder is None:
        return max(1, len(text) // 4)
    return len(encoder.encode(text))


class ProviderProfile(ABC):
    """One per provider. Concrete implementations live in sibling modules
    (anthropic.py, openai.py, openrouter.py, ollama.py)."""

    name: str
    display_name: str

    @abstractmethod
    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        """Return the provider's model catalogue. Implementations should
        prefer live discovery and fall back to bake-in data on failure.

        `force_refresh=True` bypasses any in-memory cache the implementation
        keeps; disk-cache invalidation lives in `profile_cache.py`.
        """

    @abstractmethod
    def caching_style(self, model_id: str) -> CachingStyle:
        """Tell the dispatch layer how to mark cacheable content for this
        model. See `CachingStyle` for the contract."""

    @abstractmethod
    def count_tokens(self, text: str, model_id: str) -> int:
        """Estimate tokens for `text` under `model_id`. Pre-send only —
        actuals come back via `extract_usage` on the response.

        Doesn't have to be exact; powers the cost-estimate panel.
        Providers without a native tokenizer should call
        `default_token_count` for a tiktoken-cl100k_base fallback.
        """

    @abstractmethod
    def extract_usage(self, raw_response: Any, model_id: str) -> UsageMetrics:
        """Parse the provider's response object into normalized usage.

        Each provider knows the shape of its own SDK response. Missing
        fields default to 0 — never raise on a malformed `usage` block.
        """

    def supports_temperature(self, model_id: str) -> bool:
        """Whether the model accepts a `temperature` parameter on the
        request. Default True — override for models that 400 on it (e.g.
        Anthropic's Opus 4.7+ deprecates the param). Call sites should
        omit `temperature` from the request kwargs when this returns False.
        """
        return True

    def requires_temperature(self, model_id: str) -> bool:
        """Whether the model's API rejects requests that omit `temperature`.
        Default False — most APIs supply a sensible server-side default
        when the parameter is absent. Override only for models that 400
        on missing temp. Save-time validation refuses assistants without
        an explicit temperature when this returns True for their model.
        """
        return False

    def model_for_tier(
        self, tier: CapabilityTier, models: list[ModelDescriptor]
    ) -> str | None:
        """Default tier resolver: cheapest non-deprecated model in tier.

        Tie-break: highest `context_window`, then descriptor list order.
        Subclasses can override (e.g. Ollama returns None — no auto-rank
        for local models; the picker shows the explicit list).
        """

        candidates = [
            m
            for m in models
            if m.tier == tier and not m.deprecated
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda m: (
                m.cost_in_per_mtok if m.cost_in_per_mtok is not None else float("inf"),
                -m.context_window,
            )
        )
        return candidates[0].id
