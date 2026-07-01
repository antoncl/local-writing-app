"""Acceptance tests for mutation resolution in the AI context path (#52, #33).

Proves the #33 story end-to-end at the context-assembly layer: a lore field that
mutates mid-manuscript resolves to its **effective value at the calling scene**.
Two surfaces:

- `_format_lore_block` (the single field-value choke-point, ADR-0006): the auto
  `<lore>` block renders the effective name/body at the calling scene.
- the `base()` / `effective()` Jinja helpers: the field-query surface that
  carries structured fields (like `rank`) the block does not render.
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
from app.services.ai.helpers import _format_lore_block, create_environment_for_project


class MutationResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Mutation Resolution Tests")
        # `rank` is a user-defined field on characters; define it so the rank
        # mutation validates (#53).
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

        honor = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Commodore Honor", entry_type="character")
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
        block = _format_lore_block(svc, [self.honor], scene=self.s1)
        self.assertIn('name="Commodore Honor"', block)

    def test_block_at_and_after_change_shows_effective_name(self) -> None:
        block = _format_lore_block(svc, [self.honor], scene=self.s2)
        self.assertIn('name="Captain Honor"', block)

    def test_block_without_scene_is_base_only(self) -> None:
        block = _format_lore_block(svc, [self.honor])
        self.assertIn('name="Commodore Honor"', block)

    # --- base()/effective() helpers (structured field: rank) --------------

    def test_effective_helper_resolves_field_per_scene(self) -> None:
        env = create_environment_for_project(svc)
        render = env.from_string(
            "{{ effective(hid, 'rank', sid) }}"
        ).render
        self.assertEqual(render(hid=self.honor, sid=self.s2), "Captain")
        # Redaction: the future "Captain" must not leak into the earlier scene
        # (base rank is unset here, so it resolves to the base, not the mutation).
        self.assertNotEqual(render(hid=self.honor, sid=self.s1), "Captain")

    def test_effective_helper_resolves_title_per_scene(self) -> None:
        env = create_environment_for_project(svc)
        render = env.from_string("{{ effective(hid, 'title', sid) }}").render
        self.assertEqual(render(hid=self.honor, sid=self.s1), "Commodore Honor")
        self.assertEqual(render(hid=self.honor, sid=self.s2), "Captain Honor")

    def test_base_helper_ignores_mutations(self) -> None:
        env = create_environment_for_project(svc)
        render = env.from_string("{{ base(hid, 'title') }}").render
        # base() is scene-independent: always the stored (book-start) value.
        self.assertEqual(render(hid=self.honor), "Commodore Honor")

    def test_effective_coerces_to_field_native_type(self) -> None:
        # A number field resolves to an int, not the marker's "600" string, so
        # template comparisons behave the same as with a base value.
        layers = svc.read_metadata_schema_layers()
        svc.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="strength",
                field=MetadataFieldDefinition(name="Strength", type="number"),
                entry_type="character",
            )
        )
        scene = self._new_scene(
            "Scene Three",
            f"Grew stronger. <!-- mutate:entity={self.honor};field=strength;value=600;id=s1 -->",
        )
        env = create_environment_for_project(svc)
        value = env.globals["effective"](self.honor, "strength", scene)
        self.assertEqual(value, 600)
        self.assertIsInstance(value, int)


if __name__ == "__main__":
    unittest.main()
