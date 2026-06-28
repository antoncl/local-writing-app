"""Concrete-profile behaviour: caching style per provider, offline
fallback to bake-in, OpenRouter pricing parsing, Ollama caching=none.

We avoid hitting real APIs by injecting a fake httpx.AsyncClient via
monkeypatch. The profile classes own their HTTP usage, so monkeypatching
`httpx.AsyncClient` at module level is enough.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.services.ai.profiles import CapabilityTier, ModelDescriptor
from app.services.ai.profiles.anthropic import AnthropicProfile
from app.services.ai.profiles.ollama import OllamaProfile
from app.services.ai.profiles.openai import OpenAIProfile
from app.services.ai.profiles.openrouter import OpenRouterProfile

# --- httpx fake plumbing -----------------------------------------------


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
    """Stand-in for httpx.AsyncClient supporting `async with`. Returns a
    pre-canned JSON payload for any GET. Pass `raise_exc` to simulate a
    transport error."""

    def __init__(
        self,
        json_payload: Any = None,
        *,
        raise_exc: Exception | None = None,
        capture: dict | None = None,
        **_kwargs,
    ) -> None:
        self._payload = json_payload
        self._raise = raise_exc
        self._capture = capture

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def get(self, url: str, **kwargs) -> _FakeResponse:
        if self._capture is not None:
            self._capture["url"] = url
            self._capture["kwargs"] = kwargs
        if self._raise is not None:
            raise self._raise
        return _FakeResponse(self._payload)


def _patch_async_client(monkeypatch, module, *, payload=None, raise_exc=None, capture=None):
    def factory(**kwargs):
        return _FakeAsyncClient(
            json_payload=payload, raise_exc=raise_exc, capture=capture, **kwargs
        )

    monkeypatch.setattr(f"{module}.httpx.AsyncClient", factory)


# --- Tests -------------------------------------------------------------


def test_anthropic_caching_style_is_explicit():
    profile = AnthropicProfile(api_key="")
    assert profile.caching_style("claude-sonnet-4-6") == "explicit"


def test_openai_caching_style_is_auto():
    profile = OpenAIProfile(api_key="")
    assert profile.caching_style("gpt-4o") == "auto"


def test_ollama_caching_style_is_none():
    profile = OllamaProfile(host="http://localhost:11434")
    assert profile.caching_style("llama3.2") == "none"


def test_openrouter_caching_style_by_prefix():
    profile = OpenRouterProfile(api_key="")
    # Anthropic / Google routes need explicit markup.
    assert profile.caching_style("anthropic/claude-sonnet-4") == "explicit"
    assert profile.caching_style("google/gemini-2.5-pro") == "explicit"
    # OpenAI / DeepSeek / Groq route through to auto-cache providers.
    assert profile.caching_style("openai/gpt-4o") == "auto"
    assert profile.caching_style("deepseek/deepseek-chat") == "auto"
    # Unknown prefix: safe default.
    assert profile.caching_style("totallymadeup/x") == "none"


def test_anthropic_falls_back_to_bakein_without_key():
    profile = AnthropicProfile(api_key="")
    models = asyncio.run(profile.list_models())
    ids = {m.id for m in models}
    assert "claude-sonnet-4-6" in ids


def test_anthropic_falls_back_to_bakein_on_transport_error(monkeypatch):
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.anthropic",
        raise_exc=httpx.ConnectError("offline"),
    )
    profile = AnthropicProfile(api_key="sk-test")
    models = asyncio.run(profile.list_models())
    ids = {m.id for m in models}
    # Bake-in catalogue still surfaces.
    assert "claude-sonnet-4-6" in ids


def test_anthropic_marks_bakein_models_missing_from_live_as_deprecated(monkeypatch):
    # Live API returns only haiku — sonnet/opus/fable should be flagged
    # deprecated but still appear (so existing assistants don't error).
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.anthropic",
        payload={"data": [{"id": "claude-haiku-4-5-20251001"}]},
    )
    profile = AnthropicProfile(api_key="sk-test")
    models = asyncio.run(profile.list_models())
    by_id = {m.id: m for m in models}
    assert by_id["claude-haiku-4-5-20251001"].deprecated is False
    assert by_id["claude-sonnet-4-6"].deprecated is True


def test_openai_falls_back_to_bakein_without_key():
    profile = OpenAIProfile(api_key="")
    models = asyncio.run(profile.list_models())
    ids = {m.id for m in models}
    assert "gpt-4o" in ids


def test_ollama_returns_empty_on_unreachable_host(monkeypatch):
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.ollama",
        raise_exc=httpx.ConnectError("offline"),
    )
    profile = OllamaProfile(host="http://localhost:11434")
    models = asyncio.run(profile.list_models())
    assert models == []


def test_ollama_strips_v1_suffix_from_host():
    profile = OllamaProfile(host="http://localhost:11434/v1")
    assert profile._base == "http://localhost:11434"


def test_ollama_parses_local_tags(monkeypatch):
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.ollama",
        payload={
            "models": [
                {"name": "llama3.2:latest", "details": {"family": "llama"}},
                {"name": "llava:7b", "details": {"family": "llava"}},
            ]
        },
    )
    profile = OllamaProfile(host="http://localhost:11434")
    models = asyncio.run(profile.list_models())
    by_id = {m.id: m for m in models}
    assert "llama3.2:latest" in by_id
    assert by_id["llama3.2:latest"].tier == CapabilityTier.LOCAL
    # Vision capability inferred from family name.
    assert any(c.value == "vision" for c in by_id["llava:7b"].capabilities)


def test_ollama_model_for_tier_always_none():
    profile = OllamaProfile(host="http://localhost:11434")
    descriptors = [
        ModelDescriptor(
            id="llama3.2",
            display_name="llama3.2",
            provider="ollama",
            context_window=0,
            tier=CapabilityTier.LOCAL,
        )
    ]
    # Even with candidates in LOCAL, Ollama deliberately returns None —
    # the picker shows the explicit list, not an auto-rank pick.
    assert profile.model_for_tier(CapabilityTier.LOCAL, descriptors) is None


def test_openrouter_parses_pricing_and_buckets_tier(monkeypatch):
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.openrouter",
        payload={
            "data": [
                {
                    "id": "anthropic/claude-haiku-4.5",
                    "name": "Claude Haiku 4.5",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.0000008", "completion": "0.000004"},
                    "architecture": {"input_modalities": ["text", "image"]},
                    "supported_parameters": ["tools"],
                },
                {
                    "id": "openai/gpt-4o",
                    "name": "GPT-4o",
                    "context_length": 128000,
                    "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
                    "architecture": {"input_modalities": ["text", "image"]},
                    "supported_parameters": ["tools"],
                },
                {
                    "id": "anthropic/claude-opus-4",
                    "name": "Claude Opus 4",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000015", "completion": "0.000075"},
                    "architecture": {"input_modalities": ["text"]},
                    "supported_parameters": ["tools"],
                },
                {
                    "id": "openai/o3-mini",
                    "name": "o3-mini",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.0000011", "completion": "0.0000044"},
                    "architecture": {"input_modalities": ["text"]},
                    "supported_parameters": ["tools", "reasoning"],
                },
                {
                    "id": "free/promo",
                    "name": "Promo",
                    "context_length": 8000,
                    "pricing": {"prompt": "0", "completion": "0"},
                    "architecture": {"input_modalities": ["text"]},
                    "supported_parameters": [],
                },
            ]
        },
    )
    profile = OpenRouterProfile(api_key="")
    models = asyncio.run(profile.list_models())
    by_id = {m.id: m for m in models}

    # Free-tier promo (null pricing after parse) is filtered out — its
    # tier would be meaningless.
    assert "free/promo" not in by_id

    # Cost-bucket tier assignments.
    assert by_id["anthropic/claude-haiku-4.5"].tier == CapabilityTier.FAST
    assert by_id["openai/gpt-4o"].tier == CapabilityTier.BALANCED
    assert by_id["anthropic/claude-opus-4"].tier == CapabilityTier.PREMIUM
    # Reasoning override beats cost bucket — o3-mini is cheap but reasons.
    assert by_id["openai/o3-mini"].tier == CapabilityTier.REASONING

    # Pricing parsed into $/Mtok.
    assert by_id["openai/gpt-4o"].cost_in_per_mtok == pytest.approx(2.5)
    assert by_id["anthropic/claude-opus-4"].cost_out_per_mtok == pytest.approx(75.0)


def test_openrouter_offline_falls_back_to_bakein(monkeypatch):
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.openrouter",
        raise_exc=httpx.ConnectError("offline"),
    )
    profile = OpenRouterProfile(api_key="")
    models = asyncio.run(profile.list_models())
    # Bake-in has two seeds.
    ids = {m.id for m in models}
    assert "anthropic/claude-sonnet-4.6" in ids


def test_anthropic_sends_versioned_header(monkeypatch):
    # Sanity-check that we set anthropic-version + x-api-key on the
    # discovery request — anthropic rejects unversioned calls.
    captured: dict = {}
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.anthropic",
        payload={"data": []},
        capture=captured,
    )
    profile = AnthropicProfile(api_key="sk-test")
    asyncio.run(profile.list_models())
    assert "anthropic-version" in captured["kwargs"]["headers"]
    assert captured["kwargs"]["headers"]["x-api-key"] == "sk-test"


def test_openrouter_sends_bearer_when_key_present(monkeypatch):
    captured: dict = {}
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.openrouter",
        payload={"data": []},
        capture=captured,
    )
    profile = OpenRouterProfile(api_key="or-test")
    asyncio.run(profile.list_models())
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer or-test"
