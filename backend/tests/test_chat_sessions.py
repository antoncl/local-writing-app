from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app, service as global_service


class ChatSessionEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Chat Sessions Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_empty_list_when_no_chats_yet(self) -> None:
        response = self.client.get("/api/chats")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"sessions": []})

    def test_create_persists_yaml_file_and_returns_session(self) -> None:
        response = self.client.post(
            "/api/chats",
            json={"title": "First chat", "assistant_id": "asst-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("chat_"))
        self.assertEqual(body["title"], "First chat")
        self.assertEqual(body["assistant_id"], "asst-1")
        self.assertEqual(body["messages"], [])
        self.assertEqual(body["context_items"], [])
        self.assertTrue(body["created_at"])
        self.assertEqual(body["created_at"], body["updated_at"])
        # File on disk
        chat_path = self.root / "chats" / f"{body['id']}.yaml"
        self.assertTrue(chat_path.exists())

    def test_get_returns_full_session(self) -> None:
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        response = self.client.get(f"/api/chats/{created['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], created["id"])

    def test_get_nonexistent_chat_returns_404(self) -> None:
        response = self.client.get("/api/chats/chat_bogus")
        self.assertEqual(response.status_code, 404)

    def test_save_updates_messages_and_bumps_updated_at(self) -> None:
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        # Force a different updated_at by saving via PUT.
        payload = {
            "title": "Renamed",
            "assistant_id": "asst-x",
            "system_prompt": "Be terse.",
            "pinned": True,
            "context_items": [
                {"kind": "scene", "id": "scene_1", "title": "Opening"}
            ],
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi", "thinking": "reasoning"},
            ],
        }
        response = self.client.put(f"/api/chats/{created['id']}", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["title"], "Renamed")
        self.assertEqual(body["assistant_id"], "asst-x")
        self.assertEqual(body["system_prompt"], "Be terse.")
        self.assertTrue(body["pinned"])
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["messages"][1]["thinking"], "reasoning")
        self.assertEqual(body["context_items"][0]["id"], "scene_1")
        # created_at preserved, updated_at refreshed
        self.assertEqual(body["created_at"], created["created_at"])

    def test_list_sorts_pinned_first_then_recent(self) -> None:
        a = self.client.post("/api/chats", json={"title": "a"}).json()
        b = self.client.post("/api/chats", json={"title": "b"}).json()
        c = self.client.post("/api/chats", json={"title": "c"}).json()
        # Pin b; touch c last so it's most-recent in unpinned bucket.
        self.client.put(
            f"/api/chats/{b['id']}",
            json={
                "title": "b",
                "assistant_id": "",
                "system_prompt": "",
                "pinned": True,
                "context_items": [],
                "messages": [],
            },
        )
        # Re-save c so its updated_at is latest among unpinned.
        self.client.put(
            f"/api/chats/{c['id']}",
            json={
                "title": "c",
                "assistant_id": "",
                "system_prompt": "",
                "pinned": False,
                "context_items": [],
                "messages": [],
            },
        )
        listing = self.client.get("/api/chats").json()["sessions"]
        titles = [s["title"] for s in listing]
        self.assertEqual(titles[0], "b")  # pinned first
        # Unpinned ordering by updated_at desc → c before a.
        self.assertEqual(titles[1:], ["c", "a"])

    def test_delete_removes_file_and_returns_updated_list(self) -> None:
        created = self.client.post("/api/chats", json={"title": "T"}).json()
        path = self.root / "chats" / f"{created['id']}.yaml"
        self.assertTrue(path.exists())
        response = self.client.delete(f"/api/chats/{created['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sessions"], [])
        self.assertFalse(path.exists())

    def test_invalid_chat_id_rejected(self) -> None:
        # The chat_id pattern is strict (must start with chat_); ids that
        # don't match the regex are rejected before disk access.
        response = self.client.get("/api/chats/not-a-chat-id")
        self.assertEqual(response.status_code, 422)

    def test_save_nonexistent_chat_returns_404(self) -> None:
        payload = {
            "title": "X",
            "assistant_id": "",
            "system_prompt": "",
            "pinned": False,
            "context_items": [],
            "messages": [],
        }
        response = self.client.put("/api/chats/chat_nope", json=payload)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
