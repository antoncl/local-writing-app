"""A select's derived state is a FIELD-level declaration (#1911).

`derived: {value, when_set}` on a select says the app holds `value` on a node
whenever the reference field `when_set` is set, and clears a stale `value`
when it is not. One declaration drives the read/save select canon
(`_canonicalise_metadata_selects`), the rail's pick list and the type editor — the
built-in `page_status` ← `scene` rule (exercised end-to-end by test_plot /
test_plot_card_links) and a user's own field are the same case.
"""

from __future__ import annotations

from metadata_validation_base import MetadataValidationBase

from app.models import (
    CreateCardRequest,
    CreateLoreEntryRequest,
    DerivedSelectState,
    LoreEntry,
    MetadataSchema,
    SaveLoreEntryRequest,
)


class DerivedSelectStateTests(MetadataValidationBase):
    def _declare_filmed(self) -> None:
        """A user-authored rule on lore:character: `filmed` is `filmed` while
        `footage` (a reference) is set — the how-to's worked example."""
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        fields = data.setdefault("fields", {})
        fields["footage"] = {"name": "Footage", "type": "entity_ref"}
        fields["filmed"] = {
            "name": "Filmed",
            "type": "select",
            "options": ["planned", "filmed", "scrapped"],
            "default": "planned",
            "derived": {"value": "filmed", "when_set": "footage"},
        }
        tdef = data["entry_types"].get("lore:character") or {}
        tdef["fields"] = [*(tdef.get("fields") or []), "footage", "filmed"]
        data["entry_types"]["lore:character"] = tdef
        self.service._write_yaml(schema_path, data)

    def _character(self, title: str) -> LoreEntry:
        return self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type="lore:character"))

    def _save(self, entry: LoreEntry, metadata: dict) -> LoreEntry:
        return self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=entry.body,
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata=metadata,
            ),
        )

    def test_the_state_is_held_while_the_reference_is_set(self) -> None:
        self._declare_filmed()
        reel = self._character("Reel")
        hero = self._character("Seren")
        saved = self._save(hero, {"footage": reel.id})
        self.assertEqual(saved.metadata.get("filmed"), "filmed")
        self.assertEqual(self.service.read_lore_entry(hero.id).metadata.get("filmed"), "filmed")

    def test_the_reference_overrides_an_authored_value(self) -> None:
        self._declare_filmed()
        reel = self._character("Reel")
        hero = self._character("Seren")
        saved = self._save(hero, {"footage": reel.id, "filmed": "scrapped"})
        self.assertEqual(saved.metadata.get("filmed"), "filmed")

    def test_a_stale_state_is_cleared_when_the_reference_is_gone(self) -> None:
        # Without the reference the state falls back to the default — sparse,
        # like a fresh node (the rail shows "planned", no reset chip).
        self._declare_filmed()
        hero = self._character("Seren")
        saved = self._save(hero, {"filmed": "filmed"})
        self.assertNotIn("filmed", saved.metadata)
        self.assertNotIn("filmed", self.service.read_lore_entry(hero.id).metadata)

    def test_an_authored_value_stands_without_the_reference(self) -> None:
        self._declare_filmed()
        hero = self._character("Seren")
        self.assertEqual(self._save(hero, {"filmed": "scrapped"}).metadata.get("filmed"), "scrapped")

    def test_a_declaration_the_validator_only_reports_derives_nothing(self) -> None:
        # A hand-edited layer naming a value outside the options stays readable
        # (the validator is soft) — and the canon must not write a value the
        # field's own validation would then reject on every read.
        self._declare_filmed()
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["filmed"]["derived"] = {"value": "flimed", "when_set": "footage"}
        self.service._write_yaml(schema_path, data)
        reel = self._character("Reel")
        hero = self._character("Seren")
        saved = self._save(hero, {"footage": reel.id, "filmed": "scrapped"})
        self.assertEqual(saved.metadata.get("filmed"), "scrapped")
        self.assertEqual(self.service.read_lore_entry(hero.id).metadata.get("filmed"), "scrapped")

    def test_the_rule_is_inert_on_a_type_that_does_not_carry_the_reference(self) -> None:
        # `filmed` on a type without `footage`: nothing can ever set the state,
        # so an authored value stands rather than being popped on every read —
        # and the validator names the gap.
        self._declare_filmed()
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        tdef = data["entry_types"].get("lore:location") or {}
        tdef["fields"] = [*(tdef.get("fields") or []), "filmed"]
        data["entry_types"]["lore:location"] = tdef
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(any("lore:location" in e and "footage" in e for e in errors), errors)
        place = self.service.create_lore_entry(CreateLoreEntryRequest(title="Set", entry_type="lore:location"))
        saved = self.service.save_lore_entry(
            place.id,
            SaveLoreEntryRequest(
                title=place.title,
                body=place.body,
                base_revision=place.revision,
                entry_type="lore:location",
                metadata={"filmed": "filmed"},
            ),
        )
        self.assertEqual(saved.metadata.get("filmed"), "filmed")

    def test_the_file_lands_canonical_on_save(self) -> None:
        # The select canon rides the write seam, not only the read: the front
        # matter itself holds the derived state and never the literal default.
        self._declare_filmed()
        reel = self._character("Reel")
        hero = self._character("Seren")
        self._save(hero, {"footage": reel.id, "filmed": "scrapped", "context_policy": "auto"})
        stored = self.service._read_front_matter_only(self.service._path_for_node_id(hero.id, "lore"), strict=True)
        self.assertEqual(stored["metadata"].get("filmed"), "filmed")
        self.assertNotIn("context_policy", stored["metadata"])

    def test_the_card_list_reads_the_same_canon_as_a_single_read(self) -> None:
        # A listed card with a stale `on_page` beside no scene (a purge, an
        # import) projects as unwritten — the list heals like the rail's read.
        card = self.service.create_card(CreateCardRequest(title="Beat"))
        path = self.service._path_for_node_id(card.id, "plot")
        front_matter, body = self.service._read_markdown_with_front_matter(path, strict=True)
        front_matter["metadata"] = {"page_status": "on_page"}
        self.service._write_markdown_with_front_matter(path, front_matter, body)
        listed = next(c for c in self.service.list_cards().entries if c.id == card.id)
        self.assertNotIn("page_status", listed.metadata)

    def test_a_layer_relabelling_the_options_keeps_the_ancestor_declaration(self) -> None:
        # Field definitions merge per attribute up the chain: a layer that only
        # renames the built-in page_status options still derives on_page from
        # the scene — and the rail never offers it there either.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["page_status"] = {
            "options": [
                {"value": "unwritten", "label": "Not yet"},
                {"value": "off_page", "label": "Off"},
                {"value": "on_page", "label": "On"},
            ],
        }
        self.service._write_yaml(schema_path, data)
        field = self.service.read_metadata_schema().fields["page_status"]
        self.assertEqual(field.derived, DerivedSelectState(value="on_page", when_set="scene"))
        self.assertEqual([option.label for option in field.options], ["Not yet", "Off", "On"])
        self.assertEqual(field.default, "unwritten")

    def test_declaration_errors_are_reported_softly(self) -> None:
        # Like a select default that names no option: the layer stays readable
        # and the save path surfaces the errors.
        schema = MetadataSchema.model_validate(
            {
                "entry_types": {"lore:base": {"name": "Lore", "kind": "lore"}},
                "fields": {
                    "rank": {"name": "Rank", "type": "text"},
                    "ally": {"name": "Ally", "type": "entity_ref"},
                    "mood": {"name": "Mood", "type": "text", "derived": {"value": "x", "when_set": "ally"}},
                    "grade": {
                        "name": "Grade",
                        "type": "select",
                        "options": [{"value": "a"}, {"value": "b"}],
                        "derived": {"value": "c", "when_set": "ally"},
                    },
                    "tier": {
                        "name": "Tier",
                        "type": "select",
                        "options": [{"value": "a"}, {"value": "b"}],
                        "default": "b",
                        "derived": {"value": "b", "when_set": "rank"},
                    },
                    "page_status": {
                        "name": "Page status",
                        "type": "select",
                        "options": [{"value": "unwritten"}, {"value": "on_page"}],
                        "derived": {"value": "on_page", "when_set": "ally"},
                    },
                },
            }
        )
        errors = self.service._validate_metadata_schema_definition(schema)
        self.assertTrue(any("mood" in e and "not type select" in e for e in errors), errors)
        self.assertTrue(any("grade" in e and "not one of its options" in e for e in errors), errors)
        self.assertTrue(any("tier" in e and "also its default" in e for e in errors), errors)
        self.assertTrue(any("tier" in e and "not a reference field" in e for e in errors), errors)
        self.assertFalse(any("page_status" in e for e in errors), errors)
