"""Integration tests for the scene todo-anchor repair path (SceneTodoAnchorsMixin).

`todo-anchor` HTML-comment markers LINK a todo.yaml item to a position in a
scene body. `POST /api/project/repair` unwraps orphaned anchors (no backing
todo.yaml item) and collapses duplicate anchor ids, both via the shared
`MarkerMixin._apply_scene_marker_repair` machinery. This path had no direct
coverage before the marker-mixin extraction; these tests pin it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app


def _anchor(anchor_id: str, content: str) -> str:
    return f"<!-- todo-anchor:id={anchor_id} -->{content}<!-- /todo-anchor -->"


class SceneTodoAnchorRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Anchor Repair Tests")
        self.client = TestClient(app)
        scene = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.assertEqual(scene.status_code, 200, scene.text)
        self.scene_id = scene.json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _save_body(self, body: str) -> None:
        response = self.client.put(
            f"/api/scenes/{self.scene_id}",
            json={"title": "Chapter One", "body": body},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _body(self) -> str:
        return self.client.get(f"/api/scenes/{self.scene_id}").json()["body"]

    def _repair(self) -> None:
        response = self.client.post("/api/project/repair")
        self.assertEqual(response.status_code, 200, response.text)

    def test_repair_unwraps_orphan_and_collapses_duplicate(self) -> None:
        # A valid anchor (backed by a todo.yaml item), an orphan (no item), and
        # a duplicate of the valid id — all in one body, front-matter present.
        todo = self.client.post(
            "/api/todos",
            json={
                "text": "Backed anchor",
                "scope": "scene",
                "scene_id": self.scene_id,
                "anchor_id": "keep1",
            },
        )
        self.assertEqual(todo.status_code, 200, todo.text)
        self._save_body(
            f"Intro {_anchor('keep1', 'kept')} "
            f"mid {_anchor('orphan1', 'orphaned')} "
            f"end {_anchor('keep1', 'dupe')}"
        )

        self._repair()
        body = self._body()

        # Orphan comment gone, its prose survives (unwrapped).
        self.assertNotIn("orphan1", body)
        self.assertIn("orphaned", body)
        # Duplicate collapsed to exactly one keep1 anchor; both prose halves kept.
        self.assertEqual(body.count("todo-anchor:id=keep1"), 1)
        self.assertIn("kept", body)
        self.assertIn("dupe", body)

    def test_repair_leaves_a_clean_scene_untouched(self) -> None:
        # A single valid anchor with a backing item — nothing to repair, the body
        # (and its lone anchor comment) must survive verbatim.
        self.client.post(
            "/api/todos",
            json={
                "text": "Backed anchor",
                "scope": "scene",
                "scene_id": self.scene_id,
                "anchor_id": "solo",
            },
        )
        original = f"Before {_anchor('solo', 'text')} after"
        self._save_body(original)

        self._repair()

        # rstrip: the scene writer normalizes a trailing newline onto the body,
        # independent of anchor repair — the marker content must be untouched.
        self.assertEqual(self._body().rstrip("\n"), original)


if __name__ == "__main__":
    unittest.main()
