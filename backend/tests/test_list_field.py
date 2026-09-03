"""List field type (#698, ADR-0048 §6).

An ordered list whose item shape is a named group (`item_group`, values =
maps keyed by member key) or a single scalar (`item_type` sugar, values =
flat scalars). Covers: soft shape-conflict integrity (cross-layer merges must
never make the schema unreadable), resolver stamping of `item_members` (one
internal model; authored copies purged), schema-integrity checks (unknown
group; reference/tag members allowed as of ADR-0081, date/multi_select still
out), per-item value
validation through the real save path, the AI patch path's whole-field drop
(a partial list would let adopt silently delete items), option migration for
the select sugar, the nested unknown-member read heal, the delete-group
referential guard, and the at-or-above-layer visibility rule for item_group.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare, declare_full_chain, make_project_folder

from app.models import (
    CreateLoreEntryRequest,
    DeleteMetadataGroupRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
)
from app.services.ai.helpers import _fields
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class ListFieldModelTests(unittest.TestCase):
    def test_shape_conflicts_parse_without_raising(self) -> None:
        # Deliberately NOT model validators: a cross-layer merge can combine
        # an ancestor's item_group with a child's item_type, and a raising
        # validator would make the merged schema unreadable (500 on every
        # read). The rules are soft schema-integrity errors instead
        # (covered in ListFieldProjectTests below).
        MetadataFieldDefinition(name="Qs", type="list")
        MetadataFieldDefinition(name="Qs", type="list", item_group="g", item_type="text")
        MetadataFieldDefinition(name="Qs", type="list", item_group="g")
        MetadataFieldDefinition(name="Qs", type="list", item_type="text")
        MetadataFieldDefinition(name="T", type="text", item_type="text")


class ListFieldProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "universe" / "series" / "test"
        self.service = ProjectService.created_at(self.root, "Test Project")
        declare_full_chain(self.service, self.root, self.base)
        self._seed_list_schema()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_list_schema(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("groups", {})["open_question"] = {
            "name": "Open question",
            "members": [
                {"key": "question", "name": "Question", "type": "text"},
                {"key": "status", "name": "Status", "type": "select", "options": ["open", "answered"]},
                {"key": "note", "name": "Note", "type": "long_text"},
            ],
        }
        fields = data.setdefault("fields", {})
        fields["open_questions"] = {"name": "Open questions", "type": "list", "item_group": "open_question"}
        fields["nicknames"] = {"name": "Nicknames", "type": "list", "item_type": "text"}
        character = data["entry_types"].get("lore:character") or {}
        member_fields = list(character.get("fields") or [])
        for field_id in ("open_questions", "nicknames"):
            if field_id not in member_fields:
                member_fields.append(field_id)
        character["fields"] = member_fields
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def _create_character(self) -> str:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        return entry.id

    def _save_metadata(self, entry_id: str, metadata: dict) -> None:
        entry = self.service.read_lore_entry(entry_id)
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=entry.body,
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata=metadata,
            ),
        )

    # ---- built-in group visibility (#1003) ----

    def test_builtin_plot_link_groups_are_marked_system(self) -> None:
        # The plot-board machinery groups are consumed by feature code by id and
        # must stay out of the author-facing reusable-group pickers, so they are
        # flagged `system`. The plot-beat *shape* remains author-facing, and a
        # user-defined group defaults to non-system.
        groups = self.service.read_metadata_schema().groups
        self.assertTrue(groups["plot_instance_beat"].system)
        self.assertTrue(groups["plot_beat_link"].system)
        self.assertTrue(groups["plot_causal_link"].system)
        self.assertFalse(groups["plot_beat"].system)
        self.assertFalse(groups["open_question"].system)

    # ---- resolver stamping (one internal model) ----

    def test_resolver_stamps_group_item_members(self) -> None:
        field = self.service.read_metadata_schema().fields["open_questions"]
        assert field.item_members is not None
        self.assertEqual([m.key for m in field.item_members], ["question", "status", "note"])
        self.assertEqual(field.item_members[1].type, "select")
        self.assertEqual([opt.value for opt in field.item_members[1].options], ["open", "answered"])

    def test_resolver_normalizes_item_type_sugar_to_one_member(self) -> None:
        field = self.service.read_metadata_schema().fields["nicknames"]
        assert field.item_members is not None
        self.assertEqual(len(field.item_members), 1)
        self.assertEqual(field.item_members[0].key, "value")
        self.assertEqual(field.item_members[0].type, "text")

    # ---- schema integrity ----

    def test_unknown_item_group_is_a_schema_error(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["broken"] = {"name": "Broken", "type": "list", "item_group": "nope"}
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(any("references unknown group nope" in error for error in errors), errors)

    def test_reference_members_allowed_but_date_still_rejected(self) -> None:
        # ADR-0081: a ref member (slice 2) and a ref-LIST member (slice 3) are
        # valid item shapes — the one metadata-ref traversal indexes/scrubs/heals
        # a nested ref wherever it lives, so neither is a silent mis-link.
        # date/multi_select stay out (no item affordances). A tag vocabulary is
        # itself an entity_ref_list member now (ADR-0082 slice 2b — the `tags`
        # field type is retired), so this covers that shape too.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["cast"] = {
            "name": "Cast",
            "members": [
                {"key": "who", "name": "Who", "type": "entity_ref"},
                {"key": "topics", "name": "Topics", "type": "entity_ref_list"},
            ],
        }
        data["fields"]["cast_list"] = {"name": "Cast list", "type": "list", "item_group": "cast"}
        data["groups"]["schedule"] = {
            "name": "Schedule",
            "members": [{"key": "at", "name": "At", "type": "date"}],
        }
        data["fields"]["schedule_list"] = {"name": "Schedule", "type": "list", "item_group": "schedule"}
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        # The entity_ref and entity_ref_list members are accepted — no integrity error names them.
        self.assertFalse(any("member who" in error for error in errors), errors)
        self.assertFalse(any("member topics" in error for error in errors), errors)
        # date is still not a supported item member.
        self.assertTrue(any("member at of type date" in error for error in errors), errors)

    # ---- per-item value validation through the real save path ----

    def test_saves_valid_items_both_shapes(self) -> None:
        entry_id = self._create_character()
        self._save_metadata(
            entry_id,
            {
                "open_questions": [
                    {"question": "Who forged the letter?", "status": "open", "note": "Ch. 12"},
                    {"question": "Where is the key?"},
                ],
                "nicknames": ["Ash", "Harbor Rat"],
            },
        )
        saved = self.service.read_lore_entry(entry_id)
        self.assertEqual(len(saved.metadata["open_questions"]), 2)
        self.assertEqual(saved.metadata["nicknames"], ["Ash", "Harbor Rat"])

    def test_rejects_bad_member_value_naming_the_item(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"open_questions\[1\]\.status must be one of"):
            self._save_metadata(
                entry_id,
                {"open_questions": [{"question": "ok"}, {"question": "x", "status": "bogus"}]},
            )

    def test_rejects_unknown_member_key(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"open_questions\[0\] has unknown member severity"):
            self._save_metadata(entry_id, {"open_questions": [{"severity": "high"}]})

    def test_rejects_non_map_item_for_group_shape(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"open_questions\[0\] must be a map"):
            self._save_metadata(entry_id, {"open_questions": ["just a string"]})

    def test_rejects_non_scalar_item_for_item_type(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"nicknames\[1\] must be text"):
            self._save_metadata(entry_id, {"nicknames": ["ok", 7]})

    # ---- AI patch path: whole-field drop + catalog ----

    def test_ai_draft_drops_whole_list_on_any_bad_item(self) -> None:
        # The prompt asks for the COMPLETE replacement list, so keeping only
        # the valid items would let adopt silently delete the entry's other
        # items while the UI reports the field as merely "ignored". A field
        # with any illegal item drops whole; the current value stays intact.
        raw = json.dumps(
            {
                "body": "",
                "fields": {
                    "open_questions": [
                        {"question": "Good", "status": "open"},
                        {"question": "Bad", "status": "bogus"},
                    ],
                    "nicknames": ["ok", "fine"],
                },
            }
        )
        patch = self.service.validate_ai_entry_draft("lore:character", raw)
        self.assertFalse(patch.garbled)
        self.assertNotIn("open_questions", patch.fields)
        self.assertIn("open_questions", patch.dropped)
        # The clean list still rides through untouched.
        self.assertEqual(patch.fields["nicknames"], ["ok", "fine"])

    # ---- review-round regressions (the fixes the findings demanded) ----

    def test_both_shape_keys_is_a_soft_integrity_error_not_a_500(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["conflicted"] = {
            "name": "Conflicted",
            "type": "list",
            "item_group": "open_question",
            "item_type": "text",
        }
        character = data["entry_types"]["lore:character"]
        character["fields"].append("conflicted")
        self.service._write_yaml(schema_path, data)
        # The schema stays READABLE (no raise) …
        schema = self.service.read_metadata_schema()
        # … the conflict is reported …
        errors = self.service._validate_metadata_schema_definition(schema)
        self.assertTrue(any("declares both item_group and item_type" in e for e in errors), errors)
        # … and the resolver breaks the tie deterministically: item_group wins,
        # stamped as a NON-scalar shape.
        field = schema.fields["conflicted"]
        assert field.item_members is not None
        self.assertEqual([m.key for m in field.item_members], ["question", "status", "note"])
        self.assertFalse(field.item_scalar)
        # The tie-break must reach the SAVE path too — validation keys on
        # item_scalar, not the raw item_type, so a record value validates as a
        # record (not a flat scalar against members[0]) and the entry stays
        # readable/saveable.
        entry_id = self._create_character()
        self._save_metadata(entry_id, {"conflicted": [{"question": "Who?", "status": "open"}]})
        saved = self.service.read_lore_entry(entry_id)
        self.assertEqual(saved.metadata["conflicted"], [{"question": "Who?", "status": "open"}])

    def test_neither_shape_key_is_a_soft_integrity_error(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["shapeless"] = {"name": "Shapeless", "type": "list"}
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(any("declares neither item_group nor item_type" in e for e in errors), errors)

    def test_delete_group_refused_while_a_list_field_uses_it(self) -> None:
        with self.assertRaisesRegex(ProjectServiceError, "item shape of list field open_questions"):
            self.service.delete_metadata_group(DeleteMetadataGroupRequest(group_id="open_question"))

    def test_unknown_group_with_sugar_falls_back_to_the_sugar(self) -> None:
        # Tie-break edge: item_group set-but-unknown AND item_type present must
        # fall back to the sugar (serviceable), not leave the field shapeless.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["fallback"] = {
            "name": "Fallback",
            "type": "list",
            "item_group": "nope",
            "item_type": "text",
        }
        self.service._write_yaml(schema_path, data)
        field = self.service.read_metadata_schema().fields["fallback"]
        assert field.item_members is not None
        self.assertTrue(field.item_scalar)
        self.assertEqual(field.item_members[0].type, "text")

    def test_multi_select_member_rejected_as_item_shape(self) -> None:
        # The positive catalog check (LIST_ITEM_SCALAR_TYPES) closes the hole
        # the old deny-tuple left: multi_select is a legal group member but not
        # a legal list item shape.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["ms"] = {"name": "MS", "members": [{"key": "tags", "name": "Tags", "type": "multi_select"}]}
        data["fields"]["ms_list"] = {"name": "MS list", "type": "list", "item_group": "ms"}
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(any("member tags of type multi_select" in e for e in errors), errors)

    def test_option_migration_preserves_duplicate_ordered_list_items(self) -> None:
        # An ordered list legitimately repeats values — the migration must NOT
        # de-duplicate the way multi_select does.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["status_log"] = {
            "name": "Status log", "type": "list", "item_type": "select", "options": ["open", "answered"],
        }
        data["entry_types"]["lore:character"]["fields"].append("status_log")
        self.service._write_yaml(schema_path, data)
        entry_id = self._create_character()
        self._save_metadata(entry_id, {"status_log": ["open", "answered", "open"]})

        from app.models import SelectOption

        old_field = self.service.read_metadata_schema().fields["status_log"]
        new_field = old_field.model_copy(
            update={"options": [SelectOption(value="unresolved"), SelectOption(value="answered")]}
        )
        data = self.service._read_yaml(schema_path)
        data["fields"]["status_log"]["options"] = ["unresolved", "answered"]
        self.service._write_yaml(schema_path, data)
        self.service._apply_option_value_changes(
            self.root, "status_log", old_field, new_field, {"open": "unresolved"}
        )
        saved = self.service.read_lore_entry(entry_id)
        self.assertEqual(saved.metadata["status_log"], ["unresolved", "answered", "unresolved"])

    def test_move_field_refused_when_group_not_visible_at_target(self) -> None:
        from app.models import MoveMetadataFieldRequest

        layers = self.service.read_metadata_schema_layers().layers
        series_layer = next(
            layer for layer in layers
            if Path(layer.folder_path).resolve() == (self.base / "universe" / "series").resolve()
        )
        with self.assertRaisesRegex(ProjectServiceError, "not defined at or above the target layer"):
            self.service.move_metadata_field(
                MoveMetadataFieldRequest(
                    field_id="open_questions", target_layer_id=series_layer.id, entry_type="lore:character"
                )
            )

    def test_option_migration_rewrites_select_sugar_list_values(self) -> None:
        # list + item_type:select stores the same flat scalar sequence
        # multi_select does — option renames/removals must migrate it too.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["status_log"] = {
            "name": "Status log",
            "type": "list",
            "item_type": "select",
            "options": ["open", "answered"],
        }
        character = data["entry_types"]["lore:character"]
        character["fields"].append("status_log")
        self.service._write_yaml(schema_path, data)
        entry_id = self._create_character()
        self._save_metadata(entry_id, {"status_log": ["open", "answered"]})

        from app.models import SelectOption

        old_field = self.service.read_metadata_schema().fields["status_log"]
        new_field = old_field.model_copy(
            update={"options": [SelectOption(value="unresolved"), SelectOption(value="answered")]}
        )
        # Mirror the upsert order: the schema gains the new options first,
        # then the migration rewrites stored entry data.
        data = self.service._read_yaml(schema_path)
        data["fields"]["status_log"]["options"] = ["unresolved", "answered"]
        self.service._write_yaml(schema_path, data)
        self.service._apply_option_value_changes(
            self.root, "status_log", old_field, new_field, {"open": "unresolved"}
        )
        saved = self.service.read_lore_entry(entry_id)
        self.assertEqual(saved.metadata["status_log"], ["unresolved", "answered"])

    def test_read_strips_unknown_member_keys_from_items(self) -> None:
        # A group edit can retire a member while items still carry its key —
        # the rail can't show it, so the read heals it (the nested twin of
        # _strip_unknown_metadata_fields); the next save writes back clean.
        entry_id = self._create_character()
        self._save_metadata(
            entry_id, {"open_questions": [{"question": "Who?", "note": "keep me honest"}]}
        )
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["open_question"]["members"] = [
            member
            for member in data["groups"]["open_question"]["members"]
            if member["key"] != "note"
        ]
        self.service._write_yaml(schema_path, data)
        entry = self.service.read_lore_entry(entry_id)
        self.assertEqual(entry.metadata["open_questions"], [{"question": "Who?"}])
        # And the healed value round-trips through a normal save.
        self._save_metadata(entry_id, dict(entry.metadata))

    def test_derived_item_members_never_persist_on_upsert(self) -> None:
        # Echo a RESOLVED field def (item_members stamped) back through the
        # upsert path — the layer YAML must not gain the derived block.
        from app.models import UpsertMetadataFieldRequest

        layer_id = self.service._metadata_schema_layer_id(self.root)
        resolved = self.service.read_metadata_schema().fields["open_questions"]
        assert resolved.item_members is not None
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="open_questions",
                field=resolved,
                entry_type="lore:character",
            )
        )
        raw = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("item_members", raw["fields"]["open_questions"])
        self.assertNotIn("category", raw["fields"]["open_questions"])

    def test_authored_item_members_is_purged_on_read(self) -> None:
        # A stale/authored item_members copy in a layer is purged on read, so
        # a deleted group can't keep validating against a frozen shape and a
        # hand-authored shape can't bypass the member-type ban.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["open_questions"]["item_members"] = [
            {"key": "question", "name": "Question", "type": "text"}
        ]
        self.service._write_yaml(schema_path, data)
        field = self.service.read_metadata_schema().fields["open_questions"]
        assert field.item_members is not None
        # Re-stamped from the group (three members), not the authored copy.
        self.assertEqual(len(field.item_members), 3)

    def test_item_group_must_be_visible_at_or_above_the_target_layer(self) -> None:
        # ADR-0045 shape: the group lives only in THIS project's layer, so a
        # sibling project inheriting the series layer could never resolve it —
        # authoring the field into the series layer must refuse.
        from app.models import UpsertMetadataFieldRequest

        layers = self.service.read_metadata_schema_layers().layers
        series_layer = next(
            layer for layer in layers if Path(layer.folder_path).resolve() == (self.base / "universe" / "series").resolve()
        )
        with self.assertRaisesRegex(ProjectServiceError, "not defined at or above this layer"):
            self.service.upsert_metadata_field(
                UpsertMetadataFieldRequest(
                    layer_id=series_layer.id,
                    field_id="series_questions",
                    field=MetadataFieldDefinition(
                        name="Series questions", type="list", item_group="open_question"
                    ),
                    entry_type="lore:character",
                )
            )

    def test_fields_describes_item_shapes(self) -> None:
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, "lore:character")
        by_id = {descriptor["id"]: descriptor for descriptor in roster}
        self.assertIn("open_questions", by_id)
        self.assertFalse(by_id["open_questions"]["item_scalar"])
        self.assertEqual(
            [member["key"] for member in by_id["open_questions"]["items"]],
            ["question", "status", "note"],
        )
        self.assertEqual(by_id["open_questions"]["items"][1]["options"], ["open", "answered"])
        self.assertTrue(by_id["nicknames"]["item_scalar"])
        self.assertEqual(by_id["nicknames"]["items"][0]["type"], "text")


class DeleteGroupSiblingGuardTests(unittest.TestCase):
    """#701: deleting a shared group must not strand a SIBLING project that
    references it. The delete rewrites the shared ancestor layer, but the
    in-project guards see only the open project's chain — a book that inherits
    the same ancestor without appearing in this chain is invisible to them.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.book_a = self.series / "book-a"
        self.book_b = self.series / "book-b"
        self.service = ProjectService.created_at(self.book_a, "Book A")
        # book-a inherits the shared series layer; machine root = base.
        declare(self.service, self.book_a, [self.series], base=self.base)
        # The shared group lives in the series layer, above both books.
        self.service._write_yaml(
            self.series / "metadata.schema.yaml",
            {"groups": {"beat": {"name": "Beat", "members": [{"key": "name", "name": "Name", "type": "text"}]}}},
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_book_b(self, schema: dict) -> None:
        make_project_folder(self.service, self.book_b, "Book B")
        manifest = self.service._read_yaml(self.book_b / "project.yaml")
        manifest["inherits"] = ["../series"]
        self.service._write_yaml(self.book_b / "project.yaml", manifest)
        self.service._write_yaml(self.book_b / "metadata.schema.yaml", schema)

    def _delete_beat(self):
        return self.service.delete_metadata_group(DeleteMetadataGroupRequest(group_id="beat"))

    def test_refused_when_a_sibling_list_field_references_the_group(self) -> None:
        self._make_book_b({"fields": {"beats": {"name": "Beats", "type": "list", "item_group": "beat"}}})
        with self.assertRaisesRegex(ProjectServiceError, r"referenced by book-b \(list field beats\)"):
            self._delete_beat()
        # Refused before any rewrite — the series copy is untouched.
        self.assertIn("beat", self.service.read_metadata_schema().groups)

    def test_refused_when_a_sibling_applies_the_group_to_a_type(self) -> None:
        self._make_book_b(
            {"entry_types": {"lore:character": {"group_applications": [{"group_id": "beat"}]}}}
        )
        with self.assertRaisesRegex(
            ProjectServiceError, r"referenced by book-b \(an application on lore:character\)"
        ):
            self._delete_beat()

    def test_allowed_when_no_sibling_references_the_group(self) -> None:
        self._make_book_b({"fields": {"scenes": {"name": "Scenes", "type": "list", "item_type": "text"}}})
        self._delete_beat()
        self.assertNotIn("beat", self.service.read_metadata_schema().groups)

    def test_allowed_when_the_sibling_shadows_the_group_in_its_own_layer(self) -> None:
        # book-b references beat but also DEFINES its own beat in its own layer,
        # which this delete never touches — so the reference stays resolvable and
        # nothing is stranded. Exercises the survival branch.
        self._make_book_b(
            {
                "groups": {"beat": {"name": "Beat", "members": [{"key": "name", "name": "Name", "type": "text"}]}},
                "fields": {"beats": {"name": "Beats", "type": "list", "item_group": "beat"}},
            }
        )
        self._delete_beat()
        # The series-layer copy is gone…
        self.assertNotIn("beat", self.service.read_metadata_schema().groups)
        # …and book-b still resolves the group from its own layer.
        self.assertIn("beat", self.service.read_metadata_schema(self.book_b).groups)


if __name__ == "__main__":
    unittest.main()
