from __future__ import annotations

from metadata_validation_base import MetadataValidationBase

from app.models import (
    CreateLoreEntryRequest,
    MetadataSchema,
    SaveLoreEntryRequest,
)
from app.services.project.errors import ProjectServiceError


class RequiredSelectTests(MetadataValidationBase):
    """A select that declares a `default` is "required" (#1421): it seeds nothing
    to disk (front matter stays sparse), an absent value resolves to the default at
    evaluation, and an explicit blank is rejected on save. `context_policy` — a
    built-in select on lore:base with default "auto" — is the first field."""

    def _hero(self):
        return self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )

    def test_new_lore_entry_omits_context_policy_from_front_matter(self) -> None:
        # A required select is NOT seeded to disk — the front matter stays sparse.
        self.assertNotIn("context_policy", self._hero().metadata)

    def test_context_policy_declares_the_auto_default_with_labels(self) -> None:
        field = self.service.read_metadata_schema().fields["context_policy"]
        self.assertEqual(field.default, "auto")
        labels = {opt.value: opt.label for opt in field.options}
        self.assertEqual(labels["auto"], "Automatic (alias match)")
        self.assertEqual(labels["never"], "Never include")

    def test_blank_context_policy_is_rejected_on_save(self) -> None:
        hero = self._hero()
        with self.assertRaisesRegex(ProjectServiceError, "context_policy is required"):
            self.service.save_lore_entry(
                hero.id,
                SaveLoreEntryRequest(
                    title=hero.title,
                    body=hero.body,
                    base_revision=hero.revision,
                    entry_type="lore:character",
                    metadata={"context_policy": ""},
                ),
            )

    def test_valid_context_policy_saves_and_stays_explicit(self) -> None:
        hero = self._hero()
        self.service.save_lore_entry(
            hero.id,
            SaveLoreEntryRequest(
                title=hero.title,
                body=hero.body,
                base_revision=hero.revision,
                entry_type="lore:character",
                metadata={"context_policy": "always"},
            ),
        )
        self.assertEqual(
            self.service.read_lore_entry(hero.id).metadata.get("context_policy"), "always"
        )

    def test_non_select_defaults_are_still_seeded(self) -> None:
        # The seeder skip is scoped to selects: a boolean default still seeds, an
        # optional select (no default) is absent anyway, and the required select is
        # not written.
        self._add_clearable_fields(self.root, "lore:character")
        hero = self._hero()
        self.assertEqual(hero.metadata.get("flagged"), True)  # boolean default seeded
        self.assertNotIn("tier", hero.metadata)  # optional select: never seeded
        self.assertNotIn("context_policy", hero.metadata)  # required select: not seeded

    def test_new_scene_still_opens_at_draft(self) -> None:
        # Scene `status` is a top-level select with a default; the seeder-skip must
        # not regress its create default (now read from the schema directly).
        self.assertEqual(self.service.create_scene(self._make_create_scene("New")).status, "draft")

    def test_select_default_must_name_a_real_option(self) -> None:
        # Schema-integrity guard: a required select whose default isn't an option
        # would resolve every entry to a value the field can never legally hold.
        schema = MetadataSchema.model_validate(
            {
                "entry_types": {"lore:base": {"name": "Lore", "kind": "lore"}},
                "fields": {
                    "mood": {
                        "name": "Mood",
                        "type": "select",
                        "options": [{"value": "calm"}, {"value": "tense"}],
                        "default": "frantic",
                    },
                },
            }
        )
        errors = self.service._validate_metadata_schema_definition(schema)
        self.assertTrue(
            any("mood" in e and "not one of its options" in e for e in errors),
            errors,
        )
