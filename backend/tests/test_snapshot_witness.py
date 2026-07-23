"""What a snapshot's witness records (ADR-0043, #439 slice 3).

The capture half. `docs/design/snapshots-and-the-witness.md` §1 is the
definition; each test here names one clause of it.

These are claim-level, not shape-level. Slice 2 shipped with three
provenance-blind oracles — inverting every warm/cool class, which reverses the
feature's central claim, passed 22 of 22 tests — so an assertion here names the
entity, the field and the value rather than counting rows.
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
    SaveLoreEntryRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.snapshot_witness import (
    MAX_WITNESS_ENTITIES,
    SOURCE_DYNAMIC,
    SOURCE_ENTITY_REF,
    SOURCE_MUTATION,
)
from app.services.project_service import ProjectService


def _define_field(
    service: ProjectService, field_id: str, field: MetadataFieldDefinition, entry_type: str
) -> None:
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=field,
            entry_type=entry_type,
        )
    )


class WitnessTestCase(unittest.TestCase):
    """A world with two characters, a scene that references one of them
    explicitly, and a field a marker can mutate."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # `.resolve()` because Windows hands back the 8.3 short form and the
        # layer walk canonicalises (#356).
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Witness Tests")
        self.client = TestClient(app)

        _define_field(
            self.service,
            "eye_colour",
            MetadataFieldDefinition(name="Eye colour", type="text"),
            "lore:character",
        )
        _define_field(
            self.service,
            "cast",
            MetadataFieldDefinition(name="Cast", type="entity_ref_list"),
            "scene:scene",
        )

        self.tom = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Tom", entry_type="lore:character")
        ).id
        self.chicago = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Chicago", entry_type="lore:character")
        ).id
        self._set_lore_field(self.tom, "eye_colour", "green")

        scene = self.client.post("/api/scenes", json={"title": "The Tide"})
        self.assertEqual(scene.status_code, 200, scene.text)
        self.scene_id = scene.json()["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ----- helpers ----------------------------------------------------------

    def _set_lore_field(self, entity_id: str, field_id: str, value: object) -> None:
        entry = self.service.read_lore_entry(entity_id)
        metadata = dict(entry.metadata)
        metadata[field_id] = value
        self._save_lore(entity_id, entry.title, entry.body, metadata)

    def _save_lore(
        self, entity_id: str, title: str, body: str, metadata: dict | None = None
    ) -> None:
        entry = self.service.read_lore_entry(entity_id)
        self.service.save_lore_entry(
            entity_id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                entry_type=entry.entry_type,
                metadata=entry.metadata if metadata is None else metadata,
            ),
        )

    def _save_scene(self, body: str = "", cast: list[str] | None = None) -> None:
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title="The Tide",
                body=body,
                status="draft",
                entry_type="scene:scene",
                metadata={"cast": cast} if cast is not None else {},
            ),
        )

    def _witness_for(self, entity_id: str, dynamic: list[str] | None = None):
        witness = self.service.build_witness(self.scene_id, dynamic)
        for entity in witness.entities:
            if entity.id == entity_id:
                return entity
        return None


class WitnessSourcesTests(WitnessTestCase):
    """§1: three sources, unioned — mutations, `entity_ref`s, dynamic context."""

    def test_an_entity_ref_puts_the_entity_in_the_witness(self) -> None:
        self._save_scene(cast=[self.tom])
        entity = self._witness_for(self.tom)
        self.assertIsNotNone(entity)
        self.assertIn(SOURCE_ENTITY_REF, entity.sources)

    def test_the_dynamic_set_puts_the_entity_in_the_witness(self) -> None:
        """The frontend owns the matcher, so the ids the author sees underlined
        are the ids that reach the backend. Nothing here rescans prose."""
        self._save_scene()
        entity = self._witness_for(self.chicago, dynamic=[self.chicago])
        self.assertIsNotNone(entity)
        self.assertEqual(entity.sources, [SOURCE_DYNAMIC])

    def test_a_mutation_in_this_scene_puts_the_entity_in_the_witness(self) -> None:
        self._save_scene(
            f"Tom blinked. <!-- mutate:entity={self.tom};field=eye_colour;value=blue;id=m1 -->"
        )
        entity = self._witness_for(self.tom)
        self.assertIsNotNone(entity)
        self.assertIn(SOURCE_MUTATION, entity.sources)

    def test_an_interval_opened_in_an_earlier_scene_still_witnesses_here(self) -> None:
        """The clause that refutes "markers in this scene's body".

        ADR-0043's own motivating example: a scene inside an open interval
        carries no markers at all, yet what the world *is* there is decided
        entirely by its neighbours. A body-markers witness would be empty, and
        the first entry in the ADR's test surface could not pass.
        """
        opener = self.client.post("/api/scenes", json={"title": "Before"}).json()["id"]
        # Manuscript *order* is what makes an interval live here, and a new
        # scene lands last — so the opener has to be moved ahead of this one.
        structure = self.service.read_structure()
        opener_node = next(n for n in structure.root.children if n.scene_id == opener)
        self.service.move_structure_node(opener_node.id, structure.root.id, 0)
        self.service.save_scene(
            opener,
            SaveSceneRequest(
                title="Before",
                body=f"<!-- mutate:entity={self.tom};field=eye_colour;value=blue;id=m1 -->",
                status="draft",
                entry_type="scene:scene",
            ),
        )
        self._save_scene("Tom said nothing at all.")

        entity = self._witness_for(self.tom)
        self.assertIsNotNone(entity, "a scene inside an open interval must witness the entity")
        self.assertEqual(entity.sources, [SOURCE_MUTATION])
        self.assertEqual(entity.state["eye_colour"], "blue")
        self.assertEqual(entity.overrides, ["eye_colour"])

    def test_an_unreferenced_entity_is_not_witnessed(self) -> None:
        """Absence is not manufactured. Chicago exists, but nothing in this
        scene depends on it."""
        self._save_scene(cast=[self.tom])
        self.assertIsNone(self._witness_for(self.chicago))

    def test_an_id_that_resolves_to_nothing_is_dropped(self) -> None:
        """A stale id in the dynamic set is not recorded as an absent entity —
        an entity that never participated must not become a report row."""
        self._save_scene()
        witness = self.service.build_witness(self.scene_id, ["lore_does_not_exist"])
        self.assertEqual(witness.entities, [])


class WitnessContentTests(WitnessTestCase):
    """What one entity's record carries — the raw material for the report."""

    def test_the_state_is_the_resolved_view_not_the_stored_one(self) -> None:
        """Base values with the live overrides applied. A report naming only the
        stored value would be wrong inside an interval; one naming only the
        override would be empty outside."""
        self._save_scene(
            f"Tom blinked. <!-- mutate:entity={self.tom};field=eye_colour;value=blue;id=m1 -->",
            cast=[self.tom],
        )
        entity = self._witness_for(self.tom)
        self.assertEqual(entity.state["eye_colour"], "blue")
        self.assertEqual(entity.state["title"], "Tom")
        self.assertEqual(entity.overrides, ["eye_colour"])

    def test_the_field_label_travels_with_the_witness(self) -> None:
        """So the report speaks the author's vocabulary even about a field the
        schema has since dropped — which is exactly what axis 3 fires on."""
        self._save_scene(cast=[self.tom])
        entity = self._witness_for(self.tom)
        self.assertEqual(entity.field_types["eye_colour"].label, "Eye colour")
        self.assertEqual(entity.field_types["eye_colour"].type, "text")

    def test_the_resolved_source_layer_is_recorded(self) -> None:
        """Axis 5. Scope visibility is a property of the resolved index, not of
        any file, so no hash over bytes can see it — including the composite
        `revision` #314 introduces."""
        self._save_scene(cast=[self.tom])
        entity = self._witness_for(self.tom)
        self.assertTrue(entity.source_layer_id)

    def test_the_body_is_never_recorded(self) -> None:
        """Unbounded, and a body edit still reports at the floor through
        `revision`. The witness stores what a report can name."""
        self._save_lore(self.tom, "Tom", "A very long life story.")
        self._save_scene(cast=[self.tom])
        self.assertNotIn("body", self._witness_for(self.tom).state)

    def test_the_revision_is_recorded_as_an_opaque_token(self) -> None:
        self._save_scene(cast=[self.tom])
        first = self._witness_for(self.tom).revision
        self.assertTrue(first)
        self._set_lore_field(self.tom, "eye_colour", "blue")
        self.assertNotEqual(self._witness_for(self.tom).revision, first)


class WitnessSourceProvenanceTests(WitnessTestCase):
    """`sources_recorded` — the seam that stops a two-source capture from
    reporting every implicitly-detected entity as removed."""

    def test_an_unobserved_dynamic_set_is_not_an_empty_one(self) -> None:
        self._save_scene()
        not_observed = self.service.build_witness(self.scene_id)
        observed_empty = self.service.build_witness(self.scene_id, [])
        self.assertNotIn(SOURCE_DYNAMIC, not_observed.sources_recorded)
        self.assertIn(SOURCE_DYNAMIC, observed_empty.sources_recorded)


class WitnessCostBoundTests(WitnessTestCase):
    """#409: an unbounded cost on the synchronous route is a hung pane with
    nothing on screen explaining why. The bound must *fire*, not merely exist."""

    def test_the_entity_cap_fires_and_says_so(self) -> None:
        cast = [
            self.service.create_lore_entry(
                CreateLoreEntryRequest(title=f"Extra {n}", entry_type="lore:character")
            ).id
            for n in range(MAX_WITNESS_ENTITIES + 5)
        ]
        self._save_scene(cast=cast)
        witness = self.service.build_witness(self.scene_id, [])
        self.assertEqual(len(witness.entities), MAX_WITNESS_ENTITIES)
        self.assertTrue(
            witness.truncated,
            "a silently truncated witness reads as 'nothing else changed', "
            "which is the one claim it cannot make",
        )

    def test_a_witness_under_the_cap_is_not_marked_truncated(self) -> None:
        """The control. Without it the cap test passes with `truncated = True`
        hard-coded — a guard asserted in a place it can never fail."""
        self._save_scene(cast=[self.tom])
        self.assertFalse(self.service.build_witness(self.scene_id, []).truncated)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
