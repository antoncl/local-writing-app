"""Acceptance tests for mutation resolution in the AI context path (#52, #33).

Proves the #33 story end-to-end at the context-assembly layer: a lore field that
mutates mid-manuscript resolves to its **effective value at the calling scene**.
Two surfaces:

- `_format_lore_block` (the single field-value choke-point, ADR-0006): the auto
  `<lore>` block renders the effective name/body at the calling scene.
- the `original(x)` / `entry(x, at=…)` field reads (ADR-0060 §3): the field-query
  surface that carries structured fields (like `rank`) the block does not render.
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
    UpsertMetadataFieldRequest,
)
from app.services.ai.helpers import (
    _coerce_entry_ref_as_of,
    _format_lore_block,
    create_environment_for_project,
)


class MutationResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Mutation Resolution Tests")
        # `rank` is a user-defined field on characters; define it so the rank
        # mutation validates (#53).
        layers = self.service.read_metadata_schema_layers()
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="rank",
                field=MetadataFieldDefinition(name="Rank", type="text"),
                entry_type="lore:character",
            )
        )
        self.client = TestClient(app)

        honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Commodore Honor", entry_type="lore:character")
        )
        self.honor = honor.id

        # s1 precedes the change; s2 promotes Honor (title + rank), mid-scene.
        self.s1 = self._new_scene("Scene One", "Honor commands the fleet.")
        self.s2 = self._new_scene(
            "Scene Two",
            "She took the ship. "
            f"<!-- mutate:entity={self.honor};field=title;value=Captain%20Honor;id=t1 -->"
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=r1 -->",
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

    # --- <lore> block auto-resolution (the choke-point) -------------------

    def test_block_before_change_shows_base_name(self) -> None:
        block = _format_lore_block(self.service, [self.honor], scene=self.s1)
        self.assertIn('name="Commodore Honor"', block)

    def test_block_at_and_after_change_shows_effective_name(self) -> None:
        block = _format_lore_block(self.service, [self.honor], scene=self.s2)
        self.assertIn('name="Captain Honor"', block)

    def test_block_without_scene_is_base_only(self) -> None:
        block = _format_lore_block(self.service, [self.honor])
        self.assertIn('name="Commodore Honor"', block)

    # --- original()/entry(at=) field reads (structured field: rank) --------

    def test_entry_at_resolves_field_per_scene(self) -> None:
        env = create_environment_for_project(self.service)
        render = env.from_string("{{ entry(hid, at=sid).rank }}").render
        self.assertEqual(render(hid=self.honor, sid=self.s2), "Captain")
        # Redaction: the future "Captain" must not leak into the earlier scene
        # (book-start rank is unset here, so it resolves to book-start, not the
        # mutation).
        self.assertNotEqual(render(hid=self.honor, sid=self.s1), "Captain")

    def test_entry_at_resolves_title_per_scene(self) -> None:
        env = create_environment_for_project(self.service)
        render = env.from_string("{{ entry(hid, at=sid).title }}").render
        self.assertEqual(render(hid=self.honor, sid=self.s1), "Commodore Honor")
        self.assertEqual(render(hid=self.honor, sid=self.s2), "Captain Honor")

    def test_original_ignores_mutations(self) -> None:
        env = create_environment_for_project(self.service)
        render = env.from_string("{{ original(hid).title }}").render
        # original() is scene-independent: always the stored (book-start) value.
        self.assertEqual(render(hid=self.honor), "Commodore Honor")

    def test_entry_at_coerces_to_field_native_type(self) -> None:
        # A number field resolves to an int, not the marker's "600" string, so
        # template comparisons behave the same as with a book-start value.
        layers = self.service.read_metadata_schema_layers()
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="strength",
                field=MetadataFieldDefinition(name="Strength", type="number"),
                entry_type="lore:character",
            )
        )
        scene = self._new_scene(
            "Scene Three",
            f"Grew stronger. <!-- mutate:entity={self.honor};field=strength;value=600;id=s1 -->",
        )
        # `entry()` is a pass_context global (needs a render context); exercise the
        # same coercion through the function it delegates to, then read the field
        # off the returned EntryRef — value must be a native int.
        schema = self.service.read_metadata_schema()
        ref = _coerce_entry_ref_as_of(self.service, schema, self.honor, scene)
        value = ref.strength
        self.assertEqual(value, 600)
        self.assertIsInstance(value, int)

    def test_entry_at_honors_within_scene_position(self) -> None:
        # ADR-0060 §3 preserves `effective()`'s within-scene cursor as
        # `entry(x, at=s, position=N)`: a mutation marker AFTER the cursor is not
        # yet live, so the same scene resolves differently on either side of it.
        # s2 already promoted rank→Captain earlier; Scene Four re-promotes it to a
        # DISTINCT value mid-scene, so the cursor discriminates which value stands.
        scene = self._new_scene(
            "Scene Four",
            f"Prologue. <!-- mutate:entity={self.honor};field=rank;value=Admiral;id=p1 -->",
        )
        idx = self.service.build_mutations_index()
        offset = next(m.offset for m in idx.by_entity[self.honor] if m.marker_id == "p1")
        schema = self.service.read_metadata_schema()
        # Cursor strictly before this scene's marker: its re-promotion is not live,
        # so rank is still Captain (s2's earlier, already-passed mutation).
        before = _coerce_entry_ref_as_of(
            self.service, schema, self.honor, scene, position=offset - 1
        )
        self.assertEqual(before.rank, "Captain")
        # Cursor at the marker (and the END_OF_SCENE default): the re-promotion wins.
        at_marker = _coerce_entry_ref_as_of(
            self.service, schema, self.honor, scene, position=offset
        )
        self.assertEqual(at_marker.rank, "Admiral")


if __name__ == "__main__":
    unittest.main()
