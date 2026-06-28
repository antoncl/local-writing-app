"""HTTP-surface tests for the provider profile endpoints. Patches
httpx.AsyncClient inside each profile module so nothing hits the
network; verifies the wire shape stays stable and the endpoints
respect known/unknown providers + tiers.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

# --- httpx fake plumbing (copy of test_ai_profiles_concrete.py's helpers) ---


class _FakeResponse:
    def __init__(self, json_payload: Any, status: int = 200) -> None:
        self._json = json_payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> Any:
        return self._json


class _FakeAsyncClient:
    def __init__(self, payload: Any = None, raise_exc: Exception | None = None, **_kw) -> None:
        self._payload = payload
        self._raise = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def get(self, url: str, **_kw) -> _FakeResponse:
        if self._raise is not None:
            raise self._raise
        return _FakeResponse(self._payload)


def _patch_module_httpx(monkeypatch, module: str, **kwargs):
    def factory(**kw):
        return _FakeAsyncClient(**kwargs, **kw)

    monkeypatch.setattr(f"{module}.httpx.AsyncClient", factory)


# --- Tests ----------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_list_providers_returns_all_four_known(client):
    response = client.get("/api/ai/providers")
    assert response.status_code == 200
    names = {p["name"] for p in response.json()["providers"]}
    assert names == {"anthropic", "openai", "openrouter", "ollama"}
    # Display names are populated, not raw provider keys.
    by_name = {p["name"]: p for p in response.json()["providers"]}
    assert by_name["openai"]["display_name"] == "OpenAI"


def test_list_models_returns_wire_shape_for_anthropic(client, monkeypatch):
    # No API key configured → profile falls back to bake-in, which is
    # enough to exercise the wire-format conversion.
    response = client.get("/api/ai/providers/anthropic/models")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert len(body["models"]) >= 3
    sonnet = next(m for m in body["models"] if m["id"] == "claude-sonnet-4-6")
    # Wire fields: enums serialized as strings; capabilities sorted list.
    assert sonnet["tier"] == "balanced"
    assert isinstance(sonnet["capabilities"], list)
    assert "caching" in sonnet["capabilities"]
    assert sonnet["cost_in_per_mtok"] == pytest.approx(3.0)
    assert sonnet["deprecated"] is False
    assert sonnet["sunset_date"] is None


def test_list_models_unknown_provider_404s(client):
    response = client.get("/api/ai/providers/nope/models")
    assert response.status_code == 404


def test_resolve_tier_returns_cheapest_anthropic_balanced(client):
    response = client.get(
        "/api/ai/providers/anthropic/resolve-tier",
        params={"tier": "balanced"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["tier"] == "balanced"
    assert body["model_id"] == "claude-sonnet-4-6"


def test_resolve_tier_returns_null_for_ollama_premium(client, monkeypatch):
    # Ollama deliberately disables tier auto-rank (LOCAL is the only
    # valid tier), so any non-LOCAL tier should resolve to null.
    _patch_module_httpx(
        monkeypatch, "app.services.ai.profiles.ollama", payload={"models": []}
    )
    response = client.get(
        "/api/ai/providers/ollama/resolve-tier",
        params={"tier": "premium"},
    )
    assert response.status_code == 200
    assert response.json()["model_id"] is None


def test_resolve_tier_unknown_tier_400s(client):
    response = client.get(
        "/api/ai/providers/anthropic/resolve-tier",
        params={"tier": "ultradeluxe"},
    )
    assert response.status_code == 400


def test_resolve_tier_unknown_provider_404s(client):
    response = client.get(
        "/api/ai/providers/nope/resolve-tier",
        params={"tier": "balanced"},
    )
    assert response.status_code == 404


def test_list_models_for_openrouter_uses_live_data(client, monkeypatch):
    _patch_module_httpx(
        monkeypatch,
        "app.services.ai.profiles.openrouter",
        payload={
            "data": [
                {
                    "id": "anthropic/claude-haiku-4.5",
                    "name": "Haiku 4.5",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.0000008", "completion": "0.000004"},
                    "architecture": {"input_modalities": ["text"]},
                    "supported_parameters": ["tools"],
                }
            ]
        },
    )
    response = client.get("/api/ai/providers/openrouter/models")
    assert response.status_code == 200
    models = response.json()["models"]
    assert len(models) == 1
    assert models[0]["id"] == "anthropic/claude-haiku-4.5"
    # Caching capability inferred from anthropic/ prefix.
    assert "caching" in models[0]["capabilities"]
