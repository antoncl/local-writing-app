"""Collection add/remove mutation ops + optional name/group grammar (#58, #65).

v1.0 markers are scalar replace; v1.1 adds `op=add`/`op=remove` for the three
collection field types and an optional `name=`/`group=` label. These prove:

- the grammar round-trips (scan parses op/name/group; rewrite preserves them);
- the resolver computes `(base ∪ adds) ∖ removes`, remove-wins, as a `list[str]`;
- validation gates add/remove to collection fields and item-checks the element.
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
    SaveLoreEntryRequest,
    UpdateMutationRequest,
    UpsertMetadataFieldRequest,
)


def _define_field(field_id: str, field_type: str, name: str) -> None:
    layers = svc.read_metadata_schema_layers()
    svc.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=name, type=field_type),
            entry_type="character",
        )
    )


class CollectionMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Collection Mutation Tests")
        _define_field("clues", "tags", "Clues")
        _define_field("rank", "text", "Rank")
        self.honor = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="character")
        ).id
        # Base clues = ["footprint"] so add/remove interact with a real base set.
        svc.save_lore_entry(
            self.honor,
            SaveLoreEntryRequest(
                title="Honor", body="", entry_type="character",
                metadata={"clues": ["footprint"]},
            ),
        )
        self.client = TestClient(app)
        self.s1 = self._new_scene("Scene One", "The case opens.")

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

    def _marker(self, field: str, op: str, value: str, mid: str, **extra: str) -> str:
        attrs = f"entity={self.honor};field={field};op={op};value={value}"
        for key, val in extra.items():
            attrs += f";{key}={val}"
        return f"<!-- mutate:{attrs};id={mid} -->"

    # --- grammar round-trip ----------------------------------------------

    def test_scan_parses_op_name_group(self) -> None:
        scene = self._new_scene(
            "Scene Two",
            self._marker("clues", "add", "torn%20glove", "c1", name="The%20Glove", group="g1"),
        )
        marker = next(m for m in svc._scan_scene_mutations(svc.read_scene(scene)))
        self.assertEqual(marker.op, "add")
        self.assertEqual(marker.value, "torn glove")
        self.assertEqual(marker.name, "The Glove")
        self.assertEqual(marker.group, "g1")

    def test_v1_marker_defaults_to_replace(self) -> None:
        scene = self._new_scene(
            "Scene Two",
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=r1 -->",
        )
        marker = next(m for m in svc._scan_scene_mutations(svc.read_scene(scene)))
        self.assertEqual(marker.op, "replace")
        self.assertEqual(marker.name, "")
        self.assertEqual(marker.group, "")

    def test_update_preserves_op_and_name(self) -> None:
        scene = self._new_scene(
            "Scene Two",
            self._marker("clues", "add", "torn%20glove", "c1", name="The%20Glove"),
        )
        svc.update_mutation(scene, "c1", UpdateMutationRequest(value="bloody knife"))
        body = svc.read_scene(scene).body
        self.assertIn("op=add", body)
        self.assertIn("name=The%20Glove", body)
        self.assertIn("value=bloody%20knife", body)
        marker = next(m for m in svc._scan_scene_mutations(svc.read_scene(scene)))
        self.assertEqual(marker.op, "add")
        self.assertEqual(marker.value, "bloody knife")

    # --- resolution -------------------------------------------------------

    def test_add_accumulates_onto_base(self) -> None:
        scene = self._new_scene("Scene Two", self._marker("clues", "add", "torn%20glove", "c1"))
        self.assertEqual(
            svc.effective_state(self.honor, scene),
            {"clues": ["footprint", "torn glove"]},
        )

    def test_remove_drops_a_base_value(self) -> None:
        scene = self._new_scene("Scene Two", self._marker("clues", "remove", "footprint", "c1"))
        self.assertEqual(svc.effective_state(self.honor, scene), {"clues": []})

    def test_remove_wins_over_concurrent_add(self) -> None:
        scene = self._new_scene(
            "Scene Two",
            self._marker("clues", "add", "torn%20glove", "c1")
            + self._marker("clues", "remove", "torn%20glove", "c2"),
        )
        # torn glove is both added and removed while both are live → removed.
        self.assertEqual(svc.effective_state(self.honor, scene), {"clues": ["footprint"]})

    def test_whole_replace_on_collection_coerces_to_list(self) -> None:
        # A whole-collection replace stores the comma-joined value; effective_state
        # leaves it a string (it can't classify a pure-replace field without the
        # schema), and the field-type-aware coercion boundary splits it back to a
        # list (ADR-0009).
        scene = self._new_scene(
            "Scene Two",
            f"<!-- mutate:entity={self.honor};field=clues;value=knife%2Crope;id=c1 -->",
        )
        self.assertEqual(svc.effective_state(self.honor, scene), {"clues": "knife,rope"})
        self.assertEqual(svc._coerce_mutation_value("knife,rope", "tags"), ["knife", "rope"])

    def test_earlier_scene_sees_no_collection_override(self) -> None:
        self._new_scene("Scene Two", self._marker("clues", "add", "torn%20glove", "c1"))
        self.assertEqual(svc.effective_state(self.honor, self.s1), {})

    # --- validation -------------------------------------------------------

    def test_add_on_scalar_field_is_a_warning(self) -> None:
        # Mutation validation is advisory (#53): strays surface as warnings.
        self._new_scene("Scene Two", self._marker("rank", "add", "Captain", "r1"))
        warnings = svc.validate_project().warnings
        self.assertTrue(any("only valid on collection fields" in w for w in warnings))

    def test_add_element_is_item_validated(self) -> None:
        _define_field("friends", "entity_ref_list", "Friends")
        self._new_scene("Scene Two", self._marker("friends", "add", "ghost-id", "f1"))
        warnings = svc.validate_project().warnings
        self.assertTrue(any("friends" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
