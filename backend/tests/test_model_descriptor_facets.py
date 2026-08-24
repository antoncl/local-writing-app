"""ADR-0073 S3 — the id-derived `family`/`free` facets the model-picker View
groups and badges on, and their wire mirror."""

from app.routers.ai import _descriptor_to_wire
from app.services.ai.profiles.base import (
    CapabilityTier,
    ModelDescriptor,
    family_from_id,
)


def _desc(model_id: str, cost: float | None = 1.0) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        display_name=model_id,
        provider="openrouter",
        context_window=128000,
        tier=CapabilityTier.BALANCED,
        cost_in_per_mtok=cost,
    )


class TestFamilyFromId:
    def test_slash_namespaced_groups_by_vendor(self) -> None:
        assert family_from_id("qwen/qwen-2.5-72b") == "qwen"
        assert family_from_id("anthropic/claude-3.5-sonnet") == "anthropic"

    def test_native_id_groups_by_leading_token(self) -> None:
        assert family_from_id("claude-3-5-sonnet-20241022") == "claude"
        assert family_from_id("gpt-4o") == "gpt"
        assert family_from_id("o3") == "o"

    def test_case_folded(self) -> None:
        assert family_from_id("Qwen/Qwen-2.5") == "qwen"


class TestDescriptorFacets:
    def test_family_is_id_derived(self) -> None:
        assert _desc("qwen/qwen-2.5-72b").family == "qwen"

    def test_free_when_zero_priced(self) -> None:
        assert _desc("qwen/qwen-2.5-72b:free", cost=0.0).free is True

    def test_not_free_when_priced(self) -> None:
        assert _desc("anthropic/claude-3.5-sonnet", cost=3.0).free is False

    def test_not_free_when_price_unknown(self) -> None:
        # Unknown pricing (a provider that doesn't publish it, or local Ollama)
        # is not "free" — only an explicit 0 is.
        assert _desc("ollama/llama3", cost=None).free is False


def test_wire_carries_family_and_free() -> None:
    wire = _descriptor_to_wire(_desc("qwen/qwen-2.5-72b:free", cost=0.0))
    assert wire.family == "qwen"
    assert wire.free is True
