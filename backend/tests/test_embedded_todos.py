"""HTTP integration tests for embedded (in-prose) TODOs (GH #45).

Embedded todos are HTML-comment markers in scene markdown carrying their own
status + note. These tests prove the rebuildable index read, the intentful
single-marker mutators (PATCH/DELETE without a full body save), and that the
existing search todo-scan still works after the shared-scan refactor.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app

MARKER = (
    "<!-- embedded-todo:id=t1;status=open;note=buy -->Buy milk<!-- /embedded-todo -->"
    " and "
    "<!-- embedded-todo:id=t2;status=done;note= -->Wrote outline<!-- /embedded-todo -->"
)


class EmbeddedTodoHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Embedded Todo Tests")
        self.client = TestClient(app)
        scene = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.assertEqual(scene.status_code, 200, scene.text)
        self.scene_id = scene.json()["id"]
        self._save_body(MARKER)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers ----------------------------------------------------------

    def _save_body(self, body: str) -> dict:
        response = self.client.put(
            f"/api/scenes/{self.scene_id}",
            json={"title": "Chapter One", "body": body},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _index(self) -> list[dict]:
        response = self.client.get("/api/todos/embedded")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def _body(self) -> str:
        return self.client.get(f"/api/scenes/{self.scene_id}").json()["body"]

    # --- index read -------------------------------------------------------

    def test_index_enumerates_all_markers(self) -> None:
        items = {item["todo_id"]: item for item in self._index()}
        self.assertEqual(set(items), {"t1", "t2"})
        self.assertEqual(items["t1"]["status"], "open")
        self.assertEqual(items["t1"]["note"], "buy")
        self.assertEqual(items["t1"]["text"], "Buy milk")
        self.assertEqual(items["t1"]["scene_id"], self.scene_id)
        self.assertEqual(items["t2"]["status"], "done")
        self.assertEqual(items["t2"]["note"], "")

    # --- status / note rewrite -------------------------------------------

    def test_patch_status_toggles_single_marker(self) -> None:
        response = self.client.patch(
            f"/api/scenes/{self.scene_id}/todos/t1", json={"status": "done"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        items = {item["todo_id"]: item for item in self._index()}
        self.assertEqual(items["t1"]["status"], "done")
        self.assertEqual(items["t2"]["status"], "done")  # untouched
        self.assertIn("embedded-todo:id=t1;status=done;note=buy", self._body())

    def test_patch_note_is_url_encoded(self) -> None:
        response = self.client.patch(
            f"/api/scenes/{self.scene_id}/todos/t1", json={"note": "needs review"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("note=needs%20review", self._body())
        items = {item["todo_id"]: item for item in self._index()}
        self.assertEqual(items["t1"]["note"], "needs review")
        self.assertEqual(items["t1"]["status"], "open")  # status preserved

    def test_patch_preserves_existing_encoded_note_when_only_status_changes(self) -> None:
        self.client.patch(
            f"/api/scenes/{self.scene_id}/todos/t1", json={"note": "a/b c"}
        )
        encoded_before = self._body()
        self.assertIn("note=a%2Fb%20c", encoded_before)
        # A status-only change must not re-encode (or corrupt) the stored note.
        self.client.patch(
            f"/api/scenes/{self.scene_id}/todos/t1", json={"status": "done"}
        )
        self.assertIn("note=a%2Fb%20c", self._body())

    # --- delete -----------------------------------------------------------

    def test_delete_unwraps_marker_keeping_text(self) -> None:
        response = self.client.delete(f"/api/scenes/{self.scene_id}/todos/t2")
        self.assertEqual(response.status_code, 200, response.text)
        body = self._body()
        self.assertNotIn("id=t2", body)
        self.assertIn("Wrote outline", body)  # prose survives
        self.assertEqual({item["todo_id"] for item in self._index()}, {"t1"})

    # --- not found --------------------------------------------------------

    def test_patch_missing_todo_is_404(self) -> None:
        response = self.client.patch(
            f"/api/scenes/{self.scene_id}/todos/nope", json={"status": "done"}
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_delete_missing_todo_is_404(self) -> None:
        response = self.client.delete(f"/api/scenes/{self.scene_id}/todos/nope")
        self.assertEqual(response.status_code, 404, response.text)

    # --- search regression (shared scan) ----------------------------------

    def test_search_still_returns_open_embedded_todos(self) -> None:
        response = self.client.post(
            "/api/search", json={"query": "", "include_open_todos": True}
        )
        self.assertEqual(response.status_code, 200, response.text)
        todo_hits = {hit["todo_id"]: hit for hit in response.json()["hits"] if hit.get("todo_id")}
        # Only the open marker (t1) shows; the done one (t2) is filtered out.
        self.assertIn("t1", todo_hits)
        self.assertNotIn("t2", todo_hits)
        self.assertEqual(todo_hits["t1"]["excerpt"], "buy")


if __name__ == "__main__":
    unittest.main()
