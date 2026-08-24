"""ADR-0073 S4 — the shared catalogue merge: bake-in stays the tier/cost truth,
live confirms existence, and (when the provider's live catalogue is
authoritative) live-only models are surfaced unverified instead of dropped."""

from app.services.ai.profiles._loader import (
    looks_like_reasoning,
    merge_live_catalogue,
    tier_for_unpriced,
)
from app.services.ai.profiles.base import CapabilityTier, ModelDescriptor


def _baked(model_id: str, *, tier: CapabilityTier = CapabilityTier.BALANCED) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        display_name=model_id,
        provider="anthropic",
        context_window=200000,
        tier=tier,
        cost_in_per_mtok=3.0,
    )


class TestLooksLikeReasoning:
    def test_matches_slash_o_series_and_keywords(self) -> None:
        assert looks_like_reasoning("openai/o3-mini")
        assert looks_like_reasoning("anthropic/claude-thinking")
        assert looks_like_reasoning("some/fable-model")

    def test_plain_model_is_not_reasoning(self) -> None:
        assert not looks_like_reasoning("anthropic/claude-3.5-sonnet")
        assert not looks_like_reasoning("gpt-4o")


class TestTierForUnpriced:
    def test_reasoning_id_buckets_reasoning(self) -> None:
        assert tier_for_unpriced("openai/o1-preview") == CapabilityTier.REASONING

    def test_plain_id_defaults_balanced(self) -> None:
        assert tier_for_unpriced("gpt-5-turbo") == CapabilityTier.BALANCED


class TestMergeLiveCatalogue:
    def test_baked_present_live_is_kept_verified(self) -> None:
        merged = merge_live_catalogue(
            "anthropic", [_baked("a")], [{"id": "a"}], surface_live_only=True
        )
        assert [m.id for m in merged] == ["a"]
        assert merged[0].verified is True
        assert merged[0].deprecated is False

    def test_baked_missing_from_live_is_deprecated_not_dropped(self) -> None:
        merged = merge_live_catalogue(
            "anthropic", [_baked("a")], [{"id": "b"}], surface_live_only=True
        )
        by_id = {m.id: m for m in merged}
        assert by_id["a"].deprecated is True
        assert by_id["b"].verified is False  # live-only surfaced

    def test_live_only_dropped_when_not_authoritative(self) -> None:
        # A provider whose live catalogue is NOT authoritative keeps bake-in only.
        merged = merge_live_catalogue(
            "anthropic", [_baked("a")], [{"id": "a"}, {"id": "b"}], surface_live_only=False
        )
        assert [m.id for m in merged] == ["a"]

    def test_baked_wins_on_id_collision(self) -> None:
        # A live row sharing a baked id does not duplicate or override it.
        merged = merge_live_catalogue(
            "anthropic",
            [_baked("a", tier=CapabilityTier.PREMIUM)],
            [{"id": "a"}, {"id": "b"}],
            surface_live_only=True,
        )
        by_id = {m.id: m for m in merged}
        assert len(merged) == 2
        assert by_id["a"].tier == CapabilityTier.PREMIUM  # baked metadata kept
        assert by_id["a"].verified is True

    def test_live_only_order_preserved(self) -> None:
        merged = merge_live_catalogue(
            "anthropic",
            [],
            [{"id": "b"}, {"id": "a"}, {"id": "c"}],
            surface_live_only=True,
        )
        assert [m.id for m in merged] == ["b", "a", "c"]

    def test_live_only_uses_live_display_name_then_falls_back_to_id(self) -> None:
        merged = merge_live_catalogue(
            "anthropic",
            [],
            [{"id": "x-1", "display_name": "Fancy"}, {"id": "x-2"}],
            surface_live_only=True,
        )
        by_id = {m.id: m for m in merged}
        assert by_id["x-1"].display_name == "Fancy"
        assert by_id["x-2"].display_name == "x-2"
