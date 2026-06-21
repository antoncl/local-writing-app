"""Smoke tests for the AI provider-profile foundation: bake-in YAML
parses, dataclass round-trips, default tier resolver picks the cheapest
non-deprecated model, Ollama key exists even when empty.
"""

from __future__ import annotations

from app.services.ai.profiles import (
    Capability,
    CapabilityTier,
    ModelDescriptor,
)
from app.services.ai.profiles._loader import (
    baked_in_catalogue,
    baked_in_for,
)
from app.services.ai.profiles.base import ProviderProfile


class _DummyProfile(ProviderProfile):
    """Minimal concrete profile so we can exercise the default
    `model_for_tier` resolver without depending on a real provider."""

    name = "dummy"
    display_name = "Dummy"

    async def list_models(self, *, force_refresh: bool = False):
        return []

    def caching_style(self, model_id: str):
        return "none"

    def count_tokens(self, text: str, model_id: str) -> int:
        return len(text)

    def extract_usage(self, raw_response, model_id: str):
        from app.services.ai.profiles.base import UsageMetrics
        return UsageMetrics()


def test_baked_in_parses_for_all_expected_providers():
    catalogue = baked_in_catalogue()
    assert {"anthropic", "openai", "openrouter", "ollama"} <= set(catalogue.keys())


def test_anthropic_bakein_has_sonnet_and_haiku():
    rows = baked_in_for("anthropic")
    ids = {r.id for r in rows}
    assert "claude-sonnet-4-6" in ids
    assert "claude-haiku-4-5-20251001" in ids
    # Provider field is set from the YAML key, not duplicated per row.
    assert all(r.provider == "anthropic" for r in rows)


def test_ollama_bakein_is_empty_but_present():
    # The key exists even though Ollama has no bake-in models — the list
    # is discovered live from the local Ollama install.
    assert baked_in_for("ollama") == []


def test_tier_resolver_picks_cheapest_in_tier():
    profile = _DummyProfile()
    descriptors = [
        ModelDescriptor(
            id="cheap",
            display_name="Cheap",
            provider="dummy",
            context_window=8000,
            tier=CapabilityTier.BALANCED,
            cost_in_per_mtok=1.0,
        ),
        ModelDescriptor(
            id="expensive",
            display_name="Expensive",
            provider="dummy",
            context_window=200000,
            tier=CapabilityTier.BALANCED,
            cost_in_per_mtok=10.0,
        ),
        ModelDescriptor(
            id="fast-other-tier",
            display_name="Other",
            provider="dummy",
            context_window=8000,
            tier=CapabilityTier.FAST,
            cost_in_per_mtok=0.1,
        ),
    ]
    assert profile.model_for_tier(CapabilityTier.BALANCED, descriptors) == "cheap"


def test_tier_resolver_skips_deprecated():
    profile = _DummyProfile()
    descriptors = [
        ModelDescriptor(
            id="cheap-deprecated",
            display_name="Cheap (EOL)",
            provider="dummy",
            context_window=8000,
            tier=CapabilityTier.BALANCED,
            cost_in_per_mtok=0.5,
            deprecated=True,
        ),
        ModelDescriptor(
            id="cheap-current",
            display_name="Cheap (current)",
            provider="dummy",
            context_window=8000,
            tier=CapabilityTier.BALANCED,
            cost_in_per_mtok=2.0,
        ),
    ]
    assert profile.model_for_tier(CapabilityTier.BALANCED, descriptors) == "cheap-current"


def test_tier_resolver_returns_none_when_tier_empty():
    profile = _DummyProfile()
    descriptors = [
        ModelDescriptor(
            id="only-fast",
            display_name="Only Fast",
            provider="dummy",
            context_window=8000,
            tier=CapabilityTier.FAST,
            cost_in_per_mtok=0.1,
        )
    ]
    assert profile.model_for_tier(CapabilityTier.PREMIUM, descriptors) is None


def test_tier_resolver_tiebreaks_on_context_window():
    # Same price, different context — bigger context wins as tie-break.
    profile = _DummyProfile()
    descriptors = [
        ModelDescriptor(
            id="small-ctx",
            display_name="Small ctx",
            provider="dummy",
            context_window=32000,
            tier=CapabilityTier.BALANCED,
            cost_in_per_mtok=2.0,
        ),
        ModelDescriptor(
            id="big-ctx",
            display_name="Big ctx",
            provider="dummy",
            context_window=200000,
            tier=CapabilityTier.BALANCED,
            cost_in_per_mtok=2.0,
        ),
    ]
    assert profile.model_for_tier(CapabilityTier.BALANCED, descriptors) == "big-ctx"


def test_descriptor_carries_caching_capability_for_anthropic_models():
    rows = baked_in_for("anthropic")
    sonnet = next(r for r in rows if r.id == "claude-sonnet-4-6")
    assert Capability.CACHING in sonnet.capabilities
