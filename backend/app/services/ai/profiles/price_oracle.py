"""OpenRouter's public feed as a price oracle for native-provider models (ADR-0083).

Anthropic and OpenAI don't publish per-token prices on their model-list
endpoints, so `_baked_in.yaml` was the only native-route cost source — and it
drifts (missing rows, stale prices). OpenRouter's `/api/v1/models` endpoint is
public (no API key) and carries authoritative, current prices for the *same*
underlying models. This module fetches it once, key-less, into a process-level
index `native-id -> (cost_in_per_mtok, cost_out_per_mtok)` and overlays those
prices onto native Anthropic/OpenAI descriptors at the `list_models` boundary.

Precedence (ADR-0083 §1): a user override wins over this oracle, which wins over
the baked-in seed. This module is the oracle layer only; the override layer
lands in Slice 2.

Refresh is event-driven (ADR-0083 §3): the index warms lazily on first use and
is otherwise rebuilt only by `refresh()` (an author action). No TTL. Every
failure falls soft to the caller's existing baked-in price.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

import httpx

from app.services.ai.profiles.base import ModelDescriptor

log = logging.getLogger(__name__)

_MODELS_URL = "https://openrouter.ai/api/v1/models"
_TIMEOUT = 8.0
# The OpenRouter route prefixes whose rows price a NATIVE provider's models.
_NATIVE_PREFIXES = ("anthropic/", "openai/")

# Process-level index: normalized native id -> (cost_in_per_mtok, cost_out_per_mtok).
# `None` means "never loaded" (cold) — a failed fetch leaves it None so the next
# call retries. A successful fetch sets a dict (possibly empty = "loaded").
_index: dict[str, tuple[float | None, float | None]] | None = None

# A trailing dated-snapshot suffix on a model id: `-YYYY-MM-DD` or `-YYYYMMDD`.
_DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$|-\d{8}$")


def _normalize_id(model_id: str) -> str:
    """Native model id -> oracle index key (ADR-0083).

    Strip any `provider/` route prefix and dated snapshot suffix, then collapse a
    version dash *between two digits* to a dot so `claude-opus-4-8` matches
    OpenRouter's `claude-opus-4.8` and `claude-fable-5-1` matches
    `claude-fable-5.1`. A dash not between digits (`o3-mini`) is left alone.

    The dash→dot uses a zero-width lookaround, not `(\\d)-(\\d)`, so it does not
    consume the boundary digit — consecutive segments all convert
    (`x-4-5-6` -> `x-4.5.6`), where a capture-group sub would miss every other gap.
    """

    ident = model_id.split("/", 1)[-1]
    ident = _DATE_SUFFIX_RE.sub("", ident)
    return re.sub(r"(?<=\d)-(?=\d)", ".", ident)


def _is_dated(ident: str) -> bool:
    """Whether a bare (prefix-stripped) id ends in a dated snapshot suffix."""

    return bool(_DATE_SUFFIX_RE.search(ident))


def _per_mtok(raw: object) -> float | None:
    """OpenRouter prices are USD-per-token strings. Convert to USD per 1M tokens;
    `None` when missing/unparseable, `0.0` kept for a genuinely free route."""

    if raw is None or raw == "":
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value * 1_000_000


async def _fetch_rows() -> list[dict]:
    """GET the public feed. Raises on network/JSON failure; returns [] for a
    well-formed-but-unexpected payload shape (top-level not an object, or `data`
    not a list) so `_build_index` always gets a list."""

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(_MODELS_URL)
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, list) else []


def _build_index(rows: list[dict]) -> dict[str, tuple[float | None, float | None]]:
    """Index the native (anthropic/openai) rows of the feed by normalized id.

    Defensive against a malformed feed (ADR-0083 §6): a row that isn't a dict, or
    whose `pricing` isn't a dict, is skipped rather than raised on. When a
    canonical id and a dated snapshot of it collapse to the same key, the undated
    row wins regardless of feed order."""

    out: dict[str, tuple[float | None, float | None]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "")
        if not any(model_id.startswith(prefix) for prefix in _NATIVE_PREFIXES):
            continue
        pricing = row.get("pricing")
        if not isinstance(pricing, dict):
            continue
        cost_in = _per_mtok(pricing.get("prompt"))
        cost_out = _per_mtok(pricing.get("completion"))
        if cost_in is None and cost_out is None:
            continue
        key = _normalize_id(model_id)
        if key in out and _is_dated(model_id.split("/", 1)[-1]):
            continue  # keep the canonical (undated) price over a dated snapshot
        out[key] = (cost_in, cost_out)
    return out


async def ensure_loaded() -> None:
    """Warm the index once (lazy cold-start). A failed fetch leaves the index
    cold so the next call retries; never raises."""

    global _index
    if _index is not None:
        return
    try:
        _index = _build_index(await _fetch_rows())
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        # Any malformed-feed shape (ADR-0083 §6) leaves the index cold → retry.
        log.warning("price oracle: feed fetch failed (%s); using baked-in prices", exc)


async def refresh() -> None:
    """Force a rebuild — an author action (assistant add/change, manual button).
    A failed fetch keeps the previous index rather than clearing it."""

    global _index
    try:
        rebuilt = _build_index(await _fetch_rows())
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        log.warning("price oracle: refresh failed (%s); keeping previous prices", exc)
        return
    _index = rebuilt


def price_for(model_id: str) -> tuple[float | None, float | None] | None:
    """Oracle price for a native model id, or `None` when the oracle has none
    (cold, offline, or a model OpenRouter doesn't list). Sync — reads the cached
    index only, never the network."""

    if _index is None or not model_id:
        return None
    return _index.get(_normalize_id(model_id))


def apply_prices(descriptors: list[ModelDescriptor]) -> list[ModelDescriptor]:
    """Overlay oracle prices onto native descriptors — cost fields only
    (ADR-0083 §2). The oracle wins over the baked price; a field the oracle lacks
    keeps its baked value. Descriptors the oracle doesn't cover pass through
    untouched."""

    out: list[ModelDescriptor] = []
    for descriptor in descriptors:
        priced = price_for(descriptor.id)
        if priced is not None:
            cost_in, cost_out = priced
            descriptor = replace(
                descriptor,
                cost_in_per_mtok=cost_in if cost_in is not None else descriptor.cost_in_per_mtok,
                cost_out_per_mtok=cost_out if cost_out is not None else descriptor.cost_out_per_mtok,
            )
        out.append(descriptor)
    return out


async def priced_with_oracle(descriptors: list[ModelDescriptor]) -> list[ModelDescriptor]:
    """A native profile's `list_models` calls this: warm the index, then overlay.
    Fail-soft — returns the input untouched when the oracle is cold."""

    await ensure_loaded()
    return apply_prices(descriptors)


def reset_cache() -> None:
    """Test hook: drop the process-level index so the next `ensure_loaded`
    refetches."""

    global _index
    _index = None
