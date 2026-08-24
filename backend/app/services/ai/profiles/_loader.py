"""Loads the bake-in fallback catalogue into `ModelDescriptor` lists keyed
by provider name. Used by every concrete profile's `list_models()` as the
offline fallback path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.services.ai.profiles.base import (
    Capability,
    CapabilityTier,
    ModelDescriptor,
)


def mark_deprecated(descriptor: ModelDescriptor) -> ModelDescriptor:
    """Return a copy of `descriptor` with `deprecated=True`. Used by
    profiles when a baked-in model no longer appears in live discovery —
    the picker still shows it (so existing assistants don't error) but
    flags it as retired."""

    return replace(descriptor, deprecated=True)


# Reasoning markers OpenRouter (and the id-only live-catalogue path) can't read
# from pricing. Shared so the cost-bucketed OpenRouter tier and the price-less
# Anthropic/OpenAI live-only tier agree on what "looks like a reasoning model".
_REASONING_TOKENS = ("/o1", "/o3", "thinking", "fable")


def looks_like_reasoning(model_id: str) -> bool:
    """Heuristic: does this id name a reasoning model? Used where the provider
    doesn't flag thinking-capability directly (ADR-0073 S4)."""

    lower = model_id.lower()
    return any(token in lower for token in _REASONING_TOKENS)


def tier_for_unpriced(model_id: str) -> CapabilityTier:
    """Derive a tier for a live-only model whose provider publishes no pricing
    (Anthropic/OpenAI `/v1/models`). Reasoning ids bucket to REASONING; the rest
    default to BALANCED. Best-effort — the model is marked unverified and the
    user can override in the picker, so a wrong guess only changes its group."""

    return CapabilityTier.REASONING if looks_like_reasoning(model_id) else CapabilityTier.BALANCED


def _synth_live_descriptor(provider: str, row: dict[str, Any]) -> ModelDescriptor:
    """Build a descriptor for a live model with no baked-in audit entry
    (ADR-0073 S4). Raw id as the display name (or the provider's own live
    `display_name` when present), a derived tier, no pricing, and
    `verified=False` so the picker badges it "new"."""

    model_id = str(row["id"])
    return ModelDescriptor(
        id=model_id,
        display_name=str(row.get("display_name") or model_id),
        provider=provider,
        context_window=0,
        tier=tier_for_unpriced(model_id),
        capabilities=set(),
        verified=False,
    )


def merge_live_catalogue(
    provider: str,
    baked: list[ModelDescriptor],
    live_rows: Iterable[dict[str, Any]],
    *,
    surface_live_only: bool,
) -> list[ModelDescriptor]:
    """Merge a provider's hand-audited bake-in with its live `/v1/models`
    listing (ADR-0073 S4).

    Bake-in is the source of tier/cost truth: a baked model still present live
    is kept as-is; one that has vanished from live is marked deprecated (so the
    picker warns but existing assistants don't error). When `surface_live_only`
    is set (the provider's `live_catalog`), live models with NO baked entry are
    appended — in live order — as unverified descriptors with a derived tier,
    instead of being dropped. That is the S4 fix: Refresh surfaces newer models
    the account actually has, rather than a frozen list."""

    live_by_id: dict[str, dict[str, Any]] = {}
    for row in live_rows:
        model_id = row.get("id")
        if model_id:
            live_by_id[str(model_id)] = row
    live_ids = set(live_by_id)
    baked_ids = {d.id for d in baked}

    merged: list[ModelDescriptor] = []
    for descriptor in baked:
        if descriptor.id in live_ids or descriptor.deprecated:
            merged.append(descriptor)
        else:
            merged.append(mark_deprecated(descriptor))

    if surface_live_only:
        for model_id, row in live_by_id.items():
            if model_id not in baked_ids:
                merged.append(_synth_live_descriptor(provider, row))

    return merged


_BAKED_IN_PATH = Path(__file__).with_name("_baked_in.yaml")


@lru_cache(maxsize=1)
def baked_in_catalogue() -> dict[str, list[ModelDescriptor]]:
    """Parse `_baked_in.yaml` once per process. Returns provider name →
    list of descriptors. Empty list when the provider key exists but
    has no entries (Ollama)."""

    raw = yaml.safe_load(_BAKED_IN_PATH.read_text(encoding="utf-8")) or {}
    out: dict[str, list[ModelDescriptor]] = {}
    for provider_name, rows in raw.items():
        out[provider_name] = [_row_to_descriptor(provider_name, r) for r in (rows or [])]
    return out


def baked_in_for(provider: str) -> list[ModelDescriptor]:
    """Convenience: catalogue for one provider, empty list if unknown."""

    return list(baked_in_catalogue().get(provider, []))


def _row_to_descriptor(provider: str, row: dict[str, Any]) -> ModelDescriptor:
    capabilities = {Capability(c) for c in row.get("capabilities") or []}
    sunset_raw = row.get("sunset_date")
    sunset = _parse_date(sunset_raw)
    return ModelDescriptor(
        id=str(row["id"]),
        display_name=str(row.get("display_name") or row["id"]),
        provider=provider,
        context_window=int(row.get("context_window") or 0),
        tier=CapabilityTier(row["tier"]),
        capabilities=capabilities,
        deprecated=bool(row.get("deprecated") or False),
        sunset_date=sunset,
        successor=row.get("successor") or None,
        cost_in_per_mtok=_opt_float(row.get("cost_in_per_mtok")),
        cost_out_per_mtok=_opt_float(row.get("cost_out_per_mtok")),
        cache_read_multiplier=_opt_float(row.get("cache_read_multiplier")),
    )


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
