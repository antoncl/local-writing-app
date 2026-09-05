"""Author-set assistant price as a FILL (ADR-0083 Amendment 1).

An assistant may carry `ai_price_in_usd_per_mtok` / `ai_price_out_usd_per_mtok`
for a model the price oracle can't reach (unlisted or local). It fills the cost
only when neither the oracle nor the baked seed prices the model — so the oracle
auto-heals once it lists the model. These pin the fill precedence
(oracle → baked → manual) and the resolver plumbing.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.ai import tokens as ai_tokens
from app.services.ai.call_resolver import resolve_call_params
from app.services.ai.profiles.base import CapabilityTier, ModelDescriptor, UsageMetrics
from app.services.ai.usage import translate_usage_to_cost
from app.services.machine_settings import MachineSettings


def _desc(cost_in: float | None = None, cost_out: float | None = None) -> ModelDescriptor:
    return ModelDescriptor(
        id="m",
        display_name="m",
        provider="anthropic",
        context_window=0,
        tier=CapabilityTier.BALANCED,
        cost_in_per_mtok=cost_in,
        cost_out_per_mtok=cost_out,
    )


# ---- apply_manual_fill: precedence oracle/baked > manual --------------------


def test_manual_fill_noop_without_manual() -> None:
    d = _desc()
    assert ai_tokens.apply_manual_fill(d, provider="anthropic", model="m", manual_in=None, manual_out=None) is d


def test_manual_fill_ignored_when_descriptor_already_priced() -> None:
    d = _desc(cost_in=5.0, cost_out=25.0)  # oracle/baked price present
    out = ai_tokens.apply_manual_fill(d, provider="anthropic", model="m", manual_in=1.0, manual_out=2.0)
    assert (out.cost_in_per_mtok, out.cost_out_per_mtok) == (5.0, 25.0)  # manual ignored


def test_manual_fill_fills_a_priceless_descriptor() -> None:
    d = _desc(cost_in=None, cost_out=None)  # in catalogue but unpriced (live-only)
    out = ai_tokens.apply_manual_fill(d, provider="anthropic", model="m", manual_in=1.5, manual_out=3.0)
    assert (out.cost_in_per_mtok, out.cost_out_per_mtok) == (1.5, 3.0)


def test_manual_fill_synthesizes_when_no_descriptor() -> None:
    # No catalogue entry at all (e.g. a local Ollama model).
    out = ai_tokens.apply_manual_fill(None, provider="ollama", model="local-llama", manual_in=2.0, manual_out=8.0)
    assert out is not None
    assert out.id == "local-llama"
    assert (out.cost_in_per_mtok, out.cost_out_per_mtok) == (2.0, 8.0)
    assert out.verified is False


def test_manual_fill_requires_both_sides() -> None:
    # A half-set manual price is "unknown", not a confident $0 on the blank side:
    # it does not fill and does not synthesize a descriptor.
    priceless = _desc(cost_in=None, cost_out=None)
    assert ai_tokens.apply_manual_fill(priceless, provider="anthropic", model="m", manual_in=2.0, manual_out=None) is priceless
    assert ai_tokens.apply_manual_fill(priceless, provider="anthropic", model="m", manual_in=None, manual_out=8.0) is priceless
    assert ai_tokens.apply_manual_fill(None, provider="ollama", model="x", manual_in=2.0, manual_out=None) is None


# ---- translate_usage_to_cost end-to-end ------------------------------------


def test_manual_prices_an_unlisted_model() -> None:
    usage = UsageMetrics(input_tokens=1_000_000, output_tokens=1_000_000)
    # No key + oracle neutralized in tests → claude-mythos-5 has no descriptor.
    _wire, cost = asyncio.run(
        translate_usage_to_cost(
            usage,
            provider="anthropic",
            model="claude-mythos-5",
            settings=MachineSettings(),
            manual_price_in_usd_per_mtok=2.0,
            manual_price_out_usd_per_mtok=8.0,
        )
    )
    assert cost == pytest.approx(10.0)  # 1M in @2 + 1M out @8


def test_baked_price_wins_over_manual() -> None:
    # claude-opus-4-8 is in the baked seed → its price wins; manual is ignored.
    usage = UsageMetrics(input_tokens=1_000_000, output_tokens=0)
    _wire, cost = asyncio.run(
        translate_usage_to_cost(
            usage,
            provider="anthropic",
            model="claude-opus-4-8",
            settings=MachineSettings(),
            manual_price_in_usd_per_mtok=999.0,
            manual_price_out_usd_per_mtok=999.0,
        )
    )
    assert cost == pytest.approx(15.0)  # baked opus-4-8 input rate, not 999


def test_priced_descriptor_for_is_the_choke_point() -> None:
    # descriptor_for + manual fill in one call — the single site every cost path
    # resolves through. Unlisted model + manual price → a synthesized priced row.
    descriptor = asyncio.run(
        ai_tokens.priced_descriptor_for(
            provider="anthropic",
            model="claude-mythos-5",
            settings=MachineSettings(),
            manual_in=2.0,
            manual_out=8.0,
        )
    )
    assert descriptor is not None
    assert (descriptor.cost_in_per_mtok, descriptor.cost_out_per_mtok) == (2.0, 8.0)


# ---- resolve_call_params reads the fields onto ResolvedCall ----------------


class _FakeAssistant:
    def __init__(self, meta: dict) -> None:
        self.metadata = meta


class _FakeProject:
    def __init__(self, assistant: _FakeAssistant | None) -> None:
        self._assistant = assistant

    def resolve_assistant(self, _assistant_id: str | None) -> _FakeAssistant | None:
        return self._assistant


def _resolve(meta: dict):
    return resolve_call_params(
        _FakeProject(_FakeAssistant(meta)),  # type: ignore[arg-type]
        MachineSettings(),
        assistant_id=None,
        provider_override=None,
        model_override=None,
        max_tokens_override=None,
    )


def test_resolve_reads_manual_price_fields() -> None:
    resolved = _resolve({"ai_provider": "ollama", "ai_model": "x", "ai_price_in_usd_per_mtok": 2.5, "ai_price_out_usd_per_mtok": 9})
    assert resolved.manual_price_in_usd_per_mtok == 2.5
    assert resolved.manual_price_out_usd_per_mtok == 9.0


def test_resolve_blank_or_invalid_price_is_none() -> None:
    resolved = _resolve({"ai_provider": "ollama", "ai_model": "x", "ai_price_in_usd_per_mtok": "", "ai_price_out_usd_per_mtok": "nope"})
    assert resolved.manual_price_in_usd_per_mtok is None
    assert resolved.manual_price_out_usd_per_mtok is None


def test_resolve_rejects_negative_and_nonfinite_price() -> None:
    resolved = _resolve({"ai_provider": "ollama", "ai_model": "x", "ai_price_in_usd_per_mtok": -1, "ai_price_out_usd_per_mtok": "inf"})
    assert resolved.manual_price_in_usd_per_mtok is None
    assert resolved.manual_price_out_usd_per_mtok is None


def test_resolve_keeps_zero_price() -> None:
    # A genuinely free (local) model: 0 is a real price, kept distinct from unset.
    resolved = _resolve({"ai_provider": "ollama", "ai_model": "x", "ai_price_in_usd_per_mtok": 0, "ai_price_out_usd_per_mtok": 0})
    assert resolved.manual_price_in_usd_per_mtok == 0.0
    assert resolved.manual_price_out_usd_per_mtok == 0.0
