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

from app.main import app
from app.main import service as svc
from app.models import UpdateMutationRequest

# Two co-authored markers (a promotion sets rank + title) plus a value that
# needs url-decoding, to prove the encode/decode round-trip.
MARKERS = (
    "Honor took the ship. "
    "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
    "The crew saluted. "
    "<!-- mutate:entity=honor;field=title;value=Lady%20Dame;id=m2 -->"
)


class LoreMutationScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Lore Mutation Tests")
        self.client = TestClient(app)
        scene = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.assertEqual(scene.status_code, 200, scene.text)
        self.scene_id = scene.json()["id"]
        self._save_body(MARKERS)

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
        scene = svc.read_scene(self.scene_id)
        return {m.marker_id: m for m in svc._scan_scene_mutations(scene)}

    def _body(self) -> str:
        return svc.read_scene(self.scene_id).body

    # --- scan -------------------------------------------------------------

    def test_scan_enumerates_all_markers(self) -> None:
        markers = self._scan()
        self.assertEqual(set(markers), {"m1", "m2"})
        self.assertEqual(markers["m1"].entity_id, "honor")
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
        svc.update_mutation(
            self.scene_id, "m1", UpdateMutationRequest(value="Commodore")
        )
        markers = self._scan()
        self.assertEqual(markers["m1"].value, "Commodore")
        self.assertEqual(markers["m2"].value, "Lady Dame")  # untouched

    def test_update_value_is_url_encoded(self) -> None:
        svc.update_mutation(
            self.scene_id, "m1", UpdateMutationRequest(value="Rear Admiral")
        )
        self.assertIn("value=Rear%20Admiral", self._body())
        self.assertEqual(self._scan()["m1"].value, "Rear Admiral")

    def test_update_field_only_preserves_value_encoding(self) -> None:
        svc.update_mutation(self.scene_id, "m2", UpdateMutationRequest(field="rank"))
        # Field changed but the pre-encoded value must survive verbatim.
        self.assertIn("field=rank;value=Lady%20Dame", self._body())
        self.assertEqual(self._scan()["m2"].value, "Lady Dame")

    def test_update_missing_marker_is_404(self) -> None:
        with self.assertRaises(Exception) as ctx:
            svc.update_mutation(self.scene_id, "nope", UpdateMutationRequest(value="x"))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    # --- delete -----------------------------------------------------------

    def test_delete_removes_only_the_marker(self) -> None:
        svc.delete_mutation(self.scene_id, "m2")
        body = self._body()
        self.assertNotIn("id=m2", body)
        self.assertIn("The crew saluted.", body)  # surrounding prose survives
        self.assertEqual(set(self._scan()), {"m1"})

    def test_delete_missing_marker_is_404(self) -> None:
        with self.assertRaises(Exception) as ctx:
            svc.delete_mutation(self.scene_id, "nope")
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)


if __name__ == "__main__":
    unittest.main()
