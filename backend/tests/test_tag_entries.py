"""HTTP integration tests for the `tag` kind (ADR-0082 slice 1, #1782).

Covers the dedicated `/api/tag-entries` CRUD, the unified `/api/nodes/{id}`
read/save/delete dispatch, the machine-layer (no project open) path the
assistant-tag vocabulary needs, and the entry-type upsert route accepting
`kind: "tag"`. Slice 1 registers the kind on the read + create path only —
no `create_missing`, no `tagged:` changes, no merge.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import clear_test_scope, open_test_project

from app.main import app
from app.services import machine_settings as ms


class TagEntryHttpEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Tag Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- create / list / read, open project --------------------------------

    def test_create_tag_writes_file_and_lists(self) -> None:
        response = self.client.post(
            "/api/tag-entries",
            json={"title": "Coastal", "entry_type": "tag:tag", "color": "moss"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("tag_"))
        self.assertEqual(body["entry_type"], "tag:tag")
        self.assertEqual(body["metadata"].get("color"), "moss")

        path = self.root / "tags" / "Coastal.md"
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn("id: " + body["id"], content)
        self.assertIn("entry_type: tag:tag", content)
        self.assertIn("color: moss", content)

        listed = self.client.get("/api/tag-entries")
        self.assertEqual(listed.status_code, 200, listed.text)
        ids = [entry["id"] for entry in listed.json()["tags"]]
        self.assertIn(body["id"], ids)

        # The node index carries it with kind "tag" and the project's own
        # layer id.
        index = self.service._build_node_index()
        index_entry = index.by_id[body["id"]]
        self.assertEqual(index_entry.kind, "tag")
        self.assertEqual(index_entry.source_layer_id, self.service._metadata_schema_layer_id(self.root))

    def test_create_abstract_entry_type_is_rejected(self) -> None:
        response = self.client.post(
            "/api/tag-entries",
            json={"title": "Bad", "entry_type": "tag:base"},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_create_with_non_tag_entry_type_is_rejected(self) -> None:
        response = self.client.post(
            "/api/tag-entries",
            json={"title": "Bad", "entry_type": "lore:note"},
        )
        self.assertEqual(response.status_code, 422, response.text)

    # --- unified /api/nodes dispatch ---------------------------------------

    def test_unified_read_save_delete(self) -> None:
        created = self.client.post(
            "/api/tag-entries",
            json={"title": "Coastal", "entry_type": "tag:tag"},
        ).json()
        tag_id = created["id"]

        read = self.client.get(f"/api/nodes/{tag_id}")
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["id"], tag_id)

        saved = self.client.put(
            f"/api/nodes/{tag_id}",
            json={
                "title": "Seaside",
                "entry_type": "tag:tag",
                "metadata": {"color": "amber"},
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["title"], "Seaside")
        self.assertTrue((self.root / "tags" / "Seaside.md").exists())
        self.assertFalse((self.root / "tags" / "Coastal.md").exists())

        deleted = self.client.delete(f"/api/nodes/{tag_id}")
        self.assertEqual(deleted.status_code, 204, deleted.text)

        index = self.service._build_node_index()
        self.assertNotIn(tag_id, index.by_id)

    # --- no project open, machine layer -------------------------------------

    def test_machine_layer_create_and_list_with_no_project_open(self) -> None:
        clear_test_scope()
        response = self.client.post(
            "/api/tag-entries",
            json={"title": "Editor", "entry_type": "tag:assistant_tag"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("tag_"))

        machine_dir = ms.config_path().parent
        self.assertTrue((machine_dir / "tags" / "Editor.md").exists())

        listed = self.client.get("/api/tag-entries")
        self.assertEqual(listed.status_code, 200, listed.text)
        ids = [entry["id"] for entry in listed.json()["tags"]]
        self.assertIn(body["id"], ids)

        assistants = self.client.get("/api/assistants")
        self.assertEqual(assistants.status_code, 200, assistants.text)
        assistant_ids = [entry["id"] for entry in assistants.json()["entries"]]
        self.assertNotIn(body["id"], assistant_ids)

    # --- entry-type upsert ---------------------------------------------------

    def test_upsert_entry_type_with_kind_tag(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        response = self.client.put(
            "/api/metadata/schema/entry-types",
            json={
                "layer_id": layer_id,
                "entry_type_id": "motifs",
                "entry_type": {"name": "Motifs", "kind": "tag", "parent": "tag:base"},
                "allow_existing": False,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        schema = response.json()
        self.assertIn("tag:motifs", schema["entry_types"])
        self.assertEqual(schema["entry_types"]["tag:motifs"]["kind"], "tag")


if __name__ == "__main__":
    unittest.main()
