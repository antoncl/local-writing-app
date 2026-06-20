"""Abstract `ProviderProfile` + the dataclasses every concrete profile
returns. See [docs/ai-model-selection.md](../../../../../docs/ai-model-selection.md)
for the rationale and the conversation that fed it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal


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
    # Cost surfacing is v2; schema is in place so v2 doesn't need a migration.
    cost_in_per_mtok: float | None = None
    cost_out_per_mtok: float | None = None
    cache_read_multiplier: float | None = None


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
