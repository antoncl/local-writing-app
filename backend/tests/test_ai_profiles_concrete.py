"""Concrete-profile behaviour: cache strategy per provider, offline
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
from app.services.ai.profiles.cache_strategy import (
    ANTHROPIC_BREAKPOINTS,
    GEMINI_BREAKPOINT,
    NO_CACHE,
    PREFIX_CACHE,
)
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


def test_anthropic_cache_strategy_caches():
    profile = AnthropicProfile(api_key="")
    assert profile.cache_strategy("claude-sonnet-4-6").caches is True


def test_anthropic_cache_strategy_is_anthropic_breakpoints():
    # ADR-0084: identity, not a string label.
    profile = AnthropicProfile(api_key="")
    assert profile.cache_strategy("claude-sonnet-4-6") is ANTHROPIC_BREAKPOINTS


def test_openai_cache_strategy_caches():
    profile = OpenAIProfile(api_key="")
    assert profile.cache_strategy("gpt-4o").caches is True


def test_openai_cache_strategy_is_prefix_cache():
    profile = OpenAIProfile(api_key="")
    assert profile.cache_strategy("gpt-4o") is PREFIX_CACHE


def test_ollama_cache_strategy_does_not_cache():
    profile = OllamaProfile(host="http://localhost:11434")
    assert profile.cache_strategy("llama3.2").caches is False


def test_ollama_cache_strategy_is_no_cache():
    profile = OllamaProfile(host="http://localhost:11434")
    assert profile.cache_strategy("llama3.2") is NO_CACHE


def test_openrouter_cache_strategy_caches_by_prefix():
    profile = OpenRouterProfile(api_key="")
    # Anthropic / Google routes carry markers; OpenAI / DeepSeek auto-cache.
    assert profile.cache_strategy("anthropic/claude-sonnet-4").caches is True
    assert profile.cache_strategy("google/gemini-2.5-pro").caches is True
    assert profile.cache_strategy("openai/gpt-4o").caches is True
    assert profile.cache_strategy("deepseek/deepseek-chat").caches is True
    # Unknown prefix: safe default.
    assert profile.cache_strategy("totallymadeup/x").caches is False


def test_openrouter_cache_strategy_by_prefix():
    profile = OpenRouterProfile(api_key="")
    # Anthropic needs explicit markup; Google gets its own strategy (ADR-0084 Slice 2).
    assert profile.cache_strategy("anthropic/claude-sonnet-4") is ANTHROPIC_BREAKPOINTS
    assert profile.cache_strategy("google/gemini-2.5-pro") is GEMINI_BREAKPOINT
    # OpenAI / DeepSeek / Groq route through to auto-cache providers.
    assert profile.cache_strategy("openai/gpt-4o") is PREFIX_CACHE
    assert profile.cache_strategy("deepseek/deepseek-chat") is PREFIX_CACHE
    # Unknown prefix: safe default.
    assert profile.cache_strategy("totallymadeup/x") is NO_CACHE


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


def test_anthropic_surfaces_live_only_models_as_unverified(monkeypatch):
    # ADR-0073 S4: a live model newer than the audit file is SHOWN (not dropped),
    # marked unverified with a derived tier and the provider's live display name.
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.anthropic",
        payload={
            "data": [
                {"id": "claude-haiku-4-5-20251001"},  # baked → stays verified
                {"id": "claude-opus-5-20260101", "display_name": "Opus 5"},  # live-only
            ]
        },
    )
    profile = AnthropicProfile(api_key="sk-test")
    by_id = {m.id: m for m in asyncio.run(profile.list_models())}
    new = by_id["claude-opus-5-20260101"]
    assert new.verified is False
    assert new.display_name == "Opus 5"
    assert isinstance(new.tier, CapabilityTier)
    assert new.deprecated is False
    # A baked model keeps its audited status.
    assert by_id["claude-haiku-4-5-20251001"].verified is True


def test_openai_falls_back_to_bakein_without_key():
    profile = OpenAIProfile(api_key="")
    models = asyncio.run(profile.list_models())
    ids = {m.id for m in models}
    assert "gpt-4o" in ids


def test_openai_surfaces_live_only_model_as_unverified(monkeypatch):
    # A live-only id surfaces unverified; with no live display name the raw id is
    # used as the name, and the tier is a best-effort derivation (BALANCED here —
    # the shared reasoning marker only catches the slash form `/o3`, not a bare
    # native `o3`, an accepted best-effort limit for an unverified row).
    _patch_async_client(
        monkeypatch,
        "app.services.ai.profiles.openai",
        payload={"data": [{"id": "gpt-4o"}, {"id": "gpt-5-turbo"}]},
    )
    profile = OpenAIProfile(api_key="sk-test")
    by_id = {m.id: m for m in asyncio.run(profile.list_models())}
    new = by_id["gpt-5-turbo"]
    assert new.verified is False
    assert new.display_name == "gpt-5-turbo"
    assert new.tier == CapabilityTier.BALANCED
    assert by_id["gpt-4o"].verified is True


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
                {
                    "id": "vendor/unpriced",
                    "name": "Unpriced",
                    "context_length": 8000,
                    "pricing": {},
                    "architecture": {"input_modalities": ["text"]},
                    "supported_parameters": [],
                },
            ]
        },
    )
    profile = OpenRouterProfile(api_key="")
    models = asyncio.run(profile.list_models())
    by_id = {m.id: m for m in models}

    # A genuinely free model (price "0") is KEPT — it's among the most useful
    # options for a local-first user — and buckets as FAST ($0 < $1). Only rows
    # with no usable price are dropped, since they can't be tiered (#1386).
    assert by_id["free/promo"].cost_in_per_mtok == 0.0
    assert by_id["free/promo"].tier == CapabilityTier.FAST
    assert "vendor/unpriced" not in by_id

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
