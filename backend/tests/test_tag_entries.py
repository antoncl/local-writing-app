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

    def test_list_entries_carry_a_revision(self) -> None:
        """Review fix: the roster's `revision` was blank (`None`), so the
        frontend's `saveTagEntry` sent `base_revision: undefined` on the wire
        and the 409 staleness guard below never fired."""
        self.client.post("/api/tag-entries", json={"title": "Coastal", "entry_type": "tag:tag"})
        listed = self.client.get("/api/tag-entries").json()["tags"]
        self.assertTrue(listed)
        for entry in listed:
            self.assertTrue(entry["revision"])

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

    # --- save guards ---------------------------------------------------------

    def test_save_with_stale_base_revision_is_rejected(self) -> None:
        created = self.client.post(
            "/api/tag-entries", json={"title": "Coastal", "entry_type": "tag:tag"}
        ).json()
        tag_id = created["id"]
        stale_revision = self.client.get(f"/api/tag-entries/{tag_id}").json()["revision"]
        # Move the file on once so the captured revision is now behind disk.
        self.client.put(
            f"/api/tag-entries/{tag_id}",
            json={"title": "Seaside", "entry_type": "tag:tag", "metadata": {}},
        )
        response = self.client.put(
            f"/api/tag-entries/{tag_id}",
            json={
                "title": "Other",
                "entry_type": "tag:tag",
                "metadata": {},
                "base_revision": stale_revision,
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_save_without_entry_type_is_rejected(self) -> None:
        """Review fix: `SaveTagEntryRequest.entry_type` has no default — for a
        tag the entry type IS the vocabulary, so an omitted one 422s rather
        than silently retyping it (e.g. to `tag:tag`)."""
        created = self.client.post(
            "/api/tag-entries", json={"title": "Coastal", "entry_type": "tag:assistant_tag"}
        ).json()
        response = self.client.put(
            f"/api/tag-entries/{created['id']}",
            json={"title": "Seaside", "metadata": {}},
        )
        self.assertEqual(response.status_code, 422, response.text)

    # --- delete purges references ---------------------------------------------

    def test_delete_purges_reference_from_a_lore_entry(self) -> None:
        """Review fix: `delete_tag_entry` purges references the way
        `delete_lore_entry` does — a lore entry's `entity_ref_list` field
        pointing at a deleted tag must not keep a dangling id."""
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["motifs"] = {
            "name": "Motifs",
            "type": "entity_ref_list",
            "picker_config": {"sources": [{"kind": "tag"}]},
        }
        definition = data.setdefault("entry_types", {}).get("lore:character") or {}
        fields = list(definition.get("fields") or [])
        fields.insert(0, "motifs")
        definition["fields"] = fields
        data["entry_types"]["lore:character"] = definition
        self.service._write_yaml(schema_path, data)

        # Both node files written directly, straight to disk, and the tag
        # entry deleted below without any prior index-touching call — so the
        # delete's own (necessarily cold) index build is the first one to see
        # either file, exactly like a real project a user hand-edited.
        tag_path = self.root / "tags" / "coastal.md"
        tag_path.parent.mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            tag_path,
            {"id": "tag_coastal", "title": "Coastal", "entry_type": "tag:tag", "metadata": {}},
            "",
        )
        lore_path = self.root / "lore" / "hero.md"
        lore_path.parent.mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            lore_path,
            {
                "id": "lore_hero",
                "title": "Hero",
                "entry_type": "lore:character",
                "metadata": {"motifs": ["tag_coastal"]},
            },
            "Body.",
        )

        response = self.client.delete("/api/tag-entries/tag_coastal")
        self.assertEqual(response.status_code, 204, response.text)

        front_matter, _ = self.service._read_markdown_with_front_matter(lore_path, strict=True)
        self.assertNotIn("tag_coastal", front_matter.get("metadata", {}).get("motifs") or [])

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

    def test_first_ever_machine_tag_with_project_open_does_not_leave_index_stale(self) -> None:
        """B5 review fix. `_mutate_index_for_write` used to drop a write it
        could not place as "outside the chain" and leave the memo untouched —
        correct for a genuinely foreign path, wrong for `<machine>/tags/…`
        the FIRST time any machine-layer node (assistant or tag) is ever
        created: `_machine_layer_folder` gates on the folder already
        existing, so the memo built a moment ago (with a project open, no
        machine layer yet) has no machine layer to place the write against.
        Before the fix the immediate read below 404'd off that stale memo.
        """
        # Warm the memo BEFORE any machine-layer file exists — the autouse
        # `_isolate_machine_settings` fixture (conftest.py) starts every test
        # with neither an `assistants/` nor a `tags/` folder under the fake
        # machine config dir, so this really is the "layer doesn't exist yet"
        # memo.
        self.service._build_node_index()
        self.assertIsNone(self.service.machine_layer())

        response = self.client.post(
            "/api/tag-entries",
            json={"title": "Editor", "entry_type": "tag:assistant_tag", "layer_id": ""},
        )
        self.assertEqual(response.status_code, 200, response.text)
        tag_id = response.json()["id"]

        # The exact bug symptom: an immediate read off the (memoized) index.
        read = self.client.get(f"/api/tag-entries/{tag_id}")
        self.assertEqual(read.status_code, 200, read.text)

        listed = self.client.get("/api/tag-entries")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn(tag_id, [entry["id"] for entry in listed.json()["tags"]])

        # The machine layer is real now, and the memoized index actually
        # carries the tag under it — not merely reachable some other way.
        machine_layer = self.service.machine_layer()
        self.assertIsNotNone(machine_layer)
        index_entry = self.service._build_node_index().by_id[tag_id]
        self.assertEqual(index_entry.source_layer_id, machine_layer.id)

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
