"""OpenRouter price parsing must distinguish free from unknown (#1386).

Free `:free` routes are reported by OpenRouter with price "0". The parser once
collapsed 0 -> None, and `list_models` then dropped null-priced rows — hiding the
free models a local-first, cost-conscious user most wants. These pin the pure
parsing/tiering: "0" is a real price (0.0, kept), only missing/unparseable prices
become None. The end-to-end filter (free kept, unpriced dropped) is covered in
test_ai_profiles_concrete.py::test_openrouter_parses_pricing_and_buckets_tier.
"""

from __future__ import annotations

from app.services.ai.profiles.base import CapabilityTier
from app.services.ai.profiles.openrouter import _per_mtok, _row_to_descriptor

# ---- _per_mtok: free vs unknown -------------------------------------------


def test_per_mtok_free_is_zero_not_none() -> None:
    # The crux: a genuinely free model must be a real 0.0, so it survives the
    # `cost_in_per_mtok is not None` filter rather than being treated as unpriced.
    assert _per_mtok("0") == 0.0


def test_per_mtok_missing_or_unparseable_is_none() -> None:
    assert _per_mtok(None) is None
    assert _per_mtok("") is None
    assert _per_mtok("not-a-number") is None
    assert _per_mtok("-0.5") is None  # negative is nonsense -> unknown


def test_per_mtok_priced_scales_to_per_mtok() -> None:
    # 0.000002 USD/token -> 2.0 USD per 1M tokens.
    assert _per_mtok("0.000002") == 2.0


# ---- _row_to_descriptor: a free row tiers sanely --------------------------


def test_free_row_becomes_zero_cost_fast_tier() -> None:
    row = {
        "id": "vendor/model:free",
        "name": "Vendor Model (free)",
        "context_length": 8000,
        "pricing": {"prompt": "0", "completion": "0"},
    }
    d = _row_to_descriptor(row)
    assert d.cost_in_per_mtok == 0.0
    assert d.tier == CapabilityTier.FAST  # $0 falls in the <$1 band


# ---- _row_to_descriptor: temperature support from the route params ---------


def _row(model_id: str, supported_parameters: list[str]) -> dict:
    return {
        "id": model_id,
        "name": model_id,
        "context_length": 8000,
        "pricing": {"prompt": "0.000001", "completion": "0.000001"},
        "supported_parameters": supported_parameters,
    }


def test_row_records_temperature_from_supported_parameters() -> None:
    # OpenRouter publishes the accepted params per route; the descriptor's
    # provider signal mirrors that list.
    with_temp = _row_to_descriptor(_row("openai/gpt-4o", ["temperature", "tools"]))
    without_temp = _row_to_descriptor(_row("some/reasoning-model", ["tools"]))
    assert with_temp.supports_temperature is True
    assert without_temp.supports_temperature is False
    assert with_temp.accepts_temperature is True
    assert without_temp.accepts_temperature is False


def test_no_sampling_family_via_openrouter_is_readonly_despite_listed_param() -> None:
    # Even when OpenRouter's route lists `temperature`, the family rule wins for
    # a no-sampling Anthropic model reached as `anthropic/…` (#1554).
    d = _row_to_descriptor(_row("anthropic/claude-opus-4-8", ["temperature", "tools"]))
    assert d.supports_temperature is True  # provider signal
    assert d.accepts_temperature is False  # family rule overrides
