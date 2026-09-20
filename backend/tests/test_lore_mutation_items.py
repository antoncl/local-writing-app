"""ADR-0089 slice S1 (#2070) — relationship items follow the mutation rules.

A group-shaped list whose item group has exactly one `entity_ref` member is a
reference-keyed list: the member is the item's key, one item per target. Its
items are mutated with the ordinary marker grammar in three record shapes —
`add` (the whole item, JSON), `replace` on `<field>.<target id>.<member>`, and
`remove` (the target id) — and resolve positionally per key. These pin the
journey steps the ADR names as done (2, 5, 6, 7), the validator's advisory
findings, the write-side uniqueness rule, and the widened `effective_state`
contract (a list field resolves to its items).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.models.schema import GroupMember, MetadataFieldDefinition
from app.services.project.errors import ProjectServiceError
from app.services.project.lore_mutation_items import (
    decode_item,
    encode_item,
    fold_keyed_items,
    keyed_lists_from,
    split_member_path,
)
from app.services.project.metadata_refs import (
    dedupe_keyed_items,
    duplicate_item_keys,
    keyed_list_key,
)

FIELD = "relationships"


class _RelationshipFixture(unittest.TestCase):
    """Mara with a base relationship to Tomas (kinship, estranged) and to Ilse
    (debt, owed); Peter exists but holds no base item. Scenes are created per
    test, in chapter order, so manuscript order follows creation order."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Relationship Items")
        self._add_relationships_field()
        self.tomas = self._character("Tomas Vell")
        self.ilse = self._character("Ilse")
        self.peter = self._character("Peter")
        self.mara = self._character("Mara")
        self.base = [
            {"to": self.tomas, "kind": "kinship", "state": "estranged", "weight": 1},
            {"to": self.ilse, "kind": "debt", "state": "owed", "weight": 2},
        ]
        self._save_mara(self.base)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _add_relationships_field(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("groups", {})["relationship"] = {
            "name": "Relationship",
            "members": [
                {"key": "to", "name": "Who", "type": "entity_ref"},
                {"key": "kind", "name": "Kind", "type": "text"},
                {"key": "state", "name": "State", "type": "text"},
                {"key": "weight", "name": "Weight", "type": "number"},
            ],
        }
        data.setdefault("fields", {})[FIELD] = {
            "name": "Relationships",
            "type": "list",
            "item_group": "relationship",
        }
        character = data["entry_types"].get("lore:character") or {}
        own = list(character.get("fields") or [])
        if FIELD not in own:
            own.insert(0, FIELD)
        character["fields"] = own
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def _character(self, title: str) -> str:
        return self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        ).id

    def _save_mara(self, items: list[dict]) -> None:
        current = self.service.read_lore_entry(self.mara)
        self.service.save_lore_entry(
            self.mara,
            SaveLoreEntryRequest(
                title="Mara",
                body="",
                entry_type="lore:character",
                base_revision=current.revision,
                metadata={FIELD: items},
            ),
        )

    def _new_scene(self, title: str, body: str) -> str:
        created = self.client.post("/api/scenes", json={"title": title})
        self.assertEqual(created.status_code, 200, created.text)
        scene_id = created.json()["id"]
        saved = self.client.put(f"/api/scenes/{scene_id}", json={"title": title, "body": body})
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    def _marker(self, field: str, op: str, value: str, mid: str) -> str:
        return (
            f"<!-- mutate:entity={self.mara};field={field};op={op};"
            f"value={quote(value, safe='')};id={mid} -->"
        )

    def _add(self, item: dict, mid: str) -> str:
        return self._marker(FIELD, "add", encode_item(item), mid)

    def _remove(self, target: str, mid: str) -> str:
        return self._marker(FIELD, "remove", target, mid)

    def _replace(self, target: str, member: str, value: str, mid: str) -> str:
        return self._marker(f"{FIELD}.{target}.{member}", "replace", value, mid)

    @staticmethod
    def _close(ref: str, mid: str) -> str:
        return f"<!-- mutate:close;ref={ref};id={mid} -->"

    def _items(self, scene_id: str, position: int | None = None) -> list | None:
        state = self.service.effective_state(self.mara, scene_id, position)
        return state.get(FIELD)

    def _item(self, items: list | None, target: str) -> dict | None:
        return next((item for item in items or [] if item.get("to") == target), None)

    def _warnings(self) -> list[str]:
        # Only the mutation findings — validate_project also carries the
        # machine-settings notice on a test box with no projects folder.
        return [w for w in self.service.validate_project().warnings if " mutation of " in w]


class ResolutionTests(_RelationshipFixture):
    def test_member_replace_changes_one_member_from_that_point(self) -> None:
        ch3 = self._new_scene("Chapter 3", "Cold words.")
        ch12 = self._new_scene("Chapter 12", f"They talked. {self._replace(self.tomas, 'state', 'reconciled', 'r12')}")
        ch14 = self._new_scene("Chapter 14", "Later.")
        self.assertNotIn(FIELD, self.service.effective_state(self.mara, ch3))
        for scene in (ch12, ch14):
            items = self._items(scene)
            self.assertEqual(
                self._item(items, self.tomas),
                {"to": self.tomas, "kind": "kinship", "state": "reconciled", "weight": 1},
            )
            # The other item rides through untouched, in base order.
            self.assertEqual(items[1], self.base[1])

    def test_close_reverts_the_member(self) -> None:
        # Journey 5: the Chapter 12 change holds until the Chapter 19 close.
        ch12 = self._new_scene("Chapter 12", self._replace(self.tomas, "state", "reconciled", "r12"))
        ch14 = self._new_scene("Chapter 14", "Held.")
        ch19 = self._new_scene("Chapter 19", f"The Weir. {self._close('r12', 'c19')}")
        self.assertEqual(self._item(self._items(ch14), self.tomas)["state"], "reconciled")
        self.assertNotIn(FIELD, self.service.effective_state(self.mara, ch19))
        self.assertEqual(self._item(self._items(ch12), self.tomas)["state"], "reconciled")

    def test_add_remove_add_is_a_fresh_item(self) -> None:
        # Journey 6: a member change before the remove does not survive the re-add.
        ch3 = self._new_scene("Chapter 3", self._replace(self.ilse, "state", "settled", "r3"))
        ch5 = self._new_scene("Chapter 5", f"Forgotten. {self._remove(self.ilse, 'x5')}")
        ch7 = self._new_scene("Chapter 7", "Quiet.")
        ch9 = self._new_scene(
            "Chapter 9",
            self._add({"to": self.ilse, "kind": "rivalry", "state": "rival once more"}, "a9"),
        )
        ch14 = self._new_scene("Chapter 14", "Later.")
        self.assertEqual(self._item(self._items(ch3), self.ilse)["state"], "settled")
        self.assertIsNone(self._item(self._items(ch5), self.ilse))
        self.assertIsNone(self._item(self._items(ch7), self.ilse))
        for scene in (ch9, ch14):
            self.assertEqual(
                self._item(self._items(scene), self.ilse),
                {"to": self.ilse, "kind": "rivalry", "state": "rival once more"},
            )
        # The other item is untouched throughout.
        self.assertEqual(self._item(self._items(ch14), self.tomas), self.base[0])

    def test_a_position_before_an_add_in_the_same_scene_lacks_the_item(self) -> None:
        # Journey 7: the dialog's baseline is its own insertion position.
        prefix = "She met him at the gate. "
        scene = self._new_scene(
            "Chapter 9", f"{prefix}{self._add({'to': self.peter, 'kind': 'witness'}, 'a9')} After."
        )
        self.assertIsNone(self._item(self._items(scene, position=len(prefix) - 1), self.peter))
        self.assertIsNotNone(self._item(self._items(scene, position=len(prefix)), self.peter))
        self.assertIsNotNone(self._item(self._items(scene), self.peter))

    def test_a_closed_remove_brings_the_base_item_back(self) -> None:
        ch5 = self._new_scene("Chapter 5", self._remove(self.ilse, "x5"))
        ch7 = self._new_scene("Chapter 7", self._close("x5", "c7"))
        self.assertIsNone(self._item(self._items(ch5), self.ilse))
        self.assertNotIn(FIELD, self.service.effective_state(self.mara, ch7))

    def test_member_values_coerce_to_the_member_type(self) -> None:
        ch3 = self._new_scene("Chapter 3", self._replace(self.tomas, "weight", "7", "r3"))
        self.assertEqual(self._item(self._items(ch3), self.tomas)["weight"], 7)

    def test_a_replace_before_its_add_does_not_apply(self) -> None:
        ch3 = self._new_scene("Chapter 3", self._replace(self.peter, "state", "early", "r3"))
        ch9 = self._new_scene("Chapter 9", self._add({"to": self.peter, "kind": "witness"}, "a9"))
        self.assertIsNone(self._item(self._items(ch3), self.peter))
        self.assertEqual(self._item(self._items(ch9), self.peter), {"to": self.peter, "kind": "witness"})

    def test_whole_list_replace_is_ignored(self) -> None:
        ch3 = self._new_scene("Chapter 3", self._marker(FIELD, "replace", "anything", "w3"))
        self.assertEqual(self._items(ch3), self.base)

    def test_the_key_member_never_changes(self) -> None:
        ch3 = self._new_scene("Chapter 3", self._replace(self.tomas, "to", self.peter, "r3"))
        self.assertEqual(self._items(ch3), self.base)

    def test_route_returns_the_folded_items(self) -> None:
        ch12 = self._new_scene("Chapter 12", self._replace(self.tomas, "state", "reconciled", "r12"))
        response = self.client.get(f"/api/lore/{self.mara}/effective", params={"scene": ch12})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["values"][FIELD]
        self.assertEqual(items[0]["state"], "reconciled")
        self.assertEqual(items[1], self.base[1])


class ValidationTests(_RelationshipFixture):
    """Every finding is advisory (validate_project warnings) — a scene save never
    blocks on a marker, as for every other mutation value."""

    def test_add_validates_the_item_as_a_base_item(self) -> None:
        self._new_scene("Chapter 3", self._add({"to": self.peter, "weight": "heavy"}, "a3"))
        self.assertTrue(any(f"{FIELD}[0].weight" in w for w in self._warnings()), self._warnings())

    def test_add_without_a_key_is_flagged(self) -> None:
        self._new_scene("Chapter 3", self._add({"kind": "witness"}, "a3"))
        self.assertTrue(any("key member to" in w for w in self._warnings()), self._warnings())

    def test_add_of_a_held_key_is_flagged(self) -> None:
        self._new_scene("Chapter 3", self._add({"to": self.tomas, "kind": "rivalry"}, "a3"))
        self.assertTrue(any("already holds an item" in w for w in self._warnings()), self._warnings())

    def test_add_after_a_remove_is_clean(self) -> None:
        self._new_scene("Chapter 5", self._remove(self.ilse, "x5"))
        self._new_scene("Chapter 9", self._add({"to": self.ilse, "kind": "rivalry"}, "a9"))
        self.assertEqual(self._warnings(), [])

    def test_remove_of_an_absent_key_is_flagged(self) -> None:
        self._new_scene("Chapter 3", self._remove(self.peter, "x3"))
        self.assertTrue(any("names no item" in w for w in self._warnings()), self._warnings())

    def test_replace_before_its_add_is_dangling(self) -> None:
        self._new_scene("Chapter 3", self._replace(self.peter, "state", "early", "r3"))
        self._new_scene("Chapter 9", self._add({"to": self.peter, "kind": "witness"}, "a9"))
        warnings = self._warnings()
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("names no item", warnings[0])

    def test_whole_list_replace_is_flagged(self) -> None:
        self._new_scene("Chapter 3", self._marker(FIELD, "replace", "anything", "w3"))
        self.assertTrue(any("whole-list replace" in w for w in self._warnings()), self._warnings())

    def test_key_member_replace_is_flagged(self) -> None:
        self._new_scene("Chapter 3", self._replace(self.tomas, "to", self.peter, "r3"))
        self.assertTrue(any("never changes" in w for w in self._warnings()), self._warnings())

    def test_member_value_is_validated_as_the_member_type(self) -> None:
        self._new_scene("Chapter 3", self._replace(self.tomas, "weight", "heavy", "r3"))
        warnings = self._warnings()
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(f"{FIELD}.{self.tomas}.weight", warnings[0])
        self.assertNotIn("names no item", warnings[0])

    def test_unknown_member_is_flagged(self) -> None:
        self._new_scene("Chapter 3", self._replace(self.tomas, "mood", "x", "r3"))
        self.assertTrue(any("unknown member mood" in w for w in self._warnings()), self._warnings())

    def test_add_on_a_member_path_is_flagged(self) -> None:
        self._new_scene("Chapter 3", self._marker(f"{FIELD}.{self.tomas}.state", "add", "x", "r3"))
        self.assertTrue(any("only replace is" in w for w in self._warnings()), self._warnings())

    def test_a_clean_record_set_has_no_findings(self) -> None:
        self._new_scene("Chapter 12", self._replace(self.tomas, "state", "reconciled", "r12"))
        self._new_scene("Chapter 19", self._close("r12", "c19"))
        self.assertEqual(self._warnings(), [])

    def test_a_unit_that_adds_and_edits_the_same_item_is_clean(self) -> None:
        # Carrier rows share their unit's offset (ADR-0016): the add row counts
        # for the replace row after it, exactly as the resolver applies them.
        item = quote(encode_item({"to": self.peter, "kind": "witness"}), safe="")
        unit = (
            f"<!-- mutate:entity={self.mara};name=Meets;id=u1\n"
            f"field={FIELD};op=add;value={item};id=a1\n"
            f"field={FIELD}.{self.peter}.state;op=replace;value=wary;id=r1\n"
            "-->"
        )
        scene = self._new_scene("Chapter 9", f"At the gate. {unit} After.")
        self.assertEqual(self._warnings(), [])
        self.assertEqual(
            self._item(self._items(scene), self.peter),
            {"to": self.peter, "kind": "witness", "state": "wary"},
        )


class WriteRuleTests(_RelationshipFixture):
    def test_save_refuses_a_second_item_for_the_same_target(self) -> None:
        # Journey 2: one item per target per field.
        with self.assertRaises(ProjectServiceError) as raised:
            self._save_mara([*self.base, {"to": self.tomas, "kind": "rivalry"}])
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("more than one item", raised.exception.message)

    def test_duplicates_on_disk_read_fine_and_are_reported(self) -> None:
        # Tolerated on read, warned by project validation, first wins on resolve.
        entry_path = self.service.read_lore_entry(self.mara)
        path = next(p for p in (self.root / "lore").glob("*.md") if self.mara in p.read_text(encoding="utf-8"))
        front_matter, body = self.service._read_markdown_with_front_matter(path, strict=True)
        front_matter["metadata"][FIELD] = [
            {"to": self.tomas, "kind": "kinship", "state": "first"},
            {"to": self.tomas, "kind": "rivalry", "state": "second"},
        ]
        self.service._write_markdown_with_front_matter(path, front_matter, body)
        self.assertEqual(len(self.service.read_lore_entry(self.mara).metadata[FIELD]), 2)
        entry_warnings = self.service.validate_project().warnings
        self.assertTrue(any("more than one item" in w for w in entry_warnings), entry_warnings)
        ch3 = self._new_scene("Chapter 3", self._replace(self.tomas, "state", "changed", "r3"))
        self.assertEqual(
            self._items(ch3), [{"to": self.tomas, "kind": "kinship", "state": "changed"}]
        )
        self.assertEqual(entry_path.id, self.mara)


class ModuleTests(unittest.TestCase):
    """The pure pieces: the shape predicate, the path grammar, the fold."""

    @staticmethod
    def _field(members: list[GroupMember]) -> MetadataFieldDefinition:
        return MetadataFieldDefinition(
            name="Rels", type="list", item_group="rel", item_scalar=False, item_members=members
        )

    def test_keyed_list_key_needs_exactly_one_entity_ref_member(self) -> None:
        who = GroupMember(key="who", name="Who", type="entity_ref")
        kind = GroupMember(key="kind", name="Kind", type="text")
        also = GroupMember(key="also", name="Also", type="entity_ref")
        many = GroupMember(key="many", name="Many", type="entity_ref_list")
        self.assertEqual(keyed_list_key(self._field([who, kind])), "who")
        self.assertEqual(keyed_list_key(self._field([who, many])), "who")
        self.assertIsNone(keyed_list_key(self._field([who, also])))
        self.assertIsNone(keyed_list_key(self._field([many, kind])))
        self.assertIsNone(keyed_list_key(self._field([kind])))
        self.assertIsNone(keyed_list_key(MetadataFieldDefinition(name="Tags", type="entity_ref_list")))
        self.assertIsNone(keyed_list_key(None))

    def test_member_path_splits_on_the_longest_field_prefix(self) -> None:
        schema_fields = {
            "rels": self._field([GroupMember(key="who", name="Who", type="entity_ref")]),
            "rels.x": self._field([GroupMember(key="who", name="Who", type="entity_ref")]),
        }
        keyed = keyed_lists_from(type("S", (), {"fields": schema_fields})())
        self.assertEqual(split_member_path("rels.lore_a.state", keyed)[1:], ("lore_a", "state"))
        self.assertEqual(split_member_path("rels.x.lore_a.state", keyed)[0].field_id, "rels.x")
        self.assertIsNone(split_member_path("rels.lore_a", keyed))
        self.assertIsNone(split_member_path("other.lore_a.state", keyed))
        self.assertIsNone(split_member_path("rels", keyed))

    def test_item_encoding_round_trips_and_is_stable(self) -> None:
        item = {"who": "lore_a", "kind": "ally", "weight": 2}
        self.assertEqual(decode_item(encode_item(item)), item)
        self.assertEqual(encode_item(item), encode_item({"weight": 2, "kind": "ally", "who": "lore_a"}))
        self.assertIsNone(decode_item("[1, 2]"))
        self.assertIsNone(decode_item("not json"))

    def test_duplicates_and_first_wins(self) -> None:
        items = [{"who": "a", "n": 1}, {"who": "b"}, {"who": "a", "n": 2}, {"n": 3}, {"who": ""}]
        self.assertEqual(duplicate_item_keys(items, "who"), ["a"])
        self.assertEqual(
            dedupe_keyed_items(items, "who"), [{"who": "a", "n": 1}, {"who": "b"}, {"n": 3}, {"who": ""}]
        )

    def test_fold_matches_keys_through_canonical(self) -> None:
        from types import SimpleNamespace

        keyed = keyed_lists_from(
            type("S", (), {"fields": {"rels": self._field([
                GroupMember(key="who", name="Who", type="entity_ref"),
                GroupMember(key="n", name="N", type="number"),
            ])}})()
        )["rels"]
        marker = SimpleNamespace(op="replace", value="5", scene_id="s", offset=0)
        from app.services.project.lore_mutation_items import member_record

        folded = fold_keyed_items(
            [{"who": "old_b", "n": 1}, {"who": "a", "n": 2}],
            keyed,
            [member_record(marker, "old_b", "n")],
            coerce=lambda value, _type: int(value),
            canonical=lambda key: "a" if key == "old_b" else key,
        )
        # Both base items collapse onto `a` (first wins) and the record, written
        # against the merged-away id, still finds the item.
        self.assertEqual(folded, [{"who": "a", "n": 5}])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
