"""Restore-time mutation conversion (ADR-0095 §11): a pre-v14 snapshot's
legacy markers convert on the way out, and every restore re-mints a duplicate
anchor id regardless of the snapshot's own schema version.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateLoreEntryRequest, CreateSceneRequest, SaveSceneRequest
from app.services.project.legacy_mutation_markers import ConvertedRow, ConvertedSet
from app.services.project.mutation_anchors import (
    MUTATION_ANCHOR_PATTERN,
    derive_anchor_id,
    derive_set_id,
    render_anchor,
)


class _RestoreFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Restore Mutations Tests")
        self.honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        ).id

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ---- helpers -------------------------------------------------------------

    def _new_scene(self, title: str, body: str = "") -> str:
        scene = self.service.create_scene(CreateSceneRequest(title=title))
        self.service.save_scene(scene.id, SaveSceneRequest(title=title, body=body))
        return scene.id

    def _set_body(self, scene_id: str, title: str, body: str) -> None:
        current = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=title, body=body, status=current.status,
                entry_type=current.entry_type, metadata=current.metadata,
            ),
        )

    def _downgrade_sidecar(self, scene_id: str, snapshot_id: str, version: int) -> None:
        sidecar = self.root / "snapshots" / scene_id / f"{snapshot_id}.yaml"
        data = self.service._read_yaml(sidecar)
        data["schema_version"] = version
        self.service._write_yaml(sidecar, data)

    def _write_set(self, set_id: str, entity_id: str, field: str, value: str, target_entry_type: str = "lore:character") -> None:
        self.service._write_converted_mutation_set(
            ConvertedSet(
                set_id=set_id,
                anchor_id="",
                scene_id="",
                entity_id=entity_id,
                title="",
                target_entry_type=target_entry_type,
                rows=[ConvertedRow(id="row_1", field=field, op="replace", value=value)],
                unit_id="",
            )
        )

    def _anchor_ids(self, body: str) -> list[str]:
        return [m.group("id") for m in MUTATION_ANCHOR_PATTERN.finditer(body)]

    def _set_ids(self, body: str) -> list[str]:
        return [m.group("set_id") for m in MUTATION_ANCHOR_PATTERN.finditer(body)]


class PreV14SnapshotConversionTests(_RestoreFixture):
    def test_restore_with_its_set_already_present_resolves_to_it(self) -> None:
        scene_id = self._new_scene("One")
        marker = f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 -->"
        self._set_body(scene_id, "One", marker)
        record = self.service.capture_snapshot(scene_id)
        self._downgrade_sidecar(scene_id, record.id, 13)
        set_id = derive_set_id("m1")
        self._write_set(set_id, self.honor, "rank", "Captain")
        self._set_body(scene_id, "One", "cleared")  # the live scene moves on

        restored = self.service.restore_snapshot(scene_id, record.id)

        self.assertEqual(self._set_ids(restored.body), [set_id])
        self.assertEqual(self._anchor_ids(restored.body), ["m1"])
        # No new set: only the one already on disk.
        self.assertEqual(len(list((self.root / "mutation-sets").glob("*.md"))), 1)

    def test_restore_with_its_set_deleted_recreates_it_from_the_marker(self) -> None:
        scene_id = self._new_scene("One")
        marker = f"<!-- mutate:entity={self.honor};field=rank;value=Captain;name=Promotion;id=m1 -->"
        self._set_body(scene_id, "One", marker)
        record = self.service.capture_snapshot(scene_id)
        self._downgrade_sidecar(scene_id, record.id, 13)
        self._set_body(scene_id, "One", "cleared")
        self.assertEqual(list((self.root / "mutation-sets").glob("*.md")), [])

        restored = self.service.restore_snapshot(scene_id, record.id)

        set_id = derive_set_id("m1")
        self.assertEqual(self._set_ids(restored.body), [set_id])
        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.title, "Promotion")
        self.assertEqual(entry.rows[0].field, "rank")
        self.assertEqual(entry.rows[0].value, "Captain")

    def test_a_repeated_unit_id_resolves_to_the_per_scene_set_not_a_copy_of_the_first(self) -> None:
        # Scene one keeps the bare id (the first occurrence, as the real
        # migration would have left it); scene two's own per-scene set already
        # exists too (as if the real migration had already run once).
        scene1 = self._new_scene("One")
        scene2 = self._new_scene("Two")
        first_set = derive_set_id("dup")
        self._write_set(first_set, self.honor, "rank", "Commodore")
        self._set_body(scene1, "One", render_anchor(first_set, "dup"))

        marker = f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=dup -->"
        self._set_body(scene2, "Two", marker)
        record = self.service.capture_snapshot(scene2)
        self._downgrade_sidecar(scene2, record.id, 13)
        self._set_body(scene2, "Two", "cleared")

        # The migration derives the per-scene set/anchor from THIS scene's own
        # id, which the fixture above must match for the lookup to succeed —
        # recompute it the way §12/§11 do, from the restored scene's own id.
        expected_set = derive_set_id(f"{scene2}:dup")
        self._write_set(expected_set, self.honor, "rank", "Captain")

        restored = self.service.restore_snapshot(scene2, record.id)

        self.assertEqual(self._set_ids(restored.body), [expected_set])
        self.assertNotEqual(expected_set, first_set)
        self.assertEqual(self._anchor_ids(restored.body), [derive_anchor_id(scene2, "dup")])
        # Scene one, unrelated, is untouched.
        self.assertEqual(self._set_ids(self.service.read_scene(scene1).body), [first_set])


class DuplicateAnchorRestoreTests(_RestoreFixture):
    def test_an_anchor_now_in_another_scene_is_re_minted_and_its_set_copied(self) -> None:
        scene_a = self._new_scene("A")
        scene_b = self._new_scene("B")
        set_id = derive_set_id("shared-set")
        # An unvalidated row (a field no schema defines) — the copy must keep
        # it exactly, never drop it the way `copy_mutation_set_entry` would.
        self._write_set(set_id, self.honor, "no_such_field", "anything")
        anchor_text = render_anchor(set_id, "anc1")
        self._set_body(scene_b, "B", f"Before. {anchor_text} After.")
        record = self.service.capture_snapshot(scene_b)
        # The cut: scene B moves on, scene A now holds the anchor instead.
        self._set_body(scene_b, "B", "moved on")
        self._set_body(scene_a, "A", f"Elsewhere. {anchor_text} too.")
        scene_a_before = self.service.read_scene(scene_a).body

        restored = self.service.restore_snapshot(scene_b, record.id)

        new_anchor_ids = self._anchor_ids(restored.body)
        new_set_ids = self._set_ids(restored.body)
        self.assertEqual(len(new_anchor_ids), 1)
        self.assertNotEqual(new_anchor_ids[0], "anc1")
        self.assertNotEqual(new_set_ids[0], set_id)
        copied = self.service.read_mutation_set_entry(new_set_ids[0])
        self.assertEqual(copied.rows[0].field, "no_such_field")
        self.assertEqual(copied.rows[0].value, "anything")
        # Scene A, the scene that now legitimately owns the original anchor,
        # is completely untouched.
        self.assertEqual(self.service.read_scene(scene_a).body, scene_a_before)
        self.assertIn("anc1", scene_a_before)


if __name__ == "__main__":
    unittest.main()
