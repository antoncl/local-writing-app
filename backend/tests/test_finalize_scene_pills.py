"""Finalize roleplay keeps the scene's mutation pills and todos (#2435)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from mutation_helpers import save_scenes_with_mutations
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateLoreEntryRequest, CreateTodoRequest
from app.services.project.finalize_placement import place_pills
from app.services.project.mutation_anchors import (
    anchors_as_markers,
    render_anchor,
    render_close,
)

ANCHOR = render_anchor("mutation_set_abc", "mut_aaa111")
CLOSE = render_close("mut_aaa111", "mut_ccc333")
OTHER = render_anchor("mutation_set_abc", "mut_bbb222")


class AnchorsAsMarkersTests(unittest.TestCase):
    def test_anchor_and_close_become_markers_and_nothing_else_survives(self) -> None:
        out = anchors_as_markers(f"a {ANCHOR} b {CLOSE} c")
        self.assertEqual(out, "a ⟦mut_aaa111⟧ b ⟦mut_ccc333⟧ c")
        self.assertNotIn("<!--", out)


class PlacePillsTests(unittest.TestCase):
    def test_marker_becomes_the_original_comment(self) -> None:
        body, unplaced = place_pills(f"x {ANCHOR} y", "Clean ⟦mut_aaa111⟧ prose.")
        self.assertEqual(body, f"Clean {ANCHOR} prose.")
        self.assertEqual(unplaced, [])

    def test_backticked_marker_is_unwrapped(self) -> None:
        body, _ = place_pills(ANCHOR, "Clean `⟦mut_aaa111⟧` prose.")
        self.assertEqual(body, f"Clean {ANCHOR} prose.")

    def test_duplicate_marker_is_placed_once(self) -> None:
        body, _ = place_pills(ANCHOR, "A ⟦mut_aaa111⟧ B ⟦mut_aaa111⟧ C")
        self.assertEqual(body.count(ANCHOR), 1)
        self.assertNotIn("⟦", body)

    def test_unknown_marker_is_removed(self) -> None:
        body, unplaced = place_pills("plain", "A ⟦mut_nope⟧ B")
        self.assertEqual(body, "A  B")
        self.assertEqual(unplaced, [])

    def test_unplaced_pills_are_appended_in_old_order_and_reported(self) -> None:
        old = f"{ANCHOR} text {OTHER} more {CLOSE}"
        body, unplaced = place_pills(old, "Clean ⟦mut_bbb222⟧ prose.")
        self.assertEqual(unplaced, ["mut_aaa111", "mut_ccc333"])
        self.assertEqual(body, f"Clean {OTHER} prose.\n\n{ANCHOR}\n{CLOSE}\n")

    def test_close_marker_is_restored_and_a_misordered_pair_loses_nothing(self) -> None:
        body, unplaced = place_pills(f"{ANCHOR} t {CLOSE}", "⟦mut_ccc333⟧ then ⟦mut_aaa111⟧")
        self.assertEqual(body, f"{CLOSE} then {ANCHOR}")
        self.assertEqual(unplaced, [])


class FinalizeKeepsPillsAndTodosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Finalize Pills")
        self.client = TestClient(app)
        self.scene_id = self.client.post("/api/scenes", json={"title": "The Tide"}).json()["id"]
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Marek", entry_type="lore:character")
        )
        self.marek = entry.id

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed(self) -> tuple[str, str]:
        """A scene with a pill, an embedded todo and a legacy anchored todo.
        Returns `(set_id, anchor_id)`."""
        ids = save_scenes_with_mutations(
            self.service,
            {
                self.scene_id: (
                    f"Before. <!-- mutate:entity={self.marek};field=rank;value=Captain;id=m1 --> After. "
                    "<!-- embedded-todo:id=et1;status=open;note=Check%20this -->the tale"
                    "<!-- /embedded-todo --> "
                    "<!-- embedded-todo:id=et2;status=done;note= -->settled<!-- /embedded-todo --> "
                    "<!-- todo-anchor:id=ta1 -->anchored<!-- /todo-anchor -->"
                )
            },
        )
        self.service.create_todo(
            CreateTodoRequest(text="Legacy item", scope="scene", scene_id=self.scene_id, anchor_id="ta1")
        )
        return ids["m1"]

    def test_finalize_places_pill_moves_todos_and_reports(self) -> None:
        set_id, anchor_id = self._seed()
        old = self.service.read_scene(self.scene_id).body
        self.assertIn(f"id={anchor_id}", old)

        result = self.service.finalize_scene(self.scene_id, f"Clean ⟦{anchor_id}⟧ prose.")

        body = self.service.read_scene(self.scene_id).body
        self.assertIn(render_anchor(set_id, anchor_id), body)
        self.assertNotIn("⟦", body)
        self.assertNotIn("embedded-todo", body)
        self.assertEqual(result.appended_changes, [])
        self.assertEqual(result.moved_todos, 3)  # 2 embedded + 1 detached legacy
        self.assertEqual(self.service.read_mutation_set_entry(set_id).state, "active")

        items = {item.text: item for item in self.service.read_todos().items}
        moved = items["Check this — “the tale”"]
        self.assertEqual((moved.scope, moved.scene_id, moved.anchor_id, moved.status),
                         ("scene", self.scene_id, None, "open"))
        self.assertEqual(items["“settled”"].status, "done")
        legacy = items["Legacy item"]
        self.assertIsNone(legacy.anchor_id)
        self.assertEqual(legacy.scene_id, self.scene_id)

    def test_unplaced_pill_is_appended_and_labelled_with_its_set_title(self) -> None:
        set_id, anchor_id = self._seed()
        title = self.service.read_mutation_set_entry(set_id).title

        result = self.service.finalize_scene(self.scene_id, "Clean prose, no markers.")

        body = self.service.read_scene(self.scene_id).body
        self.assertTrue(body.rstrip().endswith(render_anchor(set_id, anchor_id)))
        self.assertEqual(result.appended_changes, [title or anchor_id])
        self.assertEqual(self.service.read_mutation_set_entry(set_id).state, "active")

    def test_route_returns_the_scene_and_the_report(self) -> None:
        _, anchor_id = self._seed()
        response = self.client.post(
            f"/api/scenes/{self.scene_id}/finalize", json={"body": "No markers here."}
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["scene"]["id"], self.scene_id)
        self.assertEqual(len(data["appended_changes"]), 1)
        self.assertEqual(data["moved_todos"], 3)
        self.assertIn(f"id={anchor_id}", data["scene"]["body"])


if __name__ == "__main__":
    unittest.main()
