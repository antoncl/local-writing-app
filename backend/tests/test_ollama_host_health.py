"""Model-less Ollama host reachability check (#1380).

The point is to answer "can this machine reach the Ollama daemon / is the
firewall open?" without a pulled model — so these pin `ping_host` against a
mocked transport (reachable / HTTP error / connect refused / not-Ollama), the
blank-host default fallback, and the route wiring.
"""

from __future__ import annotations

import httpx

from app.services.ai.profiles.ollama import _DEFAULT_OLLAMA_HOST, OllamaProfile


def _transport(handler):
    return httpx.MockTransport(handler)


def test_ping_host_reachable_reports_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/version"  # model-less endpoint
        return httpx.Response(200, json={"version": "0.5.1"})

    reachable, version, error = OllamaProfile("http://box:11434").ping_host(
        transport=_transport(handler)
    )
    assert reachable is True
    assert version == "0.5.1"
    assert error is None


def test_ping_host_strips_v1_suffix_before_probing() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"version": "1.0"})

    # A host pasted with the OpenAI-compat /v1 suffix must still probe the native
    # /api/version, not /v1/api/version.
    OllamaProfile("http://box:11434/v1").ping_host(transport=_transport(handler))
    assert seen["url"] == "http://box:11434/api/version"


def test_ping_host_http_error_is_not_reachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    reachable, version, error = OllamaProfile("http://box:11434").ping_host(
        transport=_transport(handler)
    )
    assert reachable is False
    assert version is None
    assert "500" in (error or "")


def test_ping_host_connection_refused_is_a_friendly_firewall_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    reachable, version, error = OllamaProfile("http://box:11434").ping_host(
        transport=_transport(handler)
    )
    assert reachable is False
    assert error is not None
    assert "Couldn't reach" in error and "firewall" in error


def test_ping_host_non_ollama_response_is_reachable_but_flagged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hello from nginx")  # not JSON

    reachable, version, error = OllamaProfile("http://box:11434").ping_host(
        transport=_transport(handler)
    )
    assert reachable is True  # something answered on that address
    assert version is None
    assert "didn't respond like Ollama" in (error or "")


def test_blank_host_falls_back_to_the_default(monkeypatch) -> None:
    from app.services.ai import providers

    captured: dict[str, str] = {}

    def fake_ping(self, **_kwargs):
        captured["base"] = self._base
        return (True, None, None)

    monkeypatch.setattr(OllamaProfile, "ping_host", fake_ping)
    result = providers.check_ollama_host("   ")
    assert result.host == _DEFAULT_OLLAMA_HOST
    assert captured["base"] == _DEFAULT_OLLAMA_HOST


def test_route_returns_the_reachability_verdict(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(OllamaProfile, "ping_host", lambda self, **_kw: (True, "0.5.1", None))
    client = TestClient(app)
    resp = client.post("/api/ai/ollama/health", json={"host": "http://box:11434"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert body["version"] == "0.5.1"
    assert body["host"] == "http://box:11434"
    assert "latency_ms" in body
