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
