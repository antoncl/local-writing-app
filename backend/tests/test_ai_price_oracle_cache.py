"""File-backed price oracle cache (ADR-0083 §3, #1828).

The oracle index persists to a machine-level JSON file. A cold start loads that
file with no network; only a first-ever start (no file) fetches, and only
`refresh()` refetches and rewrites the file. Prices move rarely, so the cached
file is authoritative until an explicit refresh. The cache path derives from
`config_path`, which conftest redirects to a per-test tempdir, so these tests are
isolated without touching the developer's real cache.
"""

from __future__ import annotations

import asyncio

import httpx

from app.services.ai.profiles import price_oracle

_FEED = [
    {"id": "anthropic/claude-opus-5", "pricing": {"prompt": "0.000005", "completion": "0.000025"}},
]


def _feed(monkeypatch, rows: list[dict] | None = None) -> None:
    payload = list(_FEED if rows is None else rows)

    async def fake_fetch() -> list[dict]:
        return payload

    monkeypatch.setattr(price_oracle, "_fetch_rows", fake_fetch)


# ---- pure round-trip -------------------------------------------------------


def test_cache_round_trip_preserves_none_side() -> None:
    price_oracle._write_cache({"m": (5.0, None)})
    assert price_oracle._read_cache() == {"m": (5.0, None)}


def test_read_cache_none_when_no_file() -> None:
    assert price_oracle._read_cache() is None


def test_reset_cache_removes_the_file() -> None:
    price_oracle._write_cache({"m": (5.0, 25.0)})
    assert price_oracle._read_cache() is not None
    price_oracle.reset_cache()
    assert price_oracle._read_cache() is None


# ---- ensure_loaded prefers the file, no network ----------------------------


def test_ensure_loaded_loads_cache_without_fetching(monkeypatch) -> None:
    price_oracle._write_cache({"claude-opus-5": (5.0, 25.0)})

    async def boom() -> list[dict]:
        raise httpx.ConnectError("should not fetch when a cache file exists")

    monkeypatch.setattr(price_oracle, "_fetch_rows", boom)
    asyncio.run(price_oracle.ensure_loaded())
    # Only the cache file can supply this (a fetch would have raised → cold).
    assert price_oracle.price_for("claude-opus-5") == (5.0, 25.0)


def test_first_ever_fetches_and_persists(monkeypatch) -> None:
    _feed(monkeypatch)
    assert price_oracle._read_cache() is None  # no file yet (first-ever)
    asyncio.run(price_oracle.ensure_loaded())
    assert price_oracle.price_for("claude-opus-5") == (5.0, 25.0)
    assert price_oracle._read_cache() == {"claude-opus-5": (5.0, 25.0)}  # persisted


def test_refresh_rewrites_the_cache(monkeypatch) -> None:
    price_oracle._write_cache({"stale-model": (1.0, 2.0)})
    _feed(monkeypatch)
    asyncio.run(price_oracle.refresh())
    assert price_oracle._read_cache() == {"claude-opus-5": (5.0, 25.0)}  # replaced, not merged


def test_empty_feed_keeps_previous_and_does_not_persist(monkeypatch) -> None:
    # A "successful" fetch that yields no native prices (soft outage: a 200 with a
    # bad-shape body -> _fetch_rows returns []) must NOT overwrite a good cache
    # with {} — that would poison every future cold start.
    _feed(monkeypatch)
    asyncio.run(price_oracle.refresh())
    assert price_oracle._read_cache() == {"claude-opus-5": (5.0, 25.0)}

    async def empty() -> list[dict]:
        return []

    monkeypatch.setattr(price_oracle, "_fetch_rows", empty)
    asyncio.run(price_oracle.refresh())
    assert price_oracle.price_for("claude-opus-5") == (5.0, 25.0)  # index untouched
    assert price_oracle._read_cache() == {"claude-opus-5": (5.0, 25.0)}  # file untouched


def test_empty_cache_file_refetches(monkeypatch) -> None:
    # A degenerate {} file is not trusted — treated as no cache so we refetch.
    path = price_oracle._cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert price_oracle._read_cache() is None
    _feed(monkeypatch)
    asyncio.run(price_oracle.ensure_loaded())
    assert price_oracle.price_for("claude-opus-5") == (5.0, 25.0)  # refetched, not stuck on {}


def test_malformed_cache_file_is_ignored() -> None:
    path = price_oracle._cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for bad in ("not json", "[1, 2]", '{"m": [1]}', '{"m": "x"}'):
        path.write_text(bad, encoding="utf-8")
        assert price_oracle._read_cache() is None, bad


def test_failed_refresh_keeps_previous_cache(monkeypatch) -> None:
    _feed(monkeypatch)
    asyncio.run(price_oracle.refresh())  # writes the good cache

    async def boom() -> list[dict]:
        raise httpx.ReadTimeout("offline")

    monkeypatch.setattr(price_oracle, "_fetch_rows", boom)
    asyncio.run(price_oracle.refresh())  # fails
    assert price_oracle._read_cache() == {"claude-opus-5": (5.0, 25.0)}  # untouched
