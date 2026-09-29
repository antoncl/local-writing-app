"""Local Ollama models are FREE, not "price unknown" (#2343).

An Ollama model runs on the author's machine, so the catalogue prices it at 0
in/out: `free` is true, a call bills at 0.0 (€0.00), and nothing nags the author
to "set a price". A manual price the author sets on a local assistant still wins
— the local 0 is a default, not a published price.
"""

from __future__ import annotations

from app.services.ai import tokens as ai_tokens
from app.services.ai.profiles.base import CapabilityTier, UsageMetrics, compute_cost
from app.services.ai.profiles.ollama import _row_to_descriptor

_SHOW = {
    "model_info": {"general.architecture": "llama", "llama.context_length": 131072},
    "capabilities": ["completion"],
}


def _local():
    return _row_to_descriptor({"name": "DarkIdol:latest", "model": "DarkIdol:latest"}, _SHOW)


def test_an_ollama_model_is_priced_free() -> None:
    d = _local()
    assert d.tier == CapabilityTier.LOCAL
    assert (d.cost_in_per_mtok, d.cost_out_per_mtok) == (0.0, 0.0)
    assert d.free is True


def test_an_ollama_call_bills_zero_not_unknown() -> None:
    usage = UsageMetrics(input_tokens=24_000, output_tokens=1_500)
    assert compute_cost(usage, _local()) == 0.0


def test_a_manual_price_on_a_local_assistant_still_wins() -> None:
    out = ai_tokens.apply_manual_fill(
        _local(), provider="ollama", model="DarkIdol:latest", manual_in=0.2, manual_out=0.4
    )
    assert out is not None
    assert (out.cost_in_per_mtok, out.cost_out_per_mtok) == (0.2, 0.4)


def test_without_a_manual_price_the_local_model_stays_free() -> None:
    d = _local()
    out = ai_tokens.apply_manual_fill(d, provider="ollama", model="DarkIdol:latest", manual_in=None, manual_out=None)
    assert out is d
    assert out.free is True
