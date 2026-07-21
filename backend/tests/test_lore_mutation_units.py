"""Mutation-unit carrier markers (#69, ADR-0016).

One authored change touching N fields is ONE multi-line carrier comment — a
head (entity, optional name, unit id) plus one `field=` row per line. Rows stay
independent records with their own ids and lifetimes; `unit_id`/`unit_name` tie
them for presentation. `close;ref=<unit-id>` expands at index time into per-row
closes. The single-line marker is the degenerate one-row form.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpdateMutationRequest,
    UpsertMetadataFieldRequest,
)
from app.runtime import service as svc


def _setup_honor() -> str:
    """Define `rank` (text) + `titles` (tags) on characters and create Honor."""
    layers = svc.read_metadata_schema_layers()
    layer_id = layers.layers[-1].id
    svc.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layer_id,
            field_id="rank",
            field=MetadataFieldDefinition(name="Rank", type="text"),
            entry_type="lore:character",
        )
    )
    svc.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layer_id,
            field_id="titles",
            field=MetadataFieldDefinition(name="Titles", type="tags"),
            entry_type="lore:character",
        )
    )
    return svc.create_lore_entry(
        CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
    ).id


class MutationUnitTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        svc.__init__()
        svc.create_project(self.root, "Mutation Unit Tests")
        self.honor = _setup_honor()
        self.client = TestClient(app)
        created = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.assertEqual(created.status_code, 200, created.text)
        self.scene_id = created.json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _save_body(self, body: str, scene_id: str | None = None) -> None:
        sid = scene_id or self.scene_id
        response = self.client.put(
            f"/api/scenes/{sid}", json={"title": "Scene", "body": body}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _carrier(self, name: str = "Promotion") -> str:
        return (
            f"<!-- mutate:entity={self.honor};name={name};id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=title;value=Lady%20Dame;id=r2\n"
            "-->"
        )

    def _scan(self) -> dict[str, object]:
        scene = svc.read_scene(self.scene_id)
        return {m.marker_id: m for m in svc._scan_scene_mutations(scene)}

    def _body(self) -> str:
        return svc.read_scene(self.scene_id).body


class CarrierScanTests(MutationUnitTestBase):
    def test_carrier_yields_one_record_per_row(self) -> None:
        self._save_body(f"Honor rose. {self._carrier()} The fleet cheered.")
        markers = self._scan()
        self.assertEqual(set(markers), {"r1", "r2"})
        self.assertEqual(markers["r1"].field, "rank")
        self.assertEqual(markers["r1"].value, "Captain")
        self.assertEqual(markers["r2"].field, "title")
        self.assertEqual(markers["r2"].value, "Lady Dame")  # url-decoded

    def test_carrier_rows_share_unit_id_name_and_offset(self) -> None:
        self._save_body(f"Honor rose. {self._carrier()}")
        markers = self._scan()
        for row_id in ("r1", "r2"):
            self.assertEqual(markers[row_id].unit_id, "u1")
            self.assertEqual(markers[row_id].unit_name, "Promotion")
            self.assertEqual(markers[row_id].entity_id, self.honor)
        self.assertEqual(markers["r1"].offset, markers["r2"].offset)
        self.assertLess(markers["r1"].line, markers["r2"].line)

    def test_standalone_marker_is_its_own_unit(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Ensign;id=m1 -->"
        )
        marker = self._scan()["m1"]
        self.assertEqual(marker.unit_id, "m1")
        self.assertEqual(marker.unit_name, "")

    def test_legacy_group_maps_to_unit(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;name=Promo;group=g1;id=m1 -->"
            f"<!-- mutate:entity={self.honor};field=title;value=Dame;name=Promo;group=g1;id=m2 -->"
        )
        markers = self._scan()
        self.assertEqual(markers["m1"].unit_id, "g1")
        self.assertEqual(markers["m2"].unit_id, "g1")
        self.assertEqual(markers["m1"].unit_name, "Promo")

    def test_carrier_and_single_line_merge_in_prose_order(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Ensign;id=m0 --> "
            f"Later. {self._carrier()}"
        )
        scene = svc.read_scene(self.scene_id)
        ids = [m.marker_id for m in svc._scan_scene_mutations(scene)]
        self.assertEqual(ids, ["m0", "r1", "r2"])

    def test_carrier_with_malformed_row_is_ignored_entirely(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};name=Promo;id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=broken row without ids\n"
            "-->"
        )
        self.assertEqual(self._scan(), {})

    def test_carrier_row_with_op_parses(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};id=u1\n"
            "field=titles;op=add;value=Steadholder;id=r1\n"
            "field=titles;op=remove;value=Ensign;id=r2\n"
            "-->"
        )
        markers = self._scan()
        self.assertEqual(markers["r1"].op, "add")
        self.assertEqual(markers["r2"].op, "remove")
        self.assertEqual(markers["r1"].unit_name, "")


class CarrierResolutionTests(MutationUnitTestBase):
    def test_all_rows_of_a_unit_resolve(self) -> None:
        self._save_body(f"Honor rose. {self._carrier()}")
        state = svc.effective_state(self.honor, self.scene_id)
        self.assertEqual(state, {"rank": "Captain", "title": "Lady Dame"})

    def test_rows_are_position_granular_together(self) -> None:
        self._save_body(f"Before. {self._carrier()} After.")
        index = svc.build_mutations_index()
        offset = index.by_entity[self.honor][0].offset
        self.assertEqual(
            svc.effective_state(self.honor, self.scene_id, position=offset - 1, index=index),
            {},
        )
        self.assertEqual(
            svc.effective_state(self.honor, self.scene_id, position=offset, index=index),
            {"rank": "Captain", "title": "Lady Dame"},
        )

    def test_close_by_unit_id_ends_every_row(self) -> None:
        self._save_body(
            f"{self._carrier()} Mid. <!-- mutate:close;ref=u1;id=c1 --> End."
        )
        index = svc.build_mutations_index()
        close_offset = self._body().index("<!-- mutate:close")
        live_before = svc.effective_state(
            self.honor, self.scene_id, position=close_offset - 1, index=index
        )
        self.assertEqual(set(live_before), {"rank", "title"})
        self.assertEqual(
            svc.effective_state(
                self.honor, self.scene_id, position=close_offset + 1, index=index
            ),
            {},
        )

    def test_close_by_row_id_ends_only_that_row(self) -> None:
        self._save_body(
            f"{self._carrier()} Mid. <!-- mutate:close;ref=r1;id=c1 --> End."
        )
        state = svc.effective_state(self.honor, self.scene_id)
        self.assertEqual(state, {"title": "Lady Dame"})

    def test_close_by_unit_id_matches_row_id_for_standalone(self) -> None:
        # A standalone marker's unit id IS its marker id — both spellings work.
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 --> "
            "Mid. <!-- mutate:close;ref=m1;id=c1 --> End."
        )
        self.assertEqual(svc.effective_state(self.honor, self.scene_id), {})

    def test_close_by_legacy_group_ends_all_members(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;group=g1;id=m1 -->"
            f"<!-- mutate:entity={self.honor};field=title;value=Dame;group=g1;id=m2 -->"
            " Mid. <!-- mutate:close;ref=g1;id=c1 --> End."
        )
        self.assertEqual(svc.effective_state(self.honor, self.scene_id), {})

    def test_live_mutations_reflect_unit_close(self) -> None:
        self._save_body(
            f"{self._carrier()} Mid. <!-- mutate:close;ref=u1;id=c1 --> End."
        )
        close_offset = self._body().index("<!-- mutate:close")
        live = svc.live_mutations(self.honor, self.scene_id, position=close_offset - 1)
        self.assertEqual({m.marker_id for m in live.items}, {"r1", "r2"})
        live_after = svc.live_mutations(self.honor, self.scene_id)
        self.assertEqual(live_after.items, [])

    def test_effective_state_exclude_skips_records(self) -> None:
        # The list-edit baseline (#71, ADR-0017): re-editing a unit resolves the
        # effective value WITHOUT the unit's own rows.
        self._save_body(f"Honor rose. {self._carrier()}")
        state = svc.effective_state(
            self.honor, self.scene_id, exclude={"r1", "r2"}
        )
        self.assertEqual(state, {})
        partial = svc.effective_state(self.honor, self.scene_id, exclude={"r1"})
        self.assertEqual(partial, {"title": "Lady Dame"})

    def test_effective_route_accepts_exclude_param(self) -> None:
        self._save_body(f"Honor rose. {self._carrier()}")
        response = self.client.get(
            f"/api/lore/{self.honor}/effective",
            params={"scene": self.scene_id, "exclude": "r1,r2"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["values"], {})

    def test_index_version_tracks_unit_name(self) -> None:
        self._save_body(f"Honor rose. {self._carrier('Promotion')}")
        before = svc.build_mutations_index().version
        self._save_body(f"Honor rose. {self._carrier('Coronation')}")
        self.assertNotEqual(before, svc.build_mutations_index().version)


class CarrierRewriteTests(MutationUnitTestBase):
    def setUp(self) -> None:
        super().setUp()
        self._save_body(f"Honor rose. {self._carrier()} The fleet cheered.")

    def test_update_row_rewrites_only_that_row(self) -> None:
        svc.update_mutation(self.scene_id, "r1", UpdateMutationRequest(value="Commodore"))
        markers = self._scan()
        self.assertEqual(markers["r1"].value, "Commodore")
        self.assertEqual(markers["r2"].value, "Lady Dame")
        # Untouched row keeps its encoded value verbatim; carrier stays multi-line.
        body = self._body()
        self.assertIn("field=title;value=Lady%20Dame;id=r2", body)
        self.assertIn(f"<!-- mutate:entity={self.honor};name=Promotion;id=u1\n", body)

    def test_update_row_name_renames_the_unit_head(self) -> None:
        svc.update_mutation(self.scene_id, "r1", UpdateMutationRequest(name="Coronation"))
        markers = self._scan()
        self.assertEqual(markers["r1"].unit_name, "Coronation")
        self.assertEqual(markers["r2"].unit_name, "Coronation")
        self.assertIn(";name=Coronation;", self._body())

    def test_update_missing_row_is_404(self) -> None:
        with self.assertRaises(Exception) as ctx:
            svc.update_mutation(self.scene_id, "nope", UpdateMutationRequest(value="x"))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    def test_delete_row_keeps_carrier_when_rows_remain(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=title;value=Dame;id=r2\n"
            "field=titles;op=add;value=Steadholder;id=r3\n"
            "-->"
        )
        svc.delete_mutation(self.scene_id, "r2")
        markers = self._scan()
        self.assertEqual(set(markers), {"r1", "r3"})
        self.assertIn("id=u1\n", self._body())  # still a carrier

    def test_delete_row_degenerates_two_row_carrier_to_single_line(self) -> None:
        svc.delete_mutation(self.scene_id, "r2")
        body = self._body()
        self.assertNotIn("\n", body[body.index("<!-- mutate:") : body.index("-->")])
        marker = self._scan()["r1"]
        self.assertEqual(marker.value, "Captain")
        # Head folds into the sole row: unit id drops, name travels as name=.
        self.assertEqual(marker.unit_id, "r1")
        self.assertEqual(marker.unit_name, "Promotion")
        self.assertIn("The fleet cheered.", body)

    def test_delete_by_unit_head_id_drops_whole_carrier(self) -> None:
        svc.delete_mutation(self.scene_id, "u1")
        self.assertEqual(self._scan(), {})
        body = self._body()
        self.assertIn("Honor rose.", body)
        self.assertIn("The fleet cheered.", body)
        self.assertNotIn("mutate:", body)

    def test_single_line_markers_still_update(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Ensign;id=m1 -->"
        )
        svc.update_mutation(self.scene_id, "m1", UpdateMutationRequest(value="Admiral"))
        self.assertEqual(self._scan()["m1"].value, "Admiral")


class CarrierValidationTests(MutationUnitTestBase):
    def test_carrier_rows_validate_like_markers(self) -> None:
        # `remove` on a text field is invalid — the per-row validator must see
        # carrier rows exactly as it sees single-line markers.
        self._save_body(
            f"<!-- mutate:entity={self.honor};id=u1\n"
            "field=rank;op=remove;value=Captain;id=r1\n"
            "field=titles;op=add;value=Steadholder;id=r2\n"
            "-->"
        )
        report = svc.validate_project()
        joined = " ".join(report.warnings)
        self.assertIn("op remove is only valid on collection fields", joined)
        self.assertNotIn("r2", joined)


if __name__ == "__main__":
    unittest.main()
