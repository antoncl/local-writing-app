"""Mutation-unit carrier markers (#69, ADR-0016) — now read only through the
ADR-0095 conversion: a carrier's rows become one `mutation_set` with one row
each, its head (entity, optional name, unit id) becomes the anchor and the
set's title. `save_scenes_with_mutations` (`mutation_helpers.py`) moves each
fixture's legacy body into a set + anchor before every assertion here — these
tests are exactly the semantics ADR-0095's migration must preserve: a unit
close ends every row, a row close ends only that row, the standalone
unit-id/row-id equivalence, a legacy `group=` close ending every member (now
several independent sets), `live_mutations` after a unit close, `exclude`,
the effective route's `exclude` param, and the index version tracking the
unit's name (now the set's title).

The retired scene-rewriting route (`PUT
/api/scenes/{sid}/mutations/units/{uid}`) and its `rewrite_mutation_unit`
service method are gone (ADR-0095 §8: editing a change saves the set, never
the scene) — `UnitRewriteTests` went with them. The raw carrier grammar
itself (parsing, malformed rows) is `legacy_mutation_markers.py`'s concern now
and is covered by `test_legacy_mutation_markers.py`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from mutation_helpers import save_scenes_with_mutations, scan_scene_mutations
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService


def _setup_honor(service: ProjectService) -> str:
    """Define `rank` (text) + `titles` (multi_select — a free-text collection
    field, standing in for the retired `tags` type, ADR-0082 slice 2b) on
    characters and create Honor."""
    layers = service.read_metadata_schema_layers()
    layer_id = layers.layers[-1].id
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layer_id,
            field_id="rank",
            field=MetadataFieldDefinition(name="Rank", type="text"),
            entry_type="lore:character",
        )
    )
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layer_id,
            field_id="titles",
            field=MetadataFieldDefinition(name="Titles", type="multi_select"),
            entry_type="lore:character",
        )
    )
    return service.create_lore_entry(
        CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
    ).id


class MutationUnitTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Mutation Unit Tests")
        self.honor = _setup_honor(self.service)
        self.client = TestClient(app)
        created = self.client.post("/api/scenes", json={"title": "Chapter One"})
        self.assertEqual(created.status_code, 200, created.text)
        self.scene_id = created.json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _save_body(self, body: str, scene_id: str | None = None) -> dict[str, tuple[str, str]]:
        """Move `body` (legacy carrier/single-line grammar) into a set +
        anchor (ADR-0095) and save it. Returns `legacy id -> (set_id,
        anchor_id)` for tests that need to name a specific converted record."""
        sid = scene_id or self.scene_id
        return save_scenes_with_mutations(self.service, {sid: body})

    def _carrier(self, name: str = "Promotion") -> str:
        return (
            f"<!-- mutate:entity={self.honor};name={name};id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=title;value=Lady%20Dame;id=r2\n"
            "-->"
        )

    def _scan(self) -> dict[str, object]:
        # Keyed by row_id (ADR-0095 §3): the converter keeps a first-occurrence
        # legacy id as both the anchor id and the row id, so every existing
        # `markers["r1"]`-style lookup below still resolves.
        scene = self.service.read_scene(self.scene_id)
        return {m.row_id: m for m in scan_scene_mutations(self.service, scene)}

    def _body(self) -> str:
        return self.service.read_scene(self.scene_id).body


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
            self.assertEqual(markers[row_id].unit_name, "Promotion")
            self.assertEqual(markers[row_id].entity_id, self.honor)
        self.assertEqual(markers["r1"].unit_id, markers["r2"].unit_id)
        # The carrier collapses into ONE anchor line (ADR-0095 §1): every row
        # now shares not just the offset but the line too — the multi-line
        # carrier's per-row line order is gone with the retired grammar.
        self.assertEqual(markers["r1"].offset, markers["r2"].offset)
        self.assertEqual(markers["r1"].line, markers["r2"].line)

    def test_standalone_marker_is_its_own_unit(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Ensign;id=m1 -->"
        )
        marker = self._scan()["m1"]
        # A standalone marker's unit id IS its own row id (ADR-0095 §3).
        self.assertEqual(marker.unit_id, marker.row_id)
        self.assertEqual(marker.unit_name, "")

    def test_legacy_group_becomes_separate_sets(self) -> None:
        # ADR-0095 §12 step 4: merging `group=` members into one set would
        # move rows to a single position and change resolution — each member
        # keeps its own anchor and set, tied only by close-expansion (proved
        # in CarrierResolutionTests.test_close_by_legacy_group_ends_all_members).
        ids = self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;name=Promo;group=g1;id=m1 -->"
            f"<!-- mutate:entity={self.honor};field=title;value=Dame;name=Promo;group=g1;id=m2 -->"
        )
        markers = self._scan()
        self.assertNotEqual(markers["m1"].anchor_id, markers["m2"].anchor_id)
        self.assertNotEqual(ids["m1"][0], ids["m2"][0])  # different sets too
        self.assertEqual(markers["m1"].unit_name, "Promo")
        self.assertEqual(markers["m2"].unit_name, "Promo")

    def test_carrier_and_single_line_merge_in_prose_order(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Ensign;id=m0 --> "
            f"Later. {self._carrier()}"
        )
        scene = self.service.read_scene(self.scene_id)
        ids = [m.row_id for m in scan_scene_mutations(self.service, scene)]
        self.assertEqual(ids, ["m0", "r1", "r2"])

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

    # DROPPED: test_carrier_with_malformed_row_is_ignored_entirely. That
    # proved the raw carrier regex leaves a malformed carrier untouched —
    # a grammar/parse claim about `legacy_mutation_markers.py`
    # (`_parse_carrier_rows`), which `test_legacy_mutation_markers.py` now
    # owns. The anchor+set index never reads carrier text at all, converted
    # or not, so it has nothing distinctive to prove about a malformed one.


class CarrierResolutionTests(MutationUnitTestBase):
    def test_all_rows_of_a_unit_resolve(self) -> None:
        self._save_body(f"Honor rose. {self._carrier()}")
        state = self.service.effective_state(self.honor, self.scene_id)
        self.assertEqual(state, {"rank": "Captain", "title": "Lady Dame"})

    def test_rows_are_position_granular_together(self) -> None:
        self._save_body(f"Before. {self._carrier()} After.")
        index = self.service.build_mutations_index()
        offset = index.by_entity[self.honor][0].offset
        self.assertEqual(
            self.service.effective_state(self.honor, self.scene_id, position=offset - 1, index=index),
            {},
        )
        self.assertEqual(
            self.service.effective_state(self.honor, self.scene_id, position=offset, index=index),
            {"rank": "Captain", "title": "Lady Dame"},
        )

    def test_close_by_unit_id_ends_every_row(self) -> None:
        self._save_body(
            f"{self._carrier()} Mid. <!-- mutate:close;ref=u1;id=c1 --> End."
        )
        index = self.service.build_mutations_index()
        close_offset = self._body().index("<!-- mutate:close")
        live_before = self.service.effective_state(
            self.honor, self.scene_id, position=close_offset - 1, index=index
        )
        self.assertEqual(set(live_before), {"rank", "title"})
        self.assertEqual(
            self.service.effective_state(
                self.honor, self.scene_id, position=close_offset + 1, index=index
            ),
            {},
        )

    def test_close_by_row_id_ends_only_that_row(self) -> None:
        self._save_body(
            f"{self._carrier()} Mid. <!-- mutate:close;ref=r1;id=c1 --> End."
        )
        state = self.service.effective_state(self.honor, self.scene_id)
        self.assertEqual(state, {"title": "Lady Dame"})

    def test_close_by_unit_id_matches_row_id_for_standalone(self) -> None:
        # A standalone marker's unit id IS its row id — both spellings work.
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 --> "
            "Mid. <!-- mutate:close;ref=m1;id=c1 --> End."
        )
        self.assertEqual(self.service.effective_state(self.honor, self.scene_id), {})

    def test_close_by_legacy_group_ends_all_members(self) -> None:
        self._save_body(
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;group=g1;id=m1 -->"
            f"<!-- mutate:entity={self.honor};field=title;value=Dame;group=g1;id=m2 -->"
            " Mid. <!-- mutate:close;ref=g1;id=c1 --> End."
        )
        self.assertEqual(self.service.effective_state(self.honor, self.scene_id), {})

    def test_live_mutations_reflect_unit_close(self) -> None:
        ids = self._save_body(
            f"{self._carrier()} Mid. <!-- mutate:close;ref=u1;id=c1 --> End."
        )
        anchor_id = ids["u1"][1]
        close_offset = self._body().index("<!-- mutate:close")
        live = self.service.live_mutations(self.honor, self.scene_id, position=close_offset - 1)
        self.assertEqual(
            {m.marker_id for m in live.items}, {f"{anchor_id}.r1", f"{anchor_id}.r2"}
        )
        live_after = self.service.live_mutations(self.honor, self.scene_id)
        self.assertEqual(live_after.items, [])

    def test_effective_state_exclude_skips_records(self) -> None:
        # The list-edit baseline (#71, ADR-0017): re-editing a unit resolves
        # the effective value WITHOUT the unit's own rows. `exclude` now takes
        # an anchor id (every row of the anchor) or a composite `anchor.row`
        # id (one row) — ADR-0095 §3.
        ids = self._save_body(f"Honor rose. {self._carrier()}")
        anchor_id = ids["u1"][1]
        state = self.service.effective_state(self.honor, self.scene_id, exclude={anchor_id})
        self.assertEqual(state, {})
        partial = self.service.effective_state(
            self.honor, self.scene_id, exclude={f"{anchor_id}.r1"}
        )
        self.assertEqual(partial, {"title": "Lady Dame"})

    def test_effective_route_accepts_exclude_param(self) -> None:
        ids = self._save_body(f"Honor rose. {self._carrier()}")
        anchor_id = ids["u1"][1]
        response = self.client.get(
            f"/api/lore/{self.honor}/effective",
            params={"scene": self.scene_id, "exclude": f"{anchor_id}.r1,{anchor_id}.r2"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["values"], {})

    def test_index_version_tracks_unit_name(self) -> None:
        # Re-authoring the same unit id is the migration's own idempotent-rerun
        # shape (ADR-0095 §12): the derived set id is the same, so this
        # overwrites that set's title — the scene's anchor line is unchanged,
        # but the version still moves, because the set's title changed.
        self._save_body(f"Honor rose. {self._carrier('Promotion')}")
        before = self.service.build_mutations_index().version
        body_before = self._body()
        self._save_body(f"Honor rose. {self._carrier('Coronation')}")
        self.assertEqual(self._body(), body_before)
        self.assertNotEqual(before, self.service.build_mutations_index().version)


class CarrierValidationTests(MutationUnitTestBase):
    def test_carrier_rows_validate_like_markers(self) -> None:
        # `remove` on a text field is invalid — the per-row validator must see
        # a converted carrier's rows exactly as it sees a single-line marker's.
        self._save_body(
            f"<!-- mutate:entity={self.honor};id=u1\n"
            "field=rank;op=remove;value=Captain;id=r1\n"
            "field=titles;op=add;value=Steadholder;id=r2\n"
            "-->"
        )
        report = self.service.validate_project()
        joined = " ".join(report.warnings)
        self.assertIn("op remove is only valid on collection fields", joined)
        self.assertNotIn("r2", joined)


if __name__ == "__main__":
    unittest.main()
