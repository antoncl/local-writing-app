"""Step 5 of V2: chat, generate, and chat/stream endpoints surface
`usage` + `cost_usd` from the dispatch layer through to the wire.

Tests mock the dispatch helpers to return a known usage; the endpoints
look up the descriptor (bake-in), compute cost, and include both fields
in the response (or the NDJSON `done` line for streaming).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import UpdateProjectSettingsRequest
from app.services import machine_settings as ms
from app.services.ai import providers as ai_providers
from app.services.ai.profiles import UsageMetrics
from app.services.ai.profiles.base import ChatOutcome, ProviderError
from app.services.ai.sessions import default_registry

_ANTHROPIC_CHAT = "app.services.ai.profiles.anthropic.AnthropicProfile.chat"


def _set_machine_keys(**keys: str) -> ms.MachineSettings:
    return ms.MachineSettings(
        providers=ms.ProviderCredentials(
            anthropic_api_key=keys.get("anthropic", ""),
            openai_api_key=keys.get("openai", ""),
            openrouter_api_key=keys.get("openrouter", ""),
            ollama_host=keys.get("ollama_host", "http://127.0.0.1:11434"),
        ),
        default_provider=keys.get("default_provider", "anthropic"),
    )


def _anthropic_raw_with_usage() -> SimpleNamespace:
    # The raw response shape extract_usage understands. Cache numbers
    # are arbitrary but distinct so cost has all three input slots.
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1_000,
            cache_read_input_tokens=4_000,
            cache_creation_input_tokens=200,
            output_tokens=500,
        )
    )


class NonStreamingChatCostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Cost Tests")
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        default_registry.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def test_chat_response_includes_usage_and_cost(self) -> None:
        # Mock the dispatch helper to return a known raw response. The
        # endpoint will run extract_usage on it, look up the descriptor
        # (claude-haiku-4-5 from bake-in has positive pricing), compute
        # cost, and surface both fields.
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        raw = _anthropic_raw_with_usage()
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                _ANTHROPIC_CHAT,
                return_value=ChatOutcome("Reply.", "end_turn", raw),
             ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIsNotNone(body["usage"])
        self.assertEqual(body["usage"]["input_tokens"], 1_000)
        self.assertEqual(body["usage"]["cached_input_tokens"], 4_000)
        self.assertEqual(body["usage"]["cache_write_tokens"], 200)
        self.assertEqual(body["usage"]["output_tokens"], 500)
        self.assertIsNotNone(body["cost_usd"])
        # Haiku 4.5 pricing: cost should be > 0 and < $1 for this volume.
        self.assertGreater(body["cost_usd"], 0.0)
        self.assertLess(body["cost_usd"], 1.0)

    def test_chat_response_with_unknown_model_returns_null_cost(self) -> None:
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        raw = _anthropic_raw_with_usage()
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                _ANTHROPIC_CHAT,
                return_value=ChatOutcome("Reply.", "end_turn", raw),
             ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-no-such-model",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        body = response.json()
        self.assertTrue(body["ok"])
        # Usage still populates from the mocked raw response.
        self.assertIsNotNone(body["usage"])
        # But cost is null because the descriptor lookup found no pricing.
        self.assertIsNone(body["cost_usd"])

    def test_chat_response_on_failure_has_null_usage_and_cost(self) -> None:
        # Provider error path: ChatResult.usage is None → wire fields null.
        loaded = _set_machine_keys(anthropic="sk-ant-test")
        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                _ANTHROPIC_CHAT,
                side_effect=ProviderError("boom"),
             ):
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIsNone(body["usage"])
        self.assertIsNone(body["cost_usd"])


class StreamingChatCostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Cost Stream Tests")
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        default_registry.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _parse_ndjson(self, body: str) -> list[dict]:
        return [json.loads(line) for line in body.splitlines() if line.strip()]

    def test_stream_done_carries_usage_and_cost(self) -> None:
        loaded = _set_machine_keys(anthropic="sk-ant-test")

        usage = UsageMetrics(
            input_tokens=1_000,
            cached_input_tokens=4_000,
            cache_write_tokens=200,
            output_tokens=500,
        )

        def fake_stream(call):
            yield ai_providers.StreamDelta(text="Hi")
            yield ai_providers.StreamFinal(stop_reason="end_turn", usage=usage)

        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.profiles.anthropic.AnthropicProfile.chat_stream",
                side_effect=fake_stream,
             ):
            response = self.client.post(
                "/api/ai/chat/stream",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        events = self._parse_ndjson(response.text)
        done = next(e for e in events if e["type"] == "done")
        self.assertIn("usage", done)
        self.assertEqual(done["usage"]["input_tokens"], 1_000)
        self.assertEqual(done["usage"]["cached_input_tokens"], 4_000)
        self.assertEqual(done["usage"]["cache_write_tokens"], 200)
        self.assertEqual(done["usage"]["output_tokens"], 500)
        self.assertIn("cost_usd", done)
        self.assertGreater(done["cost_usd"], 0.0)

    def test_stream_done_without_usage_omits_cost(self) -> None:
        # Some stream variants don't return usage (e.g. when include_usage
        # didn't fire). The done line just has no usage/cost fields.
        loaded = _set_machine_keys(anthropic="sk-ant-test")

        def fake_stream(call):
            yield ai_providers.StreamDelta(text="Hi")
            yield ai_providers.StreamFinal(stop_reason="end_turn", usage=None)

        with patch("app.services.machine_settings.load_settings", return_value=loaded), \
             patch(
                "app.services.ai.profiles.anthropic.AnthropicProfile.chat_stream",
                side_effect=fake_stream,
             ):
            response = self.client.post(
                "/api/ai/chat/stream",
                json={
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        events = self._parse_ndjson(response.text)
        done = next(e for e in events if e["type"] == "done")
        self.assertNotIn("usage", done)
        self.assertNotIn("cost_usd", done)


class ManualPriceFillEndpointTests(unittest.TestCase):
    """ADR-0083 Amendment 1: an assistant's manual price fills the cost for a
    model the oracle can't price, end-to-end through the non-stream chat turn
    (`run_chat_turn`) — the wiring a missed cost site would silently break."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Manual Price Tests")
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        # An assistant on a model the oracle/baked seed can't price, carrying a
        # manual USD price of 2 in / 8 out per 1M tokens.
        (folder / "priced.md").write_text(
            "---\n"
            "id: priced\n"
            "title: Priced\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-no-such-model\n"
            "  ai_price_in_usd_per_mtok: 2\n"
            "  ai_price_out_usd_per_mtok: 8\n"
            "---\n",
            encoding="utf-8",
        )
        ms.save_settings(
            ms.MachineSettings(
                providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
                default_provider="anthropic",
            )
        )
        default_registry.clear()

    def tearDown(self) -> None:
        default_registry.clear()
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_manual_price_fills_cost_for_unlisted_model(self) -> None:
        raw = SimpleNamespace(usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000))
        with patch(_ANTHROPIC_CHAT, return_value=ChatOutcome("Reply.", "end_turn", raw)):
            response = self.client.post(
                "/api/ai/chat",
                json={"assistant_id": "priced", "messages": [{"role": "user", "content": "hi"}]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        # The unlisted model has no oracle/baked price, but the assistant's
        # manual 2/8 fills it: 1M input @2 + 1M output @8 = $10.
        self.assertIsNotNone(body["cost_usd"])
        self.assertAlmostEqual(body["cost_usd"], 10.0, places=6)


if __name__ == "__main__":
    unittest.main()
