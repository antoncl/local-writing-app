"""Service-level tests for mid-scene lore mutation markers (GH #33, #50).

Mutations are self-contained HTML-comment markers in scene markdown carrying the
new field value at the point of change. This slice owns the marker pattern, the
per-scene scan, and the intentful single-marker mutators (rewrite/remove without
a full body save). HTTP routes arrive in #54, so these exercise the service
directly.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpdateMutationRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService


def _setup_honor(service: ProjectService) -> str:
    """Define a `rank` field on characters and create a real `Honor` character,
    returning its id — mutations must target a real lore entity (#53)."""
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id="rank",
            field=MetadataFieldDefinition(name="Rank", type="text"),
            entry_type="lore:character",
        )
    )
    return service.create_lore_entry(
        CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
    ).id


class LoreMutationScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Lore Mutation Tests")
        self.honor = _setup_honor(self.service)
        self.client = TestClient(app)
        scene = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.assertEqual(scene.status_code, 200, scene.text)
        self.scene_id = scene.json()["id"]
        # Two co-authored markers (a promotion sets rank + title) plus a value
        # needing url-decoding, to prove the encode/decode round-trip.
        self._save_body(
            f"Honor took the ship. <!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 -->"
            f"The crew saluted. <!-- mutate:entity={self.honor};field=title;value=Lady%20Dame;id=m2 -->"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers ----------------------------------------------------------

    def _save_body(self, body: str) -> None:
        response = self.client.put(
            f"/api/scenes/{self.scene_id}",
            json={"title": "Chapter One", "body": body},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _scan(self) -> dict[str, object]:
        scene = self.service.read_scene(self.scene_id)
        return {m.marker_id: m for m in self.service._scan_scene_mutations(scene)}

    def _body(self) -> str:
        return self.service.read_scene(self.scene_id).body

    # --- scan -------------------------------------------------------------

    def test_scan_enumerates_all_markers(self) -> None:
        markers = self._scan()
        self.assertEqual(set(markers), {"m1", "m2"})
        self.assertEqual(markers["m1"].entity_id, self.honor)
        self.assertEqual(markers["m1"].field, "rank")
        self.assertEqual(markers["m1"].value, "Captain")
        self.assertEqual(markers["m1"].scene_id, self.scene_id)

    def test_scan_url_decodes_value(self) -> None:
        self.assertEqual(self._scan()["m2"].value, "Lady Dame")

    def test_scan_records_prose_order_offsets(self) -> None:
        markers = self._scan()
        # m1 comes before m2 in the prose, so its offset is smaller.
        self.assertLess(markers["m1"].offset, markers["m2"].offset)

    # --- update (atomic rewrite) -----------------------------------------

    def test_update_value_rewrites_single_marker(self) -> None:
        self.service.update_mutation(
            self.scene_id, "m1", UpdateMutationRequest(value="Commodore")
        )
        markers = self._scan()
        self.assertEqual(markers["m1"].value, "Commodore")
        self.assertEqual(markers["m2"].value, "Lady Dame")  # untouched

    def test_update_value_is_url_encoded(self) -> None:
        self.service.update_mutation(
            self.scene_id, "m1", UpdateMutationRequest(value="Rear Admiral")
        )
        self.assertIn("value=Rear%20Admiral", self._body())
        self.assertEqual(self._scan()["m1"].value, "Rear Admiral")

    def test_update_field_only_preserves_value_encoding(self) -> None:
        self.service.update_mutation(self.scene_id, "m2", UpdateMutationRequest(field="rank"))
        # Field changed but the pre-encoded value must survive verbatim.
        self.assertIn("field=rank;value=Lady%20Dame", self._body())
        self.assertEqual(self._scan()["m2"].value, "Lady Dame")

    def test_update_missing_marker_is_404(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self.service.update_mutation(self.scene_id, "nope", UpdateMutationRequest(value="x"))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    # --- delete -----------------------------------------------------------

    def test_delete_removes_only_the_marker(self) -> None:
        self.service.delete_mutation(self.scene_id, "m2")
        body = self._body()
        self.assertNotIn("id=m2", body)
        self.assertIn("The crew saluted.", body)  # surrounding prose survives
        self.assertEqual(set(self._scan()), {"m1"})

    def test_delete_missing_marker_is_404(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self.service.delete_mutation(self.scene_id, "nope")
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)


class LoreMutationResolverTests(unittest.TestCase):
    """The mutations index + effective_state resolver (#51). Proves the #33
    acceptance shape at the service level: an earlier scene sees the old value,
    a later scene the new one, resolution is position-granular within a scene,
    and the latest-started record wins."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Resolver Tests")
        self.honor = _setup_honor(self.service)
        self.client = TestClient(app)
        # Three scenes in manuscript order: s1 (before), s2 (rank->Captain),
        # s3 (rank->Commodore).
        self.s1 = self._new_scene("Scene One", "Honor commands the fleet.")
        self.s2 = self._new_scene(
            "Scene Two",
            f"Before. <!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 --> After.",
        )
        self.s3 = self._new_scene(
            "Scene Three",
            f"Later still. <!-- mutate:entity={self.honor};field=rank;value=Commodore;id=m2 -->",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str) -> str:
        created = self.client.post("/api/scenes", json={"title": title})
        self.assertEqual(created.status_code, 200, created.text)
        scene_id = created.json()["id"]
        saved = self.client.put(
            f"/api/scenes/{scene_id}", json={"title": title, "body": body}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    # --- index ------------------------------------------------------------

    def test_index_orders_records_by_manuscript_position(self) -> None:
        index = self.service.build_mutations_index()
        records = index.by_entity[self.honor]
        self.assertEqual([m.marker_id for m in records], ["m1", "m2"])
        # Manuscript order reflects scene-creation order here.
        self.assertLess(index.scene_order[self.s1], index.scene_order[self.s2])
        self.assertLess(index.scene_order[self.s2], index.scene_order[self.s3])

    def test_index_version_changes_when_a_marker_changes(self) -> None:
        before = self.service.build_mutations_index().version
        self.service.update_mutation(
            self.s2, "m1", UpdateMutationRequest(value="Commander")
        )
        self.assertNotEqual(before, self.service.build_mutations_index().version)

    # --- effective_state: manuscript-order redaction (#33) ---------------

    def test_earlier_scene_sees_no_override(self) -> None:
        self.assertEqual(self.service.effective_state(self.honor, self.s1), {})

    def test_mutation_scene_and_after_see_new_value(self) -> None:
        self.assertEqual(self.service.effective_state(self.honor, self.s2), {"rank": "Captain"})

    def test_latest_started_record_wins(self) -> None:
        # By scene 3 the later rank record shadows the earlier one.
        self.assertEqual(self.service.effective_state(self.honor, self.s3), {"rank": "Commodore"})

    def test_unknown_scene_yields_base_only(self) -> None:
        self.assertEqual(self.service.effective_state(self.honor, "does-not-exist"), {})

    def test_unmutated_entity_yields_empty(self) -> None:
        self.assertEqual(self.service.effective_state("nimitz", self.s2), {})

    # --- position-granular resolution within a scene ----------------------

    def test_position_before_marker_is_not_live(self) -> None:
        index = self.service.build_mutations_index()
        offset = index.by_entity[self.honor][0].offset
        # A cursor just before the marker sees the old (base) value.
        self.assertEqual(
            self.service.effective_state(self.honor, self.s2, position=offset - 1, index=index), {}
        )

    def test_position_at_or_after_marker_is_live(self) -> None:
        index = self.service.build_mutations_index()
        offset = index.by_entity[self.honor][0].offset
        self.assertEqual(
            self.service.effective_state(self.honor, self.s2, position=offset, index=index),
            {"rank": "Captain"},
        )


if __name__ == "__main__":
    unittest.main()
