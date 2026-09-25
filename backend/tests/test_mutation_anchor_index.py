"""ADR-0095 §1/§3/§5/§10/§Verify: the mutations index reads anchors joined
with sets. Legacy markers are gone from this path (`test_legacy_mutation_markers.py`
and the fixtures moved by `mutation_helpers.save_scenes_with_mutations` cover
that grammar and its conversion); these tests exercise the new grammar and the
join directly — a missing/other-layer/unusable set, a duplicate anchor id, a
linked set's two independent intervals, row vs anchor closes, `exclude` by
anchor, an edit that changes resolution without touching the scene file, and
each Verify warning ADR-0095 adds.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.models import (
    CreateLoreEntryRequest,
    CreateMutationSetEntryRequest,
    CreateSceneRequest,
    MetadataFieldDefinition,
    MutationSetRow,
    SaveMutationSetEntryRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
)
from app.scope import WorkScope
from app.services.project.mutation_anchors import render_anchor, render_close
from app.services.project_service import ProjectService


def _define_rank_field(service: ProjectService) -> None:
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id="rank",
            field=MetadataFieldDefinition(name="Rank", type="text"),
            entry_type="lore:character",
        )
    )


class _AnchorFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Mutation Anchor Index Tests")
        _define_rank_field(self.service)
        self.honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        ).id

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- fixture helpers ----------------------------------------------------

    def _new_scene(self, title: str, body: str = "") -> str:
        scene = self.service.create_scene(CreateSceneRequest(title=title))
        self.service.save_scene(scene.id, SaveSceneRequest(title=title, body=body))
        return scene.id

    def _set_scene_body(self, scene_id: str, body: str) -> None:
        current = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=current.title, body=body, status=current.status,
                entry_type=current.entry_type, metadata=current.metadata,
            ),
        )

    def _make_set(self, field: str, value: str, target_entity: str | None = None, title: str = "") -> str:
        entity = self.honor if target_entity is None else target_entity
        entry = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title=title,
                target_entry_type="lore:character",
                target_entity=entity,
                rows=[MutationSetRow(field=field, op="replace", value=value)],
            )
        )
        return entry.id

    def _make_dead_pin_set(self, field: str, value: str) -> str:
        """A set whose pin names a lore entry that does not exist — hand-edit
        the front matter directly rather than deleting a real entry, because
        pre-ADR-0095-§9 deletion still purges the pin to "" (a template), the
        behaviour §9/S3 supersedes; that slice is out of scope here."""
        set_id = self._make_set(field, value)
        path = self.service._path_for_node_id(set_id, "mutation_set")
        front_matter, body = self.service._read_markdown_with_front_matter(path, strict=True)
        front_matter.setdefault("metadata", {})["target_entity"] = "lore_ghost"
        self.service._write_markdown_with_front_matter(path, front_matter, body)
        return set_id


class MissingAndUnusableSetTests(_AnchorFixture):
    def test_anchor_to_a_missing_set_contributes_nothing(self) -> None:
        scene = self._new_scene("Chapter One", render_anchor("mutation_set_ghost", "a1"))
        self.assertEqual(self.service.effective_state(self.honor, scene), {})

    def test_anchor_to_a_set_only_in_an_ancestor_layer_contributes_nothing(self) -> None:
        base = self.root.parent / "writing_base"
        series = base / "series"
        book = series / "book01"
        book.mkdir(parents=True)
        book_service = ProjectService.created_at(book, "Book 1")
        declare_full_chain(book_service, book, base)
        series_writer = ProjectService(WorkScope(root=series))
        declare_full_chain(series_writer, series, base)
        _define_rank_field(series_writer)
        honor = series_writer.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        ).id
        series_set = series_writer.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entry_type="lore:character",
                target_entity=honor,
                rows=[MutationSetRow(field="rank", op="replace", value="Captain")],
            )
        )
        scene = book_service.create_scene(CreateSceneRequest(title="Chapter One"))
        book_service.save_scene(
            scene.id,
            SaveSceneRequest(title="Chapter One", body=render_anchor(series_set.id, "a1")),
        )
        self.assertEqual(book_service.effective_state(honor, scene.id), {})

    def test_unpinned_set_contributes_nothing(self) -> None:
        # A template (no pin) anchored anyway (§2: templates are never
        # anchored by the app, but a hand-edited scene or a sync conflict can).
        template = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entry_type="lore:character",
                rows=[MutationSetRow(field="rank", op="replace", value="Captain")],
            )
        )
        scene = self._new_scene("Chapter One", render_anchor(template.id, "a1"))
        self.assertEqual(self.service.effective_state(self.honor, scene), {})

    def test_dead_pin_contributes_nothing(self) -> None:
        set_id = self._make_dead_pin_set("rank", "Captain")
        scene = self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        self.assertEqual(self.service.effective_state(self.honor, scene), {})


class DuplicateAnchorTests(_AnchorFixture):
    def test_duplicate_anchor_id_only_the_first_in_manuscript_order_resolves(self) -> None:
        set_a = self._make_set("rank", "Captain")
        set_b = self._make_set("rank", "Commodore")
        first = self._new_scene("Chapter One", render_anchor(set_a, "dup"))
        second = self._new_scene("Chapter Two", render_anchor(set_b, "dup"))
        self.assertEqual(self.service.effective_state(self.honor, first), {"rank": "Captain"})
        # The second occurrence contributes nothing — the first still wins.
        self.assertEqual(self.service.effective_state(self.honor, second), {"rank": "Captain"})


class LinkedSetTests(_AnchorFixture):
    def test_two_anchors_of_the_same_set_are_two_independent_intervals(self) -> None:
        set_id = self._make_set("rank", "Captain")
        self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        ch2 = self._new_scene("Chapter Two", render_anchor(set_id, "a2"))
        self._new_scene("Chapter Three", render_close("a1", "c1"))
        ch4 = self._new_scene("Chapter Four", "Later.")
        # Both anchors are live going into ch3.
        self.assertEqual(self.service.effective_state(self.honor, ch2), {"rank": "Captain"})
        # Closing a1 (in ch3) ends only that anchor's interval; a2 is still live
        # (a1 < a2 in manuscript order, so at ch3's own position a1 is closed,
        # a2's interval is untouched).
        self.assertEqual(self.service.effective_state(self.honor, ch4), {"rank": "Captain"})
        self.assertEqual(
            [m.anchor_id for m in self.service.live_mutations(self.honor, ch4).items], ["a2"]
        )
        self.assertNotIn("a1", [
            m.anchor_id for m in self.service.live_mutations(self.honor, ch4).items
        ])


class CloseTests(_AnchorFixture):
    def test_row_close_vs_anchor_close(self) -> None:
        set_id = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entry_type="lore:character",
                target_entity=self.honor,
                rows=[
                    MutationSetRow(field="rank", op="replace", value="Captain", id="row_rank"),
                    MutationSetRow(field="title", op="replace", value="The Bold", id="row_title"),
                ],
            )
        ).id
        self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        # A row close ends only that row; the anchor's other row stays live.
        ch2 = self._new_scene("Chapter Two", render_close("a1", "c1", row="row_rank"))
        self.assertEqual(
            self.service.effective_state(self.honor, ch2), {"title": "The Bold"}
        )
        # An anchor close (no row=) ends every row.
        ch3 = self._new_scene("Chapter Three", render_close("a1", "c2"))
        self.assertEqual(self.service.effective_state(self.honor, ch3), {})


class ExcludeTests(_AnchorFixture):
    def test_exclude_by_anchor_id(self) -> None:
        set_id = self._make_set("rank", "Captain")
        scene = self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        self.assertEqual(
            self.service.effective_state(self.honor, scene, exclude={"a1"}), {}
        )


class SetEditTests(_AnchorFixture):
    def test_editing_a_row_value_changes_resolution_and_version_without_touching_the_scene(self) -> None:
        set_id = self._make_set("rank", "Captain")
        scene = self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        path = self.service._path_for_node_id(scene, "manuscript")
        before_bytes = path.read_bytes()
        before_version = self.service.build_mutations_index().version
        self.assertEqual(self.service.effective_state(self.honor, scene), {"rank": "Captain"})

        entry = self.service.read_mutation_set_entry(set_id)
        self.service.save_mutation_set_entry(
            set_id,
            SaveMutationSetEntryRequest(
                title=entry.title,
                entry_type=entry.entry_type,
                target_entry_type=entry.target_entry_type,
                target_entity=entry.target_entity,
                rows=[row.model_copy(update={"value": "Commodore"}) for row in entry.rows],
            ),
        )
        self.assertEqual(self.service.effective_state(self.honor, scene), {"rank": "Commodore"})
        self.assertNotEqual(before_version, self.service.build_mutations_index().version)
        self.assertEqual(path.read_bytes(), before_bytes)


class VerifyWarningTests(_AnchorFixture):
    def test_anchor_to_missing_set_warns(self) -> None:
        self._new_scene("Chapter One", render_anchor("mutation_set_ghost", "a1"))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("does not exist" in w and "a1" in w for w in warnings), warnings)

    def test_dead_pin_warns(self) -> None:
        set_id = self._make_dead_pin_set("rank", "Captain")
        self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("entity no longer exists" in w for w in warnings), warnings)

    def test_unpinned_set_warns(self) -> None:
        template = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entry_type="lore:character",
                rows=[MutationSetRow(field="rank", op="replace", value="Captain")],
            )
        )
        self._new_scene("Chapter One", render_anchor(template.id, "a1"))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("has no entity" in w for w in warnings), warnings)

    def test_duplicate_anchor_id_warns(self) -> None:
        set_a = self._make_set("rank", "Captain")
        set_b = self._make_set("rank", "Commodore")
        self._new_scene("Chapter One", render_anchor(set_a, "dup"))
        self._new_scene("Chapter Two", render_anchor(set_b, "dup"))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("duplicates the anchor" in w for w in warnings), warnings)

    def test_close_ref_with_no_anchor_warns(self) -> None:
        self._new_scene("Chapter One", render_close("no_such_anchor", "c1"))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("no anchor" in w for w in warnings), warnings)

    def test_close_row_not_in_set_warns(self) -> None:
        set_id = self._make_set("rank", "Captain")
        self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        self._new_scene("Chapter Two", render_close("a1", "c1", row="no_such_row"))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("not in that anchor's set" in w for w in warnings), warnings)

    def test_set_with_invalid_rows_warns(self) -> None:
        # target_entry_type doesn't declare "nonexistent_field" — save it
        # unvalidated the way the migration/converter does, then Verify must
        # still catch it (ADR-0095 §4/§Verify).
        set_id = self._make_set("rank", "Captain")
        path = self.service._path_for_node_id(set_id, "mutation_set")
        front_matter, body = self.service._read_markdown_with_front_matter(path, strict=True)
        front_matter["rows"] = [{"field": "nonexistent_field", "op": "replace", "value": "x", "id": "row_bad"}]
        self.service._write_markdown_with_front_matter(path, front_matter, body)
        self._new_scene("Chapter One", render_anchor(set_id, "a1"))
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("nonexistent_field" in w for w in warnings), warnings)

    def test_legacy_markers_still_in_a_scene_warn(self) -> None:
        self._new_scene(
            "Chapter One",
            f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 -->",
        )
        warnings = self.service.validate_project().warnings
        self.assertTrue(any("not migrated yet" in w for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
