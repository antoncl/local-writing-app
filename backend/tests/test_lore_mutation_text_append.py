"""Additive (append) text mutations — `op=add` on text/long_text fields.

ADR-0009 amendment: collections resolve add/remove as set ops; text and
long_text fields (including the intrinsic title/body) accept `add` as append —
effective value = base (or latest live whole-replace) + live adds in start
order, space-joined for text, paragraph-joined for long_text. `remove` stays
collection-only (gate covered in test_lore_mutation_collections).
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
    UpsertMetadataFieldRequest,
)


class TextAppendMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Text Append Tests")
        layers = svc.read_metadata_schema_layers()
        svc.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="rank",
                field=MetadataFieldDefinition(name="Rank", type="text"),
                entry_type="character",
            )
        )
        svc.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="notes",
                field=MetadataFieldDefinition(name="Notes", type="long_text"),
                entry_type="character",
            )
        )
        self.honor = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="character")
        ).id
        svc.save_lore_entry(
            self.honor,
            SaveLoreEntryRequest(
                title="Honor", body="She is wary of strangers.", entry_type="character",
                metadata={"rank": "Sergeant", "notes": "Keeps a journal."},
            ),
        )
        self.client = TestClient(app)

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

    def _marker(self, field: str, op: str, value: str, mid: str) -> str:
        return f"<!-- mutate:entity={self.honor};field={field};op={op};value={value};id={mid} -->"

    # --- resolution ---------------------------------------------------------

    def test_text_add_appends_with_a_space(self) -> None:
        scene = self._new_scene("S2", self._marker("rank", "add", "(acting)", "a1"))
        self.assertEqual(
            svc.effective_state(self.honor, scene), {"rank": "Sergeant (acting)"}
        )

    def test_long_text_add_appends_a_paragraph(self) -> None:
        scene = self._new_scene(
            "S2", self._marker("notes", "add", "Now%20writes%20in%20cipher.", "a1")
        )
        self.assertEqual(
            svc.effective_state(self.honor, scene),
            {"notes": "Keeps a journal.\n\nNow writes in cipher."},
        )

    def test_intrinsic_body_append_uses_stored_body_as_base(self) -> None:
        scene = self._new_scene(
            "S2", self._marker("body", "add", "She%20trusts%20the%20detective.", "a1")
        )
        self.assertEqual(
            svc.effective_state(self.honor, scene),
            {"body": "She is wary of strangers.\n\nShe trusts the detective."},
        )

    def test_intrinsic_title_append_uses_stored_title_as_base(self) -> None:
        scene = self._new_scene("S2", self._marker("title", "add", "the%20Bold", "a1"))
        self.assertEqual(
            svc.effective_state(self.honor, scene), {"title": "Honor the Bold"}
        )

    def test_live_replace_resets_base_then_adds_append(self) -> None:
        # Same rule as collections: a live whole-replace resets the base; live
        # adds then append in start order.
        scene = self._new_scene(
            "S2",
            self._marker("rank", "replace", "Captain", "r1")
            + self._marker("rank", "add", "(brevet)", "a1"),
        )
        self.assertEqual(
            svc.effective_state(self.honor, scene), {"rank": "Captain (brevet)"}
        )

    def test_multiple_adds_append_in_start_order(self) -> None:
        scene = self._new_scene(
            "S2",
            self._marker("rank", "add", "(acting)", "a1")
            + self._marker("rank", "add", "(disputed)", "a2"),
        )
        self.assertEqual(
            svc.effective_state(self.honor, scene),
            {"rank": "Sergeant (acting) (disputed)"},
        )

    def test_earlier_scene_sees_no_append(self) -> None:
        s1 = self._new_scene("S1", "The case opens.")
        self._new_scene("S2", self._marker("rank", "add", "(acting)", "a1"))
        self.assertEqual(svc.effective_state(self.honor, s1), {})

    # --- validation ---------------------------------------------------------

    def test_add_on_text_field_is_not_a_warning(self) -> None:
        self._new_scene("S2", self._marker("rank", "add", "(acting)", "a1"))
        warnings = svc.validate_project().warnings
        self.assertFalse(any("only valid on" in w for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
