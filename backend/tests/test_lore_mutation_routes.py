"""HTTP tests for the mutation API routes (#54, #33).

Thin routes over the mixin: the per-entity timeline, effective-state at a
(scene, position), and the intentful PATCH/DELETE marker mutators. Insertion has
no route — the client mints the id and an ordinary scene save carries it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as svc
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)


class MutationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Mutation Route Tests")
        layers = svc.read_metadata_schema_layers()
        svc.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="rank",
                field=MetadataFieldDefinition(name="Rank", type="text"),
                entry_type="character",
            )
        )
        self.client = TestClient(app)
        self.honor = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="character")
        ).id
        self.s1 = self._new_scene("Scene One", "Honor commands.")
        self.s2 = self._new_scene(
            "Scene Two",
            "She was promoted. "
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 -->",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str) -> str:
        scene_id = self.client.post("/api/scenes", json={"title": title}).json()["id"]
        saved = self.client.put(
            f"/api/scenes/{scene_id}", json={"title": title, "body": body}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    # --- timeline ---------------------------------------------------------

    def test_timeline_lists_entity_mutations(self) -> None:
        response = self.client.get(f"/api/lore/{self.honor}/mutations")
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["marker_id"], "m1")
        self.assertEqual(items[0]["field"], "rank")
        self.assertEqual(items[0]["value"], "Captain")
        self.assertEqual(items[0]["scene_id"], self.s2)

    def test_timeline_empty_for_unmutated_entity(self) -> None:
        response = self.client.get("/api/lore/lore_nobody/mutations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])

    # --- effective state --------------------------------------------------

    def test_effective_before_change_is_empty(self) -> None:
        response = self.client.get(
            f"/api/lore/{self.honor}/effective", params={"scene": self.s1}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["values"], {})

    def test_effective_at_change_shows_override(self) -> None:
        response = self.client.get(
            f"/api/lore/{self.honor}/effective", params={"scene": self.s2}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["values"], {"rank": "Captain"})

    # --- PATCH / DELETE marker -------------------------------------------

    def test_patch_updates_marker_value(self) -> None:
        response = self.client.patch(
            f"/api/scenes/{self.s2}/mutations/m1", json={"value": "Commodore"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        effective = self.client.get(
            f"/api/lore/{self.honor}/effective", params={"scene": self.s2}
        ).json()["values"]
        self.assertEqual(effective, {"rank": "Commodore"})

    def test_delete_removes_marker(self) -> None:
        response = self.client.delete(f"/api/scenes/{self.s2}/mutations/m1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("id=m1", response.json()["body"])
        timeline = self.client.get(f"/api/lore/{self.honor}/mutations").json()["items"]
        self.assertEqual(timeline, [])

    def test_patch_to_unknown_entity_is_422(self) -> None:
        # PATCH rewrites in place, bypassing save_scene — it must validate too.
        response = self.client.patch(
            f"/api/scenes/{self.s2}/mutations/m1", json={"entity_id": "lore_ghost"}
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_patch_missing_marker_is_404(self) -> None:
        response = self.client.patch(
            f"/api/scenes/{self.s2}/mutations/nope", json={"value": "x"}
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_delete_missing_marker_is_404(self) -> None:
        response = self.client.delete(f"/api/scenes/{self.s2}/mutations/nope")
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
