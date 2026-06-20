"""Loads the bake-in fallback catalogue into `ModelDescriptor` lists keyed
by provider name. Used by every concrete profile's `list_models()` as the
offline fallback path.
"""

from __future__ import annotations

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
