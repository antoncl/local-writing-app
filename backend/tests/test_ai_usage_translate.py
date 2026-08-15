"""Unit tests for the extracted usage→cost translation (#178 slice 3).

`translate_usage_to_cost` maps a dispatch-layer UsageMetrics to wire ChatUsage
and prices it. The four branches (no usage / no provider-model / unknown
descriptor / priced) are covered directly; the HTTP cost-surface tests exercise
only the fully-priced money path.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

import pytest

from app.services.ai.profiles import CapabilityTier, ModelDescriptor, UsageMetrics
from app.services.ai.usage import translate_usage_to_cost

_SETTINGS = SimpleNamespace()


def _run(usage, *, provider: str = "anthropic", model: str = "claude-sonnet-5"):
    return asyncio.run(
        translate_usage_to_cost(usage, provider=provider, model=model, settings=_SETTINGS)
    )


def test_missing_usage_yields_no_wire_and_no_cost():
    wire, cost = _run(None)
    assert wire is None
    assert cost is None


def test_usage_without_provider_or_model_skips_pricing():
    wire, cost = _run(UsageMetrics(input_tokens=10, output_tokens=5), provider="", model="")
    assert wire is not None
    assert wire.input_tokens == 10
    assert wire.output_tokens == 5
    assert cost is None


def test_unknown_descriptor_yields_wire_without_cost():
    usage = UsageMetrics(input_tokens=10, output_tokens=5)
    with mock.patch(
        "app.services.ai.usage.ai_tokens.descriptor_for",
        new=AsyncMock(return_value=None),
    ):
        wire, cost = _run(usage)
    assert wire is not None
    assert cost is None


def test_priced_descriptor_yields_wire_and_usd_cost():
    usage = UsageMetrics(input_tokens=1_000_000, output_tokens=1_000_000)
    descriptor = ModelDescriptor(
        id="claude-sonnet-5",
        display_name="Sonnet",
        provider="anthropic",
        context_window=200_000,
        tier=CapabilityTier.BALANCED,
        cost_in_per_mtok=3.0,
        cost_out_per_mtok=15.0,
    )
    with mock.patch(
        "app.services.ai.usage.ai_tokens.descriptor_for",
        new=AsyncMock(return_value=descriptor),
    ):
        wire, cost = _run(usage)
    assert wire is not None
    assert wire.input_tokens == 1_000_000
    assert cost == pytest.approx(18.0)  # $3/Mtok in + $15/Mtok out
