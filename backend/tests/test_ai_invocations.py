"""Roleplay Phase C: ai_invocations sidecar log + cost computed field.

The continuation/roleplay accept handler POSTs one invocation record per
accept; per-character cost and the scene-scoped `cost` computed field are
projections from the log.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app


class AIInvocationLogEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Invocation Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_empty_list_when_no_invocations_yet(self) -> None:
        response = self.client.get("/api/ai/invocations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"invocations": []})

    def test_append_persists_record_and_returns_with_id_and_ts(self) -> None:
        response = self.client.post(
            "/api/ai/invocations",
            json={
                "prompt_entry_id": "prompt_1",
                "prompt_entry_type": "prompt:general",
                "scene_id": "scene_1",
                "provider": "anthropic",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 200,
                    "cache_write_tokens": 0,
                    "output_tokens": 500,
                },
                "cost_usd": 0.0123,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("inv_"))
        self.assertTrue(body["ts"])
        self.assertEqual(body["scene_id"], "scene_1")
        self.assertEqual(body["model"], "claude-opus-4-7")
        self.assertEqual(body["usage"]["input_tokens"], 1000)
        self.assertAlmostEqual(body["cost_usd"], 0.0123, places=6)
        # File on disk.
        log_path = self.root / "ai_invocations.yaml"
        self.assertTrue(log_path.exists())

    def test_list_filters_by_scene_id(self) -> None:
        for scene_id in ("scene_a", "scene_a", "scene_b"):
            self.client.post(
                "/api/ai/invocations",
                json={"scene_id": scene_id, "cost_usd": 0.01},
            )
        response = self.client.get("/api/ai/invocations?scene_id=scene_a")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["invocations"]), 2)
        self.assertTrue(all(inv["scene_id"] == "scene_a" for inv in body["invocations"]))

    def test_list_filters_by_character_id(self) -> None:
        for character_id in ("lore_alice", "lore_bob", "lore_alice"):
            self.client.post(
                "/api/ai/invocations",
                json={
                    "scene_id": "scene_1",
                    "character_id": character_id,
                    "cost_usd": 0.005,
                },
            )
        response = self.client.get(
            "/api/ai/invocations?character_id=lore_alice"
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["invocations"]), 2)
        self.assertTrue(
            all(inv["character_id"] == "lore_alice" for inv in body["invocations"])
        )

    def test_appends_grow_existing_log_rather_than_overwrite(self) -> None:
        for cost in (0.01, 0.02, 0.03):
            self.client.post(
                "/api/ai/invocations",
                json={"scene_id": "scene_1", "cost_usd": cost},
            )
        body = self.client.get("/api/ai/invocations").json()
        self.assertEqual(len(body["invocations"]), 3)
        costs = sorted(inv["cost_usd"] for inv in body["invocations"])
        self.assertEqual(costs, [0.01, 0.02, 0.03])

    def test_malformed_log_records_are_skipped_gracefully(self) -> None:
        self.client.post(
            "/api/ai/invocations",
            json={"scene_id": "scene_1", "cost_usd": 0.04},
        )
        # Hand-corrupt one record in the YAML.
        path = self.root / "ai_invocations.yaml"
        import yaml as _yaml
        data = _yaml.safe_load(path.read_text(encoding="utf-8"))
        data["invocations"].append("not a dict")
        data["invocations"].append({"id": "missing required fields"})
        path.write_text(
            _yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
        )
        # The valid record still comes back; the bad ones are dropped.
        body = self.client.get("/api/ai/invocations").json()
        self.assertEqual(len(body["invocations"]), 1)


class CostComputedFieldTests(unittest.TestCase):
    """`cost` is the third computed-field function. Sums invocations whose
    scene_id matches the scene that's being computed."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Cost Computed Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self) -> str:
        """Create a scene and return its id."""
        response = self.client.post(
            "/api/scenes",
            json={"title": "Untitled scene"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def _read_scene(self, scene_id: str) -> dict:
        response = self.client.get(f"/api/scenes/{scene_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_cost_field_is_zero_when_no_invocations(self) -> None:
        scene_id = self._new_scene()
        scene = self._read_scene(scene_id)
        self.assertIn("cost", scene["computed_metadata"])
        self.assertEqual(scene["computed_metadata"]["cost"], 0.0)

    def test_cost_field_sums_invocations_for_this_scene(self) -> None:
        a = self._new_scene()
        b = self._new_scene()
        # Three for a, one for b.
        for cost in (0.01, 0.02, 0.005):
            self.client.post(
                "/api/ai/invocations",
                json={"scene_id": a, "cost_usd": cost},
            )
        self.client.post(
            "/api/ai/invocations",
            json={"scene_id": b, "cost_usd": 0.99},
        )
        scene_a = self._read_scene(a)
        scene_b = self._read_scene(b)
        self.assertAlmostEqual(
            scene_a["computed_metadata"]["cost"], 0.035, places=6
        )
        self.assertAlmostEqual(
            scene_b["computed_metadata"]["cost"], 0.99, places=6
        )

    def test_cost_field_skips_records_without_numeric_cost(self) -> None:
        scene_id = self._new_scene()
        for payload in (
            {"scene_id": scene_id, "cost_usd": 0.01},
            {"scene_id": scene_id, "cost_usd": None},
            {"scene_id": scene_id},  # cost_usd unset
        ):
            self.client.post("/api/ai/invocations", json=payload)
        scene = self._read_scene(scene_id)
        self.assertAlmostEqual(
            scene["computed_metadata"]["cost"], 0.01, places=6
        )


class CrossKindCostDispatchTests(unittest.TestCase):
    """Phase C2 Slice A. The `cost` function now dispatches by scope:
    scene-scoped on scenes, character-scoped on lore characters, and
    project-scoped on the project node. character_cost / project_cost are
    sibling field defs pinned to the right entry_types."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Cross-kind Cost Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_character(self, title: str = "Honor") -> str:
        response = self.client.post(
            "/api/lore",
            json={"title": title, "entry_type": "lore:character"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def test_character_cost_sums_invocations_by_character_id(self) -> None:
        alice = self._new_character("Alice")
        bob = self._new_character("Bob")
        # Two for Alice across two scenes, one for Bob.
        for scene_id, character_id, cost in (
            ("scene_a", alice, 0.01),
            ("scene_b", alice, 0.02),
            ("scene_a", bob, 0.99),
        ):
            self.client.post(
                "/api/ai/invocations",
                json={
                    "scene_id": scene_id,
                    "character_id": character_id,
                    "cost_usd": cost,
                },
            )
        alice_entry = self.client.get(f"/api/lore/{alice}").json()
        bob_entry = self.client.get(f"/api/lore/{bob}").json()
        self.assertAlmostEqual(
            alice_entry["computed_metadata"]["character_cost"], 0.03, places=6
        )
        self.assertAlmostEqual(
            bob_entry["computed_metadata"]["character_cost"], 0.99, places=6
        )

    def test_character_cost_is_zero_with_no_attributed_invocations(self) -> None:
        alice = self._new_character("Alice")
        # Invocation exists but isn't attributed to Alice.
        self.client.post(
            "/api/ai/invocations",
            json={"scene_id": "scene_a", "cost_usd": 0.5},
        )
        alice_entry = self.client.get(f"/api/lore/{alice}").json()
        self.assertEqual(
            alice_entry["computed_metadata"]["character_cost"], 0.0
        )

    def test_project_cost_sums_every_invocation(self) -> None:
        alice = self._new_character("Alice")
        for payload in (
            {"scene_id": "scene_a", "character_id": alice, "cost_usd": 0.10},
            {"scene_id": "scene_b", "cost_usd": 0.20},
            {"scene_id": "scene_c", "cost_usd": 0.30},
        ):
            self.client.post("/api/ai/invocations", json=payload)
        project = self.client.get("/api/project/node").json()
        self.assertAlmostEqual(
            project["computed_metadata"]["project_cost"], 0.60, places=6
        )

    def test_project_cost_is_zero_when_log_empty(self) -> None:
        project = self.client.get("/api/project/node").json()
        self.assertEqual(project["computed_metadata"]["project_cost"], 0.0)


class ChatSessionCostViaLogTests(unittest.TestCase):
    """Phase C2 Slice B. Chat-session cost is no longer accumulated on
    the chat YAML — each non-zero save delta lands as an ai_invocations
    row tagged with chat_session_id; cost_usd_total re-derives from the log.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Slice B Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_chat(self, title: str = "Test chat") -> str:
        from app.models import CreateChatSessionRequest
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title=title, system_prompt="")
        )
        return chat.id

    def _save_with_cost(self, chat_id: str, cost: float) -> None:
        from app.models import SaveChatSessionRequest
        existing = self.service.read_chat_session(chat_id)
        self.service.save_chat_session(
            chat_id,
            SaveChatSessionRequest(
                title=existing.title,
                prompt_entry_id=existing.prompt_entry_id,
                assistant_id=existing.assistant_id,
                system_prompt=existing.system_prompt,
                pinned=existing.pinned,
                cost_delta_usd=cost,
            ),
        )

    def test_chat_save_appends_invocation_row_with_chat_id(self) -> None:
        chat_id = self._create_chat()
        self._save_with_cost(chat_id, 0.05)
        response = self.client.get(
            f"/api/ai/invocations?chat_session_id={chat_id}"
        )
        body = response.json()
        self.assertEqual(len(body["invocations"]), 1)
        row = body["invocations"][0]
        self.assertEqual(row["chat_session_id"], chat_id)
        self.assertAlmostEqual(row["cost_usd"], 0.05, places=6)

    def test_chat_cost_usd_total_is_projection_of_log_rows(self) -> None:
        chat_id = self._create_chat()
        self._save_with_cost(chat_id, 0.10)
        self._save_with_cost(chat_id, 0.20)
        chat = self.service.read_chat_session(chat_id)
        # cost_usd_total is re-derived on every read; YAML value stays 0.
        self.assertAlmostEqual(chat.cost_usd_total, 0.30, places=6)

    def test_chat_cost_usd_total_is_none_when_no_priced_rows(self) -> None:
        # A fresh chat (no invocations) has an UNKNOWN total, not 0.0 — the
        # footer hides rather than showing a fabricated €0.00 (#697).
        chat_id = self._create_chat()
        chat = self.service.read_chat_session(chat_id)
        self.assertIsNone(chat.cost_usd_total)

    def test_chat_cost_usd_total_ignores_unpriced_rows(self) -> None:
        # A turn on an unpriced model records a cost_usd=None row; it must not
        # count as €0.00. With only such rows the total stays None (#697).
        from app.models import CreateAIInvocationRequest

        chat_id = self._create_chat()
        self.service.append_ai_invocation(
            CreateAIInvocationRequest(
                chat_session_id=chat_id, provider="ollama", model="llama3", cost_usd=None
            )
        )
        chat = self.service.read_chat_session(chat_id)
        self.assertIsNone(chat.cost_usd_total)

    def test_chat_cost_usd_total_sums_priced_and_ignores_unpriced(self) -> None:
        # Mixed chat (switched models mid-session): a priced turn makes the
        # total known — it's the sum of the priced rows; the unpriced row
        # contributes nothing rather than forcing the whole total to unknown.
        from app.models import CreateAIInvocationRequest

        chat_id = self._create_chat()
        self.service.append_ai_invocation(
            CreateAIInvocationRequest(
                chat_session_id=chat_id, provider="ollama", model="llama3", cost_usd=None
            )
        )
        self._save_with_cost(chat_id, 0.02)
        chat = self.service.read_chat_session(chat_id)
        self.assertAlmostEqual(chat.cost_usd_total, 0.02, places=6)

    # --- #1794: the recorded row's model is the turn's actual model, not
    # the assistant's static `ai_model` config (blank for tier assistants).

    def _save_turn(
        self,
        chat_id: str,
        *,
        cost: float,
        model: str | None = None,
        provider: str | None = None,
        assistant_id: str | None = None,
    ) -> None:
        from app.models import (
            ChatSessionMessage,
            ChatUsage,
            SaveChatSessionRequest,
        )

        existing = self.service.read_chat_session(chat_id)
        messages = [
            ChatSessionMessage(role="user", content="hi"),
            ChatSessionMessage(
                role="assistant",
                content="reply",
                usage=ChatUsage(input_tokens=10, output_tokens=5),
                provider=provider,
                model=model,
            ),
        ]
        self.service.save_chat_session(
            chat_id,
            SaveChatSessionRequest(
                title=existing.title,
                prompt_entry_id=existing.prompt_entry_id,
                assistant_id=assistant_id if assistant_id is not None else existing.assistant_id,
                system_prompt=existing.system_prompt,
                pinned=existing.pinned,
                messages=messages,
                cost_delta_usd=cost,
            ),
        )

    def _make_assistant(self, *, ai_model: str = "", ai_provider: str = "") -> str:
        from app.models import (
            CreateAssistantEntryRequest,
            SaveAssistantEntryRequest,
        )

        entry = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title="Assistant", layer_id=None)
        )
        self.service.save_assistant_entry(
            entry.id,
            SaveAssistantEntryRequest(
                title="Assistant",
                metadata={"ai_model": ai_model, "ai_provider": ai_provider},
            ),
        )
        return entry.id

    def _last_row(self, chat_id: str) -> dict:
        body = self.client.get(f"/api/ai/invocations?chat_session_id={chat_id}").json()
        return body["invocations"][-1]

    def test_chat_save_records_the_turns_actual_model_not_blank_config(self) -> None:
        # #1794: a tier-configured assistant leaves `ai_model` blank, so
        # reading the assistant config alone recorded model="" and every
        # row bucketed as "unknown model". The model actually used is
        # stamped on the assistant message (ADR-0076) — record THAT.
        chat_id = self._create_chat()
        self._save_turn(chat_id, cost=0.05, provider="anthropic", model="claude-sonnet-5")
        row = self._last_row(chat_id)
        self.assertEqual(row["model"], "claude-sonnet-5")
        self.assertEqual(row["provider"], "anthropic")

    def test_message_provenance_wins_over_assistant_static_config(self) -> None:
        # An exact-model assistant (ai_model set) whose turn ran on a
        # different model: the row records what the turn used, not the
        # stale config value.
        assistant_id = self._make_assistant(ai_model="config-model", ai_provider="config-prov")
        chat_id = self._create_chat()
        self._save_turn(
            chat_id,
            cost=0.05,
            provider="turn-prov",
            model="turn-model",
            assistant_id=assistant_id,
        )
        row = self._last_row(chat_id)
        self.assertEqual(row["model"], "turn-model")
        self.assertEqual(row["provider"], "turn-prov")

    def test_falls_back_to_assistant_config_when_message_lacks_provenance(self) -> None:
        # Older messages predate per-turn provenance (no model on the
        # message). The assistant's static config still covers them.
        assistant_id = self._make_assistant(ai_model="config-model", ai_provider="config-prov")
        chat_id = self._create_chat()
        self._save_turn(chat_id, cost=0.05, model=None, provider=None, assistant_id=assistant_id)
        row = self._last_row(chat_id)
        self.assertEqual(row["model"], "config-model")
        self.assertEqual(row["provider"], "config-prov")


if __name__ == "__main__":
    unittest.main()
