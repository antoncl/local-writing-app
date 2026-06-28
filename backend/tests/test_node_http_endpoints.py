"""Phase 3c: HTTP shim over the unified node-CRUD service dispatchers.

Covers /api/nodes/{node_id} GET / PUT / DELETE across all the indexed
kinds. The per-kind endpoints (/api/scenes/{id}, /api/chats/{id}, ...)
stay intact and are tested separately — these tests target the unified
path only."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as global_service


class NodeHttpEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Node Http Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_chat(self, title: str = "Test Chat") -> dict:
        response = self.client.post("/api/chats", json={"title": title})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _create_lore(self, title: str = "Test Lore") -> dict:
        response = self.client.post(
            "/api/lore", json={"title": title, "entry_type": "lore_note"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # --- GET ----------------------------------------------------------------

    def test_get_chat_via_unified_endpoint(self) -> None:
        chat = self._create_chat()
        response = self.client.get(f"/api/nodes/{chat['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], chat["id"])
        self.assertEqual(body["title"], chat["title"])

    def test_get_lore_via_unified_endpoint(self) -> None:
        lore = self._create_lore()
        response = self.client.get(f"/api/nodes/{lore['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], lore["id"])

    def test_get_unknown_node_is_404(self) -> None:
        response = self.client.get("/api/nodes/scene_does_not_exist")
        self.assertEqual(response.status_code, 404)

    # --- PUT ----------------------------------------------------------------

    def test_put_chat_via_unified_endpoint(self) -> None:
        chat = self._create_chat()
        payload = {
            "title": "Renamed via /api/nodes",
            "prompt_entry_id": chat["prompt_entry_id"],
            "assistant_id": chat["assistant_id"],
            "system_prompt": chat["system_prompt"],
            "pinned": chat["pinned"],
            "context_items": chat["context_items"],
            "messages": chat["messages"],
        }
        response = self.client.put(f"/api/nodes/{chat['id']}", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], "Renamed via /api/nodes")

    def test_put_with_wrong_typed_field_is_422(self) -> None:
        chat = self._create_chat()
        # `messages` must be a list of message objects; passing a string
        # triggers Pydantic's type-validation 422. This proves the
        # dispatcher is parsing against SaveChatSessionRequest's schema
        # (not just dropping the body through).
        bad_payload = {"title": "X", "messages": "not-a-list"}
        response = self.client.put(f"/api/nodes/{chat['id']}", json=bad_payload)
        self.assertEqual(response.status_code, 422, response.text)

    def test_put_unknown_node_is_404(self) -> None:
        response = self.client.put(
            "/api/nodes/scene_nothing",
            json={"title": "X"},
        )
        self.assertEqual(response.status_code, 404)

    # --- DELETE -------------------------------------------------------------

    def test_delete_chat_via_unified_endpoint(self) -> None:
        chat = self._create_chat()
        chat_path = self.root / "chats" / f"{chat['id']}.yaml"
        self.assertTrue(chat_path.exists())
        response = self.client.delete(f"/api/nodes/{chat['id']}")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertFalse(chat_path.exists())

    def test_delete_lore_via_unified_endpoint(self) -> None:
        lore = self._create_lore()
        before = [e["id"] for e in self.client.get("/api/lore").json()["entries"]]
        self.assertIn(lore["id"], before)
        response = self.client.delete(f"/api/nodes/{lore['id']}")
        self.assertEqual(response.status_code, 204, response.text)
        after = [e["id"] for e in self.client.get("/api/lore").json()["entries"]]
        self.assertNotIn(lore["id"], after)

    def test_delete_unknown_node_is_404(self) -> None:
        response = self.client.delete("/api/nodes/scene_nothing")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
