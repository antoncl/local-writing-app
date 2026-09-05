"""Price refresh + reset sweep (ADR-0083 Slice 2b).

An oracle refresh clears the manual price fields of any assistant whose model the
oracle now prices — a value entered while the model was unlisted, made redundant
once OpenRouter lists it. Fill semantics mean the cost was already correct (the
oracle wins); the sweep only tidies the dormant field.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateAssistantEntryRequest, SaveAssistantEntryRequest
from app.services.ai.profiles import price_oracle


def _priced_assistant(service, model: str = "claude-mythos-5") -> str:
    created = service.create_assistant_entry(
        CreateAssistantEntryRequest(title="Priced", layer_id=None)
    )
    service.save_assistant_entry(
        created.id,
        SaveAssistantEntryRequest(
            title="Priced",
            metadata={
                "ai_provider": "anthropic",
                "ai_model": model,
                "ai_price_in_usd_per_mtok": 2,
                "ai_price_out_usd_per_mtok": 8,
            },
        ),
    )
    return created.id


def test_reset_clears_when_oracle_now_prices_the_model() -> None:
    with TemporaryDirectory() as tmp:
        service = open_test_project(Path(tmp) / "project", "Reset Tests")
        aid = _priced_assistant(service)
        price_oracle._index = {"claude-mythos-5": (5.0, 25.0)}  # oracle now lists it
        cleared = service.reset_stale_manual_prices()
        assert cleared == 1
        meta = service.read_assistant_entry(aid).metadata
        assert "ai_price_in_usd_per_mtok" not in meta
        assert "ai_price_out_usd_per_mtok" not in meta
        # Non-price fields survive the sweep.
        assert meta.get("ai_model") == "claude-mythos-5"


def test_reset_keeps_manual_when_oracle_still_cannot_price() -> None:
    with TemporaryDirectory() as tmp:
        service = open_test_project(Path(tmp) / "project", "Reset Tests")
        aid = _priced_assistant(service)
        price_oracle._index = {}  # oracle still can't price it
        cleared = service.reset_stale_manual_prices()
        assert cleared == 0
        assert "ai_price_in_usd_per_mtok" in service.read_assistant_entry(aid).metadata


def test_reset_ignores_assistant_without_a_manual_price() -> None:
    with TemporaryDirectory() as tmp:
        service = open_test_project(Path(tmp) / "project", "Reset Tests")
        created = service.create_assistant_entry(
            CreateAssistantEntryRequest(title="Plain", layer_id=None)
        )
        service.save_assistant_entry(
            created.id,
            SaveAssistantEntryRequest(
                title="Plain",
                metadata={"ai_provider": "anthropic", "ai_model": "claude-mythos-5"},
            ),
        )
        price_oracle._index = {"claude-mythos-5": (5.0, 25.0)}
        assert service.reset_stale_manual_prices() == 0


def test_reset_sweeps_a_mixed_roster() -> None:
    # One assistant the oracle now prices is cleared; another on a still-unlisted
    # model is kept — and the count reflects only the cleared one.
    with TemporaryDirectory() as tmp:
        service = open_test_project(Path(tmp) / "project", "Mixed Roster")
        listed = _priced_assistant(service, model="claude-mythos-5")
        unlisted = _priced_assistant(service, model="local-still-unlisted")
        price_oracle._index = {"claude-mythos-5": (5.0, 25.0)}
        assert service.reset_stale_manual_prices() == 1
        assert "ai_price_in_usd_per_mtok" not in service.read_assistant_entry(listed).metadata
        assert "ai_price_in_usd_per_mtok" in service.read_assistant_entry(unlisted).metadata


def test_refresh_endpoint_offline_keeps_prices(monkeypatch) -> None:
    # A failed refetch (offline) leaves the index cold → nothing is cleared and
    # manual prices survive; the endpoint still returns 200.
    with TemporaryDirectory() as tmp:
        service = open_test_project(Path(tmp) / "project", "Offline")
        aid = _priced_assistant(service)

        async def boom() -> list[dict]:
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(price_oracle, "_fetch_rows", boom)
        response = TestClient(app).post("/api/ai/prices/refresh")
        assert response.status_code == 200, response.text
        assert response.json()["cleared"] == 0
        assert "ai_price_in_usd_per_mtok" in service.read_assistant_entry(aid).metadata


def test_refresh_endpoint_refetches_then_clears(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        service = open_test_project(Path(tmp) / "project", "Refresh Endpoint")
        aid = _priced_assistant(service)

        async def fake_fetch() -> list[dict]:
            return [
                {"id": "anthropic/claude-mythos-5", "pricing": {"prompt": "0.000005", "completion": "0.000025"}}
            ]

        monkeypatch.setattr(price_oracle, "_fetch_rows", fake_fetch)
        response = TestClient(app).post("/api/ai/prices/refresh")
        assert response.status_code == 200, response.text
        assert response.json()["cleared"] == 1
        assert "ai_price_in_usd_per_mtok" not in service.read_assistant_entry(aid).metadata
