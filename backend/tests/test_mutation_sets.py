"""Mutation-set Node kind CRUD (#62, ADR-0095). A `(field, op, value)` row
list + a target lore entry-type, stored in front matter under
`mutation-sets/`. The entity binding is optional: unset ⇒ a template, entity
chosen at apply time. Since ADR-0095 a set's lifecycle state — template /
staged / active — is READ from the scenes that anchor it, never stored, and
every row is validated (position-free) against the pinned entity's type on
save. Exercises the routes end-to-end.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CopyMutationSetRequest,
    CreateMutationSetEntryRequest,
    CreateSceneRequest,
    MetadataFieldDefinition,
    MutationSetRow,
    SaveLoreEntryRequest,
    SaveMutationSetEntryRequest,
    SaveSceneRequest,
    Scene,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.mutation_anchors import render_anchor
from app.services.project_service import ProjectService


def _define_field(service: ProjectService, field_id: str, field_type: str, name: str, **kwargs) -> None:
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=name, type=field_type, **kwargs),
            entry_type="lore:character",
        )
    )


class MutationSetCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Mutation Set Tests")
        _define_field(self.service, "clues", "multi_select", "Clues")
        _define_field(self.service, "abilities", "multi_select", "Abilities")
        _define_field(self.service, "rank", "text", "Rank")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create(self, title: str, target: str, rows: list[dict]) -> dict:
        res = self.client.post(
            "/api/mutation-sets",
            json={"title": title, "target_entry_type": target, "rows": rows},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_create_read_roundtrips_rows_and_target(self) -> None:
        created = self._create(
            "Full Moon",
            "lore:character",
            [
                {"field": "title", "op": "replace", "value": "The Wolf"},
                {"field": "clues", "op": "add", "value": "fur"},
            ],
        )
        self.assertTrue(created["id"].startswith("mutation_set"))
        self.assertEqual(created["target_entry_type"], "lore:character")
        self.assertEqual([r["field"] for r in created["rows"]], ["title", "clues"])
        self.assertEqual(created["rows"][1]["op"], "add")

        got = self.client.get(f"/api/mutation-sets/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["rows"], created["rows"])

    def test_stored_body_less_under_mutation_sets_folder(self) -> None:
        created = self._create("Promotion", "lore:character", [{"field": "rank", "value": "Captain"}])
        files = list((self.root / "mutation-sets").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        # Rows + target live in front matter; there is no prose body.
        self.assertIn("target_entry_type: lore:character", text)
        self.assertIn("rank", text)
        del created

    def test_list_reports_row_count_and_target(self) -> None:
        self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        self._create(
            "Relocate",
            "lore:location",
            [{"field": "title", "value": "Ruins"}, {"field": "location_type", "value": "landmark"}],
        )
        listing = self.client.get("/api/mutation-sets").json()["entries"]
        by_title = {e["title"]: e for e in listing}
        self.assertEqual(by_title["Full Moon"]["row_count"], 1)
        self.assertEqual(by_title["Relocate"]["row_count"], 2)
        self.assertEqual(by_title["Relocate"]["target_entry_type"], "lore:location")

    def test_save_updates_rows(self) -> None:
        created = self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        res = self.client.put(
            f"/api/mutation-sets/{created['id']}",
            json={
                "title": "Full Moon",
                "target_entry_type": "lore:character",
                "rows": [
                    {"field": "title", "op": "replace", "value": "The Grey Wolf"},
                    {"field": "abilities", "op": "add", "value": "night vision"},
                ],
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(res.json()["rows"]), 2)
        self.assertEqual(res.json()["rows"][0]["value"], "The Grey Wolf")

    def test_delete_removes_the_set(self) -> None:
        created = self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        res = self.client.delete(f"/api/mutation-sets/{created['id']}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["entries"], [])
        self.assertEqual(self.client.get(f"/api/mutation-sets/{created['id']}").status_code, 404)

    def test_mutation_set_node_is_indexed_by_kind(self) -> None:
        created = self._create("Full Moon", "lore:character", [{"field": "title", "value": "The Wolf"}])
        index = self.service._build_node_index()
        entry = index.by_id.get(created["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, "mutation_set")


class MutationSetRowValidationTests(unittest.TestCase):
    """ADR-0095 §3/§4: ids are minted, duplicates and bad ops are refused, and
    every row is validated position-free against the pinned entity's type (or
    the set's own `target_entry_type` when unpinned)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Row Validation Tests")
        _define_field(self.service, "rank", "text", "Rank")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_character(self, node_id: str, title: str = "Mira") -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.root / "lore" / f"{node_id}.md",
            {"id": node_id, "title": title, "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

    def test_row_ids_minted_on_create_and_kept_on_save(self) -> None:
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entry_type="lore:character",
                rows=[MutationSetRow(field="rank", op="replace", value="Captain")],
            )
        )
        self.assertTrue(created.rows[0].id)
        kept_id = created.rows[0].id
        row = created.rows[0].model_copy(update={"value": "Commodore"})
        saved = self.service.save_mutation_set_entry(
            created.id,
            SaveMutationSetEntryRequest(target_entry_type="lore:character", rows=[row]),
        )
        self.assertEqual(saved.rows[0].id, kept_id)
        self.assertEqual(saved.rows[0].value, "Commodore")

    def test_duplicate_row_id_is_422(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_mutation_set_entry(
                CreateMutationSetEntryRequest(
                    target_entry_type="lore:character",
                    rows=[
                        MutationSetRow(field="rank", op="replace", value="Captain", id="r1"),
                        MutationSetRow(field="rank", op="replace", value="Commodore", id="r1"),
                    ],
                )
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_bad_op_is_422(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_mutation_set_entry(
                CreateMutationSetEntryRequest(
                    target_entry_type="lore:character",
                    rows=[MutationSetRow(field="rank", op="increment", value="1")],
                )
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_unknown_field_for_pinned_type_is_422_naming_the_field(self) -> None:
        self._write_character("mira")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_mutation_set_entry(
                CreateMutationSetEntryRequest(
                    target_entry_type="lore:character",
                    target_entity="mira",
                    rows=[MutationSetRow(field="warp_speed", op="replace", value="9")],
                )
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("warp_speed", ctx.exception.message)

    def test_keyed_list_member_row_saves_without_a_position_check(self) -> None:
        # A reference-keyed list member row (`<field>.<target>.<member>`) is
        # saved with no manuscript position — the check that an item must
        # already exist there (`_item_keys_before`) does not apply to a set.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("groups", {})["relationship"] = {
            "name": "Relationship",
            "members": [
                {"key": "to", "name": "Who", "type": "entity_ref"},
                {"key": "kind", "name": "Kind", "type": "text"},
            ],
        }
        data.setdefault("fields", {})["relationships"] = {
            "name": "Relationships",
            "type": "list",
            "item_group": "relationship",
        }
        character = data["entry_types"].get("lore:character") or {}
        own = list(character.get("fields") or [])
        own.append("relationships")
        character["fields"] = own
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

        self._write_character("mira")
        self._write_character("tomas", "Tomas")
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entry_type="lore:character",
                target_entity="mira",
                rows=[MutationSetRow(field="relationships.tomas.kind", op="replace", value="ally")],
            )
        )
        self.assertEqual(created.rows[0].value, "ally")

    def test_dead_pin_still_saves(self) -> None:
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entity="ghost",  # no such lore entry
                rows=[MutationSetRow(field="anything_at_all", op="replace", value="x")],
            )
        )
        self.assertEqual(created.rows[0].value, "x")
        self.assertTrue(created.pin_missing)

    def test_untitled_create_returns_title_empty(self) -> None:
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                target_entry_type="lore:character",
                rows=[MutationSetRow(field="rank", op="replace", value="Captain")],
            )
        )
        self.assertEqual(created.title, "")


class MutationSetFileNamingTests(unittest.TestCase):
    """ADR-0095 §12: a NEW set's file is named after its id, not its title —
    a title (or a title change on save) never renames it."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "File Naming Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_new_set_file_is_named_after_its_id(self) -> None:
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Full Moon",
                target_entry_type="lore:character",
                rows=[MutationSetRow(field="title", op="replace", value="The Wolf")],
            )
        )
        path = self.root / "mutation-sets" / f"{created.id}.md"
        self.assertTrue(path.exists())

    def test_save_with_a_new_title_does_not_rename_the_file(self) -> None:
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Full Moon",
                target_entry_type="lore:character",
                rows=[MutationSetRow(field="title", op="replace", value="The Wolf")],
            )
        )
        self.service.save_mutation_set_entry(
            created.id,
            SaveMutationSetEntryRequest(
                title="The Grey Wolf Returns",
                target_entry_type="lore:character",
                rows=created.rows,
            ),
        )
        files = list((self.root / "mutation-sets").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stem, created.id)


class MutationSetEntityPinTests(unittest.TestCase):
    """The optional entity pin (ADR-0055 §3): a `target_entity` `entity_ref`
    stored in `metadata` (not the top-level front matter that carries
    target_entry_type/rows), so it rides the kind-neutral edge machinery — a
    set→subject reverse edge and reference-integrity — while a reusable
    (un-pinned) set stays byte-identical to today's."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Pin Tests")
        _define_field(self.service, "rank", "text", "Rank")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_character(self, node_id: str, title: str = "Mira") -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.root / "lore" / f"{node_id}.md",
            {"id": node_id, "title": title, "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

    def _set_file(self) -> Path:
        files = list((self.root / "mutation-sets").glob("*.md"))
        self.assertEqual(len(files), 1)
        return files[0]

    def test_pin_roundtrips_through_metadata(self) -> None:
        self._write_character("mira")
        created = self.client.post(
            "/api/mutation-sets",
            json={
                "title": "Becomes a werewolf",
                "target_entry_type": "lore:character",
                "target_entity": "mira",
                "rows": [{"field": "title", "value": "The Wolf"}],
            },
        ).json()
        self.assertEqual(created["target_entity"], "mira")
        self.assertEqual(
            self.client.get(f"/api/mutation-sets/{created['id']}").json()["target_entity"], "mira"
        )
        self.assertEqual(
            self.client.get("/api/mutation-sets").json()["entries"][0]["target_entity"], "mira"
        )
        # The pin lives in `metadata`; rows/target stay top-level.
        text = self._set_file().read_text(encoding="utf-8")
        self.assertIn("target_entity: mira", text)
        self.assertIn("target_entry_type: lore:character", text)

    def test_reusable_set_writes_no_metadata_block(self) -> None:
        created = self.client.post(
            "/api/mutation-sets",
            json={
                "title": "Any promotion",
                "target_entry_type": "lore:character",
                "rows": [{"field": "rank", "value": "Captain"}],
            },
        ).json()
        self.assertEqual(created["target_entity"], "")
        # omit_empty_metadata keeps an un-pinned set's file free of a metadata block.
        self.assertNotIn("metadata:", self._set_file().read_text(encoding="utf-8"))

    def test_pin_emits_a_set_to_subject_reverse_edge(self) -> None:
        self._write_character("mira")
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Werewolf",
                target_entry_type="lore:character",
                target_entity="mira",
                rows=[MutationSetRow(field="title", value="The Wolf")],
            )
        )
        reverse = self.service._build_node_index().edges_by_dst.get("mira", [])
        self.assertIn(created.id, [edge.src for edge in reverse])
        self.assertIn("target_entity", [edge.field_id for edge in reverse])

    def test_deleting_the_pinned_entity_deletes_the_set(self) -> None:
        self._write_character("mira")
        created = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Werewolf",
                target_entry_type="lore:character",
                target_entity="mira",
                rows=[MutationSetRow(field="title", value="The Wolf")],
            )
        )
        set_path = self._set_file()
        self.assertIn("target_entity: mira", set_path.read_text(encoding="utf-8"))

        self.service.delete_lore_entry("mira")

        # ADR-0095 §9: the set is DELETED with its pin — this replaces
        # ADR-0055 §3's purge of the pin, which would have turned an active
        # set into an unpinned template instead.
        with self.assertRaises(ProjectServiceError):
            self.service.read_mutation_set_entry(created.id)
        self.assertFalse(set_path.exists())


class MutationSetStateTests(unittest.TestCase):
    """ADR-0095 §2: state and anchors are READ from the scenes that anchor a
    set, never stored. Template (no pin) / staged (pin, no anchors) / active
    (pin, ≥1 anchor) — including a scene that is NOT in the manuscript tree."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "State Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_character(self, node_id: str, title: str = "Mira") -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.root / "lore" / f"{node_id}.md",
            {"id": node_id, "title": title, "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

    def _create_pinned(self, target_entity: str = "") -> str:
        return self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Becomes a werewolf",
                target_entry_type="lore:character",
                target_entity=target_entity,
                rows=[MutationSetRow(field="title", value="The Wolf")],
            )
        ).id

    def _write_out_of_tree_scene(self, scene_id: str, title: str, body: str) -> None:
        # Deliberately NOT `create_scene` — that always places the scene into
        # the manuscript tree. A raw file with no `parent`/`rank` in front
        # matter is a real kind="manuscript" index entry that is simply not
        # linked into the tree (ADR-0095 §2).
        (self.root / "scenes").mkdir(parents=True, exist_ok=True)
        self.service._write_scene_file(
            self.root / "scenes" / f"{scene_id}.md",
            Scene(id=scene_id, title=title, body=body, revision="", entry_type="manuscript:scene"),
        )

    def test_no_pin_is_template(self) -> None:
        set_id = self._create_pinned("")
        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.state, "template")
        self.assertEqual(entry.anchors, [])

    def test_pin_no_anchor_is_staged(self) -> None:
        self._write_character("mira")
        set_id = self._create_pinned("mira")
        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.state, "staged")
        self.assertEqual(entry.anchors, [])

    def test_pin_with_anchor_is_active(self) -> None:
        self._write_character("mira")
        set_id = self._create_pinned("mira")
        scene = self.service.create_scene(CreateSceneRequest(title="Chapter One"))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title="Chapter One", body=render_anchor(set_id, "anchor1")),
        )
        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.state, "active")
        self.assertEqual(len(entry.anchors), 1)
        self.assertEqual(entry.anchors[0].anchor_id, "anchor1")
        self.assertEqual(entry.anchors[0].scene_id, scene.id)

    def test_anchor_in_a_scene_out_of_the_tree_still_makes_it_active(self) -> None:
        self._write_character("mira")
        set_id = self._create_pinned("mira")
        self._write_out_of_tree_scene("manuscript_orphan", "Orphan Scene", render_anchor(set_id, "anchor1"))

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.state, "active")
        self.assertEqual(entry.anchors[0].scene_id, "manuscript_orphan")

    def test_pin_missing_when_pinned_entity_no_longer_exists(self) -> None:
        set_id = self._create_pinned("ghost")
        entry = self.service.read_mutation_set_entry(set_id)
        self.assertTrue(entry.pin_missing)
        self.assertEqual(entry.state, "staged")

    def test_anchors_by_set_cache_rereads_a_changed_scene(self) -> None:
        self._write_character("mira")
        set_id = self._create_pinned("mira")
        scene = self.service.create_scene(CreateSceneRequest(title="Chapter One"))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title="Chapter One", body=render_anchor(set_id, "anchor1")),
        )
        first = self.service.anchors_by_set()
        self.assertEqual(len(first.get(set_id, [])), 1)

        # Change the scene body (a second anchor, same open scrubbed set): the
        # cache keys on (path, revision), so the changed file is re-read.
        other_id = self._create_pinned("mira")
        current = self.service.read_scene(scene.id)
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(
                title="Chapter One",
                body=render_anchor(set_id, "anchor1") + render_anchor(other_id, "anchor2"),
                base_revision=current.revision,
            ),
        )
        second = self.service.anchors_by_set()
        self.assertEqual(len(second.get(set_id, [])), 1)
        self.assertEqual(len(second.get(other_id, [])), 1)

    def test_anchors_by_set_omits_an_anchor_with_an_empty_set_id(self) -> None:
        # A pill whose copy is in flight or failed serializes with no set id
        # yet (`<!-- mutate:set=;id=... -->`, review fix #2236) — it
        # contributes nothing to `anchors_by_set`.
        scene = self.service.create_scene(CreateSceneRequest(title="Chapter One"))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title="Chapter One", body=render_anchor("", "anchor1")),
        )
        by_set = self.service.anchors_by_set()
        self.assertNotIn("", by_set)
        self.assertNotIn("anchor1", [a.anchor_id for anchors in by_set.values() for a in anchors])


class MutationSetCopyTests(unittest.TestCase):
    """ADR-0095 §6: copying a set into the open project — row ids kept,
    re-pinnable, invalid rows dropped and reported."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Copy Tests")
        _define_field(self.service, "rank", "text", "Rank")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_character(self, node_id: str, title: str = "Mira") -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.root / "lore" / f"{node_id}.md",
            {"id": node_id, "title": title, "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

    def test_copy_keeps_row_ids_and_repins(self) -> None:
        self._write_character("mira")
        self._write_character("nan", "Nan")
        source = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Werewolf",
                target_entry_type="lore:character",
                target_entity="mira",
                rows=[MutationSetRow(field="rank", op="replace", value="Captain")],
            )
        )
        result = self.service.copy_mutation_set_entry(
            source.id, CopyMutationSetRequest(target_entity="nan")
        )
        self.assertNotEqual(result.entry.id, source.id)
        self.assertEqual(result.entry.target_entity, "nan")
        self.assertEqual(result.entry.rows[0].id, source.rows[0].id)
        self.assertEqual(result.dropped_rows, [])
        # The copy lands in the open project as its own file.
        path = self.root / "mutation-sets" / f"{result.entry.id}.md"
        self.assertTrue(path.exists())

    def test_copy_drops_a_row_invalid_for_the_new_pin(self) -> None:
        self._write_character("mira")
        self._write_character("place", "Ruins")
        self.service.save_lore_entry(
            "place",
            SaveLoreEntryRequest(title="Ruins", body="", entry_type="lore:location", metadata={}),
        )
        source = self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Werewolf",
                target_entry_type="lore:character",
                target_entity="mira",
                rows=[MutationSetRow(field="rank", op="replace", value="Captain")],
            )
        )
        # Re-pin to a location: "rank" is not a defined field there.
        result = self.service.copy_mutation_set_entry(
            source.id, CopyMutationSetRequest(target_entity="place")
        )
        self.assertEqual(result.entry.rows, [])
        self.assertEqual(len(result.dropped_rows), 1)
        self.assertEqual(result.dropped_rows[0].field, "rank")

    def test_copy_from_an_ancestor_layer_lands_in_the_open_project(self) -> None:
        base = Path(self.temp_dir.name).resolve() / "writing"
        universe = base / "honorverse"
        series = universe / "honor-harrington"
        book_root = series / "book01"
        service = ProjectService.created_at(book_root, "Book 1")
        config_dir = Path(self.temp_dir.name).resolve() / "config"
        config_dir.mkdir()
        with patch(
            "app.services.machine_settings.config_path",
            return_value=config_dir / "config.yaml",
        ):
            declare_full_chain(service, book_root, base)
            (universe / "lore").mkdir(parents=True, exist_ok=True)
            service._write_node_entry_file(
                universe / "lore" / "alice.md", "alice", "Alice", "lore:character", {}, ""
            )
            (universe / "mutation-sets").mkdir(parents=True, exist_ok=True)
            service._write_node_entry_file(
                universe / "mutation-sets" / "ancestor_set.md",
                "ancestor_set",
                "Ancestor Set",
                "mutation_set:mutation_set",
                {"target_entity": "alice"},
                "",
                extra={
                    "target_entry_type": "lore:character",
                    "rows": [{"field": "title", "op": "replace", "value": "Changed", "id": "r1"}],
                },
                omit_empty_metadata=True,
            )

            result = service.copy_mutation_set_entry(
                "ancestor_set", CopyMutationSetRequest(target_entity="alice")
            )
            self.assertNotEqual(result.entry.id, "ancestor_set")
            self.assertEqual(result.entry.rows[0].id, "r1")
            path = book_root / "mutation-sets" / f"{result.entry.id}.md"
            self.assertTrue(path.exists())


class OverrideRowIdTests(unittest.TestCase):
    """ADR-0095 §3: an override row never persists `id` — nothing addresses
    one, and a lore save regenerates the whole set from a fresh diff."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_override_file_has_no_row_id_key(self) -> None:
        base = Path(self.temp_dir.name).resolve() / "writing"
        root = base / "honorverse" / "honor-harrington" / "book01"
        # Declare the chain BEFORE the first index build (mirrors
        # `test_layer_overrides.py`) — declaring it after `open_test_project`
        # has already scaffolded and cached an index for `root` would leave
        # that cache stale, with no ancestor layers in it.
        self.service = ProjectService.created_at(root, "Book 1")
        config_dir = Path(self.temp_dir.name).resolve() / "config"
        config_dir.mkdir()
        with patch(
            "app.services.machine_settings.config_path",
            return_value=config_dir / "config.yaml",
        ):
            declare_full_chain(self.service, root, base)
            (base / "lore").mkdir(parents=True, exist_ok=True)
            self.service._write_node_entry_file(
                base / "lore" / "alice.md", "alice", "Alice", "lore:character", {}, ""
            )
            self.service.save_lore_entry(
                "alice",
                SaveLoreEntryRequest(
                    title="Alicia",
                    body="",
                    entry_type="lore:character",
                    metadata={},
                    authoring_layer_id=self.service._metadata_schema_layer_id(root),
                ),
            )
            override_files = list((root / "overrides").glob("*.md"))
            self.assertEqual(len(override_files), 1)
            front_matter = self.service._read_front_matter_only(override_files[0], strict=True)
            rows = front_matter.get("rows") or []
            self.assertTrue(rows)
            self.assertTrue(all("id" not in row for row in rows))


if __name__ == "__main__":
    unittest.main()
