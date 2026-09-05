"""Price oracle: OpenRouter's public feed overlays native model prices (ADR-0083).

The oracle fixes the drift that made native cost data wrong two ways — missing
rows (`claude-opus-5` → cost 0) and stale rows (Opus 4.7/4.8 baked 3× high). It
fetches OpenRouter's public feed key-less into a process-level index and overlays
the cost fields of native descriptors. These tests pin the pure pieces (id
normalization, index build, overlay precedence) and the async warm/refresh with
a stubbed feed — no test touches the network.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ai.profiles import price_oracle
from app.services.ai.profiles.base import CapabilityTier, ModelDescriptor


@pytest.fixture(autouse=True)
def _reset_oracle():
    """Isolate the process-level index between tests."""
    price_oracle.reset_cache()
    yield
    price_oracle.reset_cache()


def _desc(
    model_id: str,
    *,
    provider: str = "anthropic",
    cost_in: float | None = None,
    cost_out: float | None = None,
) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        display_name=model_id,
        provider=provider,
        context_window=200000,
        tier=CapabilityTier.PREMIUM,
        cost_in_per_mtok=cost_in,
        cost_out_per_mtok=cost_out,
    )


# A minimal stand-in for OpenRouter's /api/v1/models `data` list. Prices are
# USD-per-token strings, exactly as the real feed reports them.
_FEED: list[dict] = [
    {"id": "anthropic/claude-opus-4.8", "pricing": {"prompt": "0.000005", "completion": "0.000025"}},
    {"id": "anthropic/claude-opus-5", "pricing": {"prompt": "0.000005", "completion": "0.000025"}},
    {"id": "anthropic/claude-fable-5.1", "pricing": {"prompt": "0.00001", "completion": "0.00005"}},
    {"id": "openai/gpt-4o", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
    {"id": "x-ai/grok-2", "pricing": {"prompt": "0.000002", "completion": "0.00001"}},  # non-native
    {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},  # unpriced
]


def _stub_feed(monkeypatch, rows: list[dict] | None = None) -> None:
    payload = list(_FEED if rows is None else rows)

    async def fake_fetch() -> list[dict]:
        return payload

    monkeypatch.setattr(price_oracle, "_fetch_rows", fake_fetch)


# ---- id normalization corpus (ADR-0083) -----------------------------------


@pytest.mark.parametrize(
    ("native", "key"),
    [
        ("claude-opus-4-8", "claude-opus-4.8"),
        ("claude-fable-5-1", "claude-fable-5.1"),
        ("claude-opus-5", "claude-opus-5"),
        ("claude-haiku-4-5-20251001", "claude-haiku-4.5"),  # date stripped, then dash→dot
        ("o3-mini", "o3-mini"),  # dash not between digits — unchanged
        ("gpt-4o", "gpt-4o"),
        ("gpt-4o-2024-11-20", "gpt-4o"),  # dated snapshot stripped
        ("anthropic/claude-opus-4-8", "claude-opus-4.8"),  # route prefix stripped
    ],
)
def test_normalize_id_corpus(native: str, key: str) -> None:
    assert price_oracle._normalize_id(native) == key


# ---- index build: native + priced only ------------------------------------


def test_build_index_keeps_native_priced_only() -> None:
    idx = price_oracle._build_index(_FEED)
    assert idx["claude-opus-5"] == (5.0, 25.0)
    assert idx["claude-opus-4.8"] == (5.0, 25.0)
    assert idx["claude-fable-5.1"] == (10.0, 50.0)
    assert idx["gpt-4o"] == (2.5, 10.0)
    assert "grok-2" not in idx  # non-native route prefix skipped
    assert "auto" not in idx  # unpriced row skipped


# ---- overlay precedence: oracle > baked -----------------------------------


def test_apply_fills_missing_price() -> None:
    # A live-only descriptor (opus-5) has no baked price; the oracle supplies it.
    price_oracle._index = price_oracle._build_index(_FEED)
    [priced] = price_oracle.apply_prices([_desc("claude-opus-5")])
    assert priced.cost_in_per_mtok == 5.0
    assert priced.cost_out_per_mtok == 25.0


def test_apply_overrides_stale_baked() -> None:
    # Baked 15/75 is stale; the oracle's 5/25 wins.
    price_oracle._index = price_oracle._build_index(_FEED)
    [priced] = price_oracle.apply_prices([_desc("claude-opus-4-8", cost_in=15.0, cost_out=75.0)])
    assert priced.cost_in_per_mtok == 5.0
    assert priced.cost_out_per_mtok == 25.0


def test_apply_touches_only_cost_fields() -> None:
    price_oracle._index = price_oracle._build_index(_FEED)
    original = _desc("claude-opus-5")
    [priced] = price_oracle.apply_prices([original])
    assert priced.tier == original.tier
    assert priced.context_window == original.context_window
    assert priced.provider == original.provider
    assert priced.cache_read_multiplier == original.cache_read_multiplier


def test_unlisted_model_is_not_priced() -> None:
    # OpenRouter doesn't list Mythos — it passes through unpriced (→ warning, not 0).
    price_oracle._index = price_oracle._build_index(_FEED)
    [out] = price_oracle.apply_prices([_desc("claude-mythos-5")])
    assert out.cost_in_per_mtok is None
    assert out.cost_out_per_mtok is None


# ---- async warm / refresh / fail-soft -------------------------------------


def test_ensure_loaded_then_priced_with_oracle(monkeypatch) -> None:
    _stub_feed(monkeypatch)
    [priced] = asyncio.run(price_oracle.priced_with_oracle([_desc("claude-opus-5")]))
    assert priced.cost_in_per_mtok == 5.0
    assert priced.cost_out_per_mtok == 25.0


def test_ensure_loaded_failsoft_leaves_baked_untouched(monkeypatch) -> None:
    async def boom() -> list[dict]:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(price_oracle, "_fetch_rows", boom)
    # Cold index → overlay is a pass-through; the baked price is preserved.
    [out] = asyncio.run(price_oracle.priced_with_oracle([_desc("claude-opus-4-8", cost_in=15.0, cost_out=75.0)]))
    assert out.cost_in_per_mtok == 15.0
    assert price_oracle.price_for("claude-opus-5") is None


def test_ensure_loaded_retries_after_a_failed_fetch(monkeypatch) -> None:
    async def boom() -> list[dict]:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(price_oracle, "_fetch_rows", boom)
    asyncio.run(price_oracle.ensure_loaded())
    assert price_oracle.price_for("claude-opus-5") is None  # stayed cold

    _stub_feed(monkeypatch)
    asyncio.run(price_oracle.ensure_loaded())  # retries, now succeeds
    assert price_oracle.price_for("claude-opus-5") == (5.0, 25.0)


def test_refresh_keeps_previous_prices_on_failure(monkeypatch) -> None:
    _stub_feed(monkeypatch)
    asyncio.run(price_oracle.ensure_loaded())
    assert price_oracle.price_for("claude-opus-5") == (5.0, 25.0)

    async def boom() -> list[dict]:
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(price_oracle, "_fetch_rows", boom)
    asyncio.run(price_oracle.refresh())
    assert price_oracle.price_for("claude-opus-5") == (5.0, 25.0)  # previous kept
