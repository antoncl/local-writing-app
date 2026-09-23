"""Cost/token-estimate half of the preview route's tests, split out of
test_ai_preview.py for the file-size guard (ADR-0092 S2)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.services.ai.sessions import default_registry


class PreviewCostEstimateTests(unittest.TestCase):
    """Step 3 of V2: AIPreviewResponse now includes estimated_tokens,
    cache_blocks[], estimated_cost_usd, provider/model, cached.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        # Patch machine_settings config path so assistant resolution finds
        # OUR temp assistant file, not whatever's on the developer's disk.
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        (folder / "sonnet.md").write_text(
            "---\n"
            "id: sonnet\n"
            "title: Sonnet\n"
            "entry_type: assistant:assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-sonnet-4-6\n"
            "---\n",
            encoding="utf-8",
        )
        (folder / "phantom.md").write_text(
            "---\n"
            "id: phantom\n"
            "title: Phantom\n"
            "entry_type: assistant:assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: not-a-real-model\n"
            "---\n",
            encoding="utf-8",
        )
        self.service = open_test_project(self.root, "Cost Tests")
        self.service = self.service
        default_registry.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        default_registry.clear()
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _basic_preview_body(self, *, assistant_id: str | None = None) -> dict:
        body: dict = {
            "template_source": (
                '{% role "system" %}You write fiction. Stay concise.{% endrole %}'
                '{% role "user" %}Continue from here.{% endrole %}'
            ),
            "target_scene_id": "",
        }
        if assistant_id is not None:
            body["assistant_id"] = assistant_id
        return body

    def test_estimated_tokens_populated_without_assistant(self) -> None:
        # No assistant_id: token count still works (universal tokenizer),
        # but cost fields stay null.
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertGreater(body["estimated_tokens"], 0)
        self.assertIsNone(body["estimated_cost_usd"])
        self.assertIsNone(body["provider"])
        self.assertIsNone(body["model"])
        self.assertIsNone(body["cached"])

    def test_cache_blocks_are_the_send_path_composition(self) -> None:
        # ADR-0060 §6: cache_blocks are the send-path composition, tier-tagged, each
        # carrying its text. This basic (lore-free) prompt → a stable system block
        # then an uncached user turn.
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        body = response.json()
        self.assertEqual(len(body["cache_blocks"]), 2)
        first, second = body["cache_blocks"]
        self.assertEqual((first["role"], first["tier"]), ("system", "stable"))
        self.assertEqual((second["role"], second["tier"]), ("user", None))
        self.assertIn("You write fiction", first["text"])
        # Tokens summed across blocks equal the top-level estimate.
        self.assertEqual(
            sum(b["tokens"] for b in body["cache_blocks"]),
            body["estimated_tokens"],
        )

    def test_assistant_id_populates_provider_model_and_cost(self) -> None:
        response = self.client.post(
            "/api/ai/preview", json=self._basic_preview_body(assistant_id="sonnet")
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["provider"], "anthropic")
        self.assertEqual(body["model"], "claude-sonnet-4-6")
        self.assertTrue(body["cached"])
        # claude-sonnet-4-6 has positive cost_in_per_mtok in the bake-in →
        # cost > 0 for non-empty input.
        self.assertIsNotNone(body["estimated_cost_usd"])
        self.assertGreater(body["estimated_cost_usd"], 0.0)
        # #1052: cache-aware — this is an explicit-caching model with a stable
        # system prefix, so the FIRST send (cache writes on that prefix) costs
        # strictly more than a settled send (cache reads).
        self.assertIsNotNone(body["estimated_first_cost_usd"])
        self.assertGreater(body["estimated_first_cost_usd"], body["estimated_cost_usd"])

    def test_unknown_model_yields_null_cost_but_keeps_provider_model(self) -> None:
        # phantom assistant references a model not in the bake-in.
        # Provider/model/cached still surface (we know the provider);
        # cost stays null because descriptor lookup fails.
        response = self.client.post(
            "/api/ai/preview", json=self._basic_preview_body(assistant_id="phantom")
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["provider"], "anthropic")
        self.assertEqual(body["model"], "not-a-real-model")
        self.assertTrue(body["cached"])
        self.assertIsNone(body["estimated_cost_usd"])
        self.assertIsNone(body["estimated_first_cost_usd"])
        # Tokens still count even when cost can't be calculated.
        self.assertGreater(body["estimated_tokens"], 0)

    def test_bound_preview_projects_cache_plan_onto_blocks(self) -> None:
        # ADR-0084 §6: an Anthropic-bound preview's cache_blocks carry the
        # plan's projection — the stable system block gets a 1h term, the
        # uncached user turn gets none.
        response = self.client.post(
            "/api/ai/preview", json=self._basic_preview_body(assistant_id="sonnet")
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        system_block, user_block = body["cache_blocks"]
        self.assertEqual(system_block["role"], "system")
        self.assertTrue(system_block["cached"])
        self.assertEqual(system_block["ttl_seconds"], 3600)
        self.assertEqual(user_block["role"], "user")
        self.assertFalse(user_block["cached"])
        self.assertIsNone(user_block["ttl_seconds"])

        # Unbound: no provider resolved, so no plan — every block is
        # cached=False, ttl_seconds=None.
        unbound = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        unbound_body = unbound.json()
        self.assertIsNone(unbound_body["cached"])
        for block in unbound_body["cache_blocks"]:
            self.assertFalse(block["cached"])
            self.assertIsNone(block["ttl_seconds"])

    def _write_assistant(self, filename: str, *, provider: str, model: str) -> str:
        assistant_id = filename
        folder = self.config_dir / "assistants"
        (folder / f"{filename}.md").write_text(
            "---\n"
            f"id: {assistant_id}\n"
            f"title: {assistant_id}\n"
            "entry_type: assistant:assistant\n"
            "metadata:\n"
            f"  ai_provider: {provider}\n"
            f"  ai_model: {model}\n"
            "---\n",
            encoding="utf-8",
        )
        return assistant_id

    def test_bound_preview_projects_gemini_cache_plan_onto_blocks(self) -> None:
        # ADR-0084 §3/§6: an OpenRouter-bound Gemini assistant projects the
        # fixed 5-minute Gemini term onto the stable system block; the
        # uncached user turn carries no ttl. `list_models` is stubbed so the
        # test never reaches OpenRouter's live catalogue.
        assistant_id = self._write_assistant(
            "gemini", provider="openrouter", model="google/gemini-2.5-pro"
        )
        with patch(
            "app.services.ai.profiles.openrouter.OpenRouterProfile.list_models",
            new=AsyncMock(return_value=[]),
        ):
            response = self.client.post(
                "/api/ai/preview", json=self._basic_preview_body(assistant_id=assistant_id)
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["cached"])
        system_block, user_block = body["cache_blocks"]
        self.assertEqual(system_block["role"], "system")
        self.assertTrue(system_block["cached"])
        self.assertEqual(system_block["ttl_seconds"], 300)
        self.assertEqual(user_block["role"], "user")
        self.assertFalse(user_block["cached"])
        self.assertIsNone(user_block["ttl_seconds"])

    def test_bound_preview_projects_deepseek_cache_plan_onto_blocks(self) -> None:
        # ADR-0084 §3/§6: DeepSeek routes through OpenRouter's auto/prefix
        # cache strategy (collapse mode, no per-block ttl) — `cached` is True
        # but no block projects a `ttl_seconds`; the user turn still reads
        # uncached because it carries no tier.
        assistant_id = self._write_assistant(
            "deepseek", provider="openrouter", model="deepseek/deepseek-chat"
        )
        with patch(
            "app.services.ai.profiles.openrouter.OpenRouterProfile.list_models",
            new=AsyncMock(return_value=[]),
        ):
            response = self.client.post(
                "/api/ai/preview", json=self._basic_preview_body(assistant_id=assistant_id)
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["cached"])
        system_block, user_block = body["cache_blocks"]
        self.assertEqual(system_block["role"], "system")
        self.assertTrue(system_block["cached"])
        self.assertIsNone(system_block["ttl_seconds"])
        self.assertEqual(user_block["role"], "user")
        self.assertFalse(user_block["cached"])
        self.assertIsNone(user_block["ttl_seconds"])

    def test_existing_fields_unchanged(self) -> None:
        # Smoke: V2 additions don't break v1 callers — old fields still in shape.
        response = self.client.post("/api/ai/preview", json=self._basic_preview_body())
        body = response.json()
        for key in ("messages", "warnings", "char_count", "session_id", "rendered"):
            self.assertIn(key, body, f"missing legacy field: {key}")
