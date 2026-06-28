"""HTTP integration tests for the research backend (slice 1).

Covers the research-structure routes (read / create / rename / move /
delete + cascade preview) and the per-note read/save routes. The shared
TreeStructureService is tested in isolation by test_tree_structure_service;
these tests prove the wiring end-to-end through FastAPI.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient

from app.main import app, service as global_service


class ResearchHttpEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Research Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers ----------------------------------------------------------

    def _read_tree(self) -> dict:
        response = self.client.get("/api/research-structure")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _create_node(
        self, title: str, entry_type: str, parent_id: str | None = None
    ) -> dict:
        payload = {"title": title, "entry_type": entry_type}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        response = self.client.post("/api/research-structure/nodes", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _find(self, node: dict, predicate) -> dict | None:
        if predicate(node):
            return node
        for child in node.get("children", []):
            found = self._find(child, predicate)
            if found is not None:
                return found
        return None

    # --- fresh state ------------------------------------------------------

    def test_fresh_project_has_empty_research_tree(self) -> None:
        tree = self._read_tree()
        self.assertEqual(tree["root"]["type"], "root")
        self.assertEqual(tree["root"]["title"], "Research")
        self.assertEqual(tree["root"]["children"], [])

    def test_fresh_project_has_research_storage_folder(self) -> None:
        self.assertTrue((self.root / "research" / "notes").is_dir())
        self.assertTrue((self.root / "research.structure.yaml").exists())

    # --- create -----------------------------------------------------------

    def test_create_topic_at_root(self) -> None:
        self._create_node("Industrial Revolution", "topic")
        tree = self._read_tree()
        self.assertEqual(len(tree["root"]["children"]), 1)
        topic = tree["root"]["children"][0]
        self.assertEqual(topic["type"], "topic")
        self.assertEqual(topic["title"], "Industrial Revolution")

    def test_create_topic_under_topic(self) -> None:
        parent = self._create_node("Industrial Revolution", "topic")
        parent_id = parent["root"]["children"][0]["id"]
        self._create_node("Factory conditions", "topic", parent_id=parent_id)
        tree = self._read_tree()
        outer = tree["root"]["children"][0]
        self.assertEqual(len(outer["children"]), 1)
        self.assertEqual(outer["children"][0]["title"], "Factory conditions")

    def test_create_note_writes_markdown_file(self) -> None:
        self._create_node("Lancashire mill towns", "note")
        notes_dir = self.root / "research" / "notes"
        files = list(notes_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        content = files[0].read_text(encoding="utf-8")
        self.assertIn("title: Lancashire mill towns", content)
        self.assertIn("entry_type: note", content)

    def test_create_note_under_topic_links_via_note_id(self) -> None:
        # Tree YAML uses `note_id` on disk; the API surfaces it as
        # `scene_id` on the model (TreeStructureService renames).
        topic = self._create_node("Industrial Revolution", "topic")
        topic_id = topic["root"]["children"][0]["id"]
        self._create_node("Mill towns", "note", parent_id=topic_id)

        on_disk = yaml.safe_load(
            (self.root / "research.structure.yaml").read_text(encoding="utf-8")
        )
        outer = on_disk["root"]["children"][0]
        self.assertEqual(outer["title"], "Industrial Revolution")
        leaf = outer["children"][0]
        self.assertIn("note_id", leaf)
        self.assertNotIn("scene_id", leaf)

    def test_create_under_note_is_rejected(self) -> None:
        self._create_node("Note A", "note")
        tree = self._read_tree()
        note_id = tree["root"]["children"][0]["id"]
        response = self.client.post(
            "/api/research-structure/nodes",
            json={"title": "child", "entry_type": "note", "parent_id": note_id},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_create_with_non_research_entry_type_is_rejected(self) -> None:
        response = self.client.post(
            "/api/research-structure/nodes",
            json={"title": "Bad", "entry_type": "scene"},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_create_abstract_entry_type_is_rejected(self) -> None:
        response = self.client.post(
            "/api/research-structure/nodes",
            json={"title": "Bad", "entry_type": "research"},
        )
        self.assertEqual(response.status_code, 422, response.text)

    # --- rename -----------------------------------------------------------

    def test_rename_topic(self) -> None:
        self._create_node("Old", "topic")
        tree = self._read_tree()
        node_id = tree["root"]["children"][0]["id"]
        response = self.client.patch(
            f"/api/research-structure/nodes/{node_id}",
            json={"title": "New"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        tree = response.json()
        self.assertEqual(tree["root"]["children"][0]["title"], "New")

    def test_rename_note_updates_front_matter_title(self) -> None:
        self._create_node("Original", "note")
        tree = self._read_tree()
        node_id = tree["root"]["children"][0]["id"]
        self.client.patch(
            f"/api/research-structure/nodes/{node_id}",
            json={"title": "Renamed"},
        )
        files = list((self.root / "research" / "notes").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("title: Renamed", files[0].read_text(encoding="utf-8"))

    # --- move -------------------------------------------------------------

    def test_move_topic_into_another_topic(self) -> None:
        a = self._create_node("A", "topic")
        a_id = a["root"]["children"][0]["id"]
        self._create_node("B", "topic")
        tree = self._read_tree()
        b_id = next(
            child["id"]
            for child in tree["root"]["children"]
            if child["title"] == "B"
        )
        response = self.client.post(
            f"/api/research-structure/nodes/{b_id}/move",
            json={"target_parent_id": a_id, "position": 0},
        )
        self.assertEqual(response.status_code, 200, response.text)
        tree = response.json()
        self.assertEqual(len(tree["root"]["children"]), 1)
        self.assertEqual(tree["root"]["children"][0]["title"], "A")
        self.assertEqual(tree["root"]["children"][0]["children"][0]["title"], "B")

    def test_move_into_descendant_is_rejected(self) -> None:
        parent = self._create_node("Outer", "topic")
        outer_id = parent["root"]["children"][0]["id"]
        self._create_node("Inner", "topic", parent_id=outer_id)
        tree = self._read_tree()
        inner_id = tree["root"]["children"][0]["children"][0]["id"]
        response = self.client.post(
            f"/api/research-structure/nodes/{outer_id}/move",
            json={"target_parent_id": inner_id, "position": 0},
        )
        self.assertEqual(response.status_code, 422, response.text)

    # --- delete -----------------------------------------------------------

    def test_cascade_preview_counts_descendants(self) -> None:
        parent = self._create_node("Topic", "topic")
        topic_id = parent["root"]["children"][0]["id"]
        self._create_node("Note 1", "note", parent_id=topic_id)
        self._create_node("Note 2", "note", parent_id=topic_id)
        response = self.client.get(
            f"/api/research-structure/nodes/{topic_id}/cascade-preview"
        )
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview["target_id"], topic_id)
        self.assertEqual(preview["descendant_scene_count"], 2)
        self.assertEqual(preview["descendant_container_count"], 0)

    def test_delete_topic_removes_descendant_note_files(self) -> None:
        parent = self._create_node("Topic", "topic")
        topic_id = parent["root"]["children"][0]["id"]
        self._create_node("Doomed note", "note", parent_id=topic_id)
        self.assertEqual(
            len(list((self.root / "research" / "notes").glob("*.md"))), 1
        )
        response = self.client.delete(
            f"/api/research-structure/nodes/{topic_id}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        tree = response.json()
        self.assertEqual(tree["root"]["children"], [])
        self.assertEqual(
            list((self.root / "research" / "notes").glob("*.md")), []
        )

    def test_delete_root_is_rejected(self) -> None:
        tree = self._read_tree()
        root_id = tree["root"]["id"]
        response = self.client.delete(
            f"/api/research-structure/nodes/{root_id}"
        )
        self.assertEqual(response.status_code, 422, response.text)

    # --- note read/save ---------------------------------------------------

    def test_read_note_returns_body_and_metadata(self) -> None:
        self._create_node("Mill towns", "note")
        tree = self._read_tree()
        leaf = tree["root"]["children"][0]
        # scene_id is the model-side ref; for research it backs the
        # note_id on disk.
        note_id = leaf["scene_id"]
        response = self.client.get(f"/api/research/notes/{note_id}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], note_id)
        self.assertEqual(body["title"], "Mill towns")
        self.assertEqual(body["entry_type"], "note")
        self.assertEqual(body["body"], "")

    def test_save_note_roundtrips_body_and_tags(self) -> None:
        self._create_node("Mill towns", "note")
        tree = self._read_tree()
        note_id = tree["root"]["children"][0]["scene_id"]

        # Read the current revision so the conditional save passes.
        current = self.client.get(f"/api/research/notes/{note_id}").json()

        response = self.client.put(
            f"/api/research/notes/{note_id}",
            json={
                "title": "Mill towns",
                "body": "Lancashire mills employed children from age 8.",
                "base_revision": current["revision"],
                "entry_type": "note",
                "metadata": {"tags": ["industrial", "labor"]},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(
            saved["body"],
            "Lancashire mills employed children from age 8.",
        )
        self.assertEqual(saved["metadata"], {"tags": ["industrial", "labor"]})

        reread = self.client.get(f"/api/research/notes/{note_id}").json()
        # Save normalizes non-empty bodies to end with a single newline,
        # matching the convention scene/lore writes use.
        self.assertEqual(
            reread["body"].rstrip(),
            "Lancashire mills employed children from age 8.",
        )
        self.assertEqual(reread["metadata"]["tags"], ["industrial", "labor"])

    def test_save_note_rejects_stale_revision(self) -> None:
        self._create_node("Note", "note")
        tree = self._read_tree()
        note_id = tree["root"]["children"][0]["scene_id"]

        response = self.client.put(
            f"/api/research/notes/{note_id}",
            json={
                "title": "Note",
                "body": "body",
                "base_revision": "stale-revision-value",
                "entry_type": "note",
                "metadata": {},
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_save_note_syncs_title_into_structure_tree(self) -> None:
        self._create_node("Original", "note")
        tree = self._read_tree()
        note_id = tree["root"]["children"][0]["scene_id"]
        current = self.client.get(f"/api/research/notes/{note_id}").json()

        self.client.put(
            f"/api/research/notes/{note_id}",
            json={
                "title": "Renamed via save",
                "body": "x",
                "base_revision": current["revision"],
                "entry_type": "note",
                "metadata": {},
            },
        )
        tree = self._read_tree()
        self.assertEqual(tree["root"]["children"][0]["title"], "Renamed via save")

    # --- validation -------------------------------------------------------

    def test_validation_does_not_flag_research_structure_missing(self) -> None:
        # A fresh project should pass validation — adding research.structure.yaml
        # to the required-files list shouldn't cause spurious errors.
        response = self.client.post("/api/project/validate")
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertNotIn(
            "Missing research.structure.yaml",
            " ".join(report.get("errors", [])),
        )


if __name__ == "__main__":
    unittest.main()
