"""ADR-0046 slice 3a — the brainstorm commit's structured patch.

Covers the three new backend pieces:
- `parse_entry_patch_json` — turning a (possibly fenced / prose-wrapped) model
  reply into a patch dict, or flagging it garbled;
- `validate_ai_entry_patch` — validate-on-return: per-field validation against
  the entry_type's schema, dropping the illegal ones without failing the whole
  patch, references / computed always excluded (§4);
- `fields` — the Jinja helper that lists an entry's full field roster (each with
  an advisory `proposable` flag) so the prompt names real field ids.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _builtins import builtin_prompt_id
from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
)
from app.models.schema import MetadataFieldDefinition
from app.services.ai.entry_patch import is_proposable_field, parse_entry_patch_json
from app.services.ai.helpers import (
    _fields,
    _type_name,
    create_environment_for_project,
)
from app.services.machine_settings import palette as machine_palette
from app.services.project.errors import ProjectServiceError


def add_character_patch_fields(service, root: Path) -> None:
    """Add a long_text, a select, a hidden text, and an entity_ref field to
    lore:character — the built-in lore types carry none of the first three.
    Shared by the revise and create (draft) validation suites so both exercise
    the same field shapes."""
    schema_path = root / "metadata.schema.yaml"
    data = service._read_yaml(schema_path)
    fields = data.setdefault("fields", {})
    fields["bio"] = {"name": "Biography", "type": "long_text"}
    fields["allegiance"] = {
        "name": "Allegiance",
        "type": "select",
        "options": ["order", "chaos"],
    }
    # A hidden field: never offered to the AI, dropped if proposed (#2).
    fields["secret_note"] = {"name": "Secret", "type": "text", "hidden": True}
    fields["patron"] = {
        "name": "Patron",
        "type": "entity_ref",
        "target": {"entry_type": "lore:character"},
    }
    character = data["entry_types"].get("lore:character") or {}
    own = list(character.get("fields") or [])
    for field_id in ("bio", "allegiance", "patron", "secret_note"):
        if field_id not in own:
            own.insert(0, field_id)
    character["fields"] = own
    data["entry_types"]["lore:character"] = character
    service._write_yaml(schema_path, data)


class ParseEntryPatchJsonTests(unittest.TestCase):
    """The pure, provider-agnostic parse — tolerant of the ways a model wraps
    JSON, garbled only when there is no JSON object to be found."""

    def test_parses_a_plain_object(self) -> None:
        self.assertEqual(
            parse_entry_patch_json('{"body": "Hi", "fields": {}}'),
            {"body": "Hi", "fields": {}},
        )

    def test_peels_a_json_code_fence(self) -> None:
        raw = '```json\n{"body": "Hi", "fields": {"bio": "x"}}\n```'
        self.assertEqual(
            parse_entry_patch_json(raw), {"body": "Hi", "fields": {"bio": "x"}}
        )

    def test_peels_a_bare_code_fence(self) -> None:
        raw = '```\n{"body": "Hi"}\n```'
        self.assertEqual(parse_entry_patch_json(raw), {"body": "Hi"})

    def test_slices_object_out_of_surrounding_prose(self) -> None:
        raw = 'Sure! Here is the patch:\n{"body": "Hi", "fields": {}}\nHope that helps.'
        self.assertEqual(
            parse_entry_patch_json(raw), {"body": "Hi", "fields": {}}
        )

    def test_garbled_non_json_is_none(self) -> None:
        self.assertIsNone(parse_entry_patch_json("I'm not sure what you mean."))

    def test_a_json_array_is_not_a_patch(self) -> None:
        # Valid JSON, but not an object → not a patch.
        self.assertIsNone(parse_entry_patch_json('["body", "fields"]'))

    def test_empty_reply_is_none(self) -> None:
        self.assertIsNone(parse_entry_patch_json(""))
        self.assertIsNone(parse_entry_patch_json("   \n  "))

    def test_prefers_the_patch_shaped_object_over_an_example(self) -> None:
        # #1036: a chatty reply that shows an example object before the real
        # patch. The naive first-`{`/last-`}` slice spanned both and failed;
        # now the patch-shaped object (has body/fields) wins.
        raw = 'For example {"foo": 1} — here is the patch: {"body": "Hi", "fields": {}}'
        self.assertEqual(parse_entry_patch_json(raw), {"body": "Hi", "fields": {}})

    def test_ignores_stray_braces_in_the_prose(self) -> None:
        raw = 'Use `{placeholder}` syntax. {"fields": {"bio": "x"}}'
        self.assertEqual(parse_entry_patch_json(raw), {"fields": {"bio": "x"}})

    def test_a_brace_inside_a_string_value_does_not_truncate(self) -> None:
        # The scanner is string-aware: the `}` inside the body value doesn't
        # close the object early.
        raw = 'Here: {"body": "a } b { c", "fields": {}}'
        self.assertEqual(
            parse_entry_patch_json(raw), {"body": "a } b { c", "fields": {}}
        )

    def test_recovers_a_fenced_object_amid_prose(self) -> None:
        raw = 'Sure:\n```json\n{"body": "Hi"}\n```\nHope that helps!'
        self.assertEqual(parse_entry_patch_json(raw), {"body": "Hi"})

    def test_bare_empty_object_is_no_changes_not_garble(self) -> None:
        # The contract says reply "{}" for "nothing changed" — a clean object
        # with no body/fields is honored, not treated as garble.
        self.assertEqual(parse_entry_patch_json("{}"), {})

    def test_only_non_patch_objects_in_prose_is_garbled(self) -> None:
        # Objects embedded in prose, none patch-shaped → we can't tell which (if
        # any) is the patch, so it stays garbled rather than silently adopting
        # an arbitrary one as an empty patch.
        self.assertIsNone(parse_entry_patch_json('first {"a": 1} then {"b": 2}'))

    def test_two_patch_shaped_objects_are_ambiguous_and_garbled(self) -> None:
        # #1036: the contract shows the shape, so a chatty model may emit a
        # filled-in example AND the real answer. We can't tell which is which, so
        # it is garbled (the caller's firmer retry then yields a single object)
        # rather than silently adopting the example as the patch.
        raw = (
            'The format is {"body": "example", "fields": {"t": "x"}}. '
            'Applying it: {"body": "Seren is braver.", "fields": {"bravery": "high"}}'
        )
        self.assertIsNone(parse_entry_patch_json(raw))

    def test_prose_wrapped_empty_object_is_no_changes(self) -> None:
        # A bare "{}" wrapped in prose still means "nothing changed", not garble.
        self.assertEqual(parse_entry_patch_json("No changes needed. {}"), {})


class ValidateAiEntryPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "AI Patch Tests")
        self._add_patch_fields_to_character()
        self.hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        # Give bio a starting value so a proposal is a genuine revision.
        self.hero = self.service.save_lore_entry(
            self.hero.id,
            SaveLoreEntryRequest(
                title="Seren",
                body="A wandering knight.",
                base_revision=self.hero.revision,
                entry_type="lore:character",
                metadata={"bio": "Old bio.", "allegiance": "order"},
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _add_patch_fields_to_character(self) -> None:
        add_character_patch_fields(self.service, self.root)

    def test_body_and_long_text_field_kept(self) -> None:
        raw = '{"body": "A knight of renown.", "fields": {"bio": "New bio."}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "A knight of renown.")
        self.assertEqual(patch.fields, {"bio": "New bio."})
        self.assertEqual(patch.dropped, [])

    def test_valid_select_kept(self) -> None:
        raw = '{"fields": {"allegiance": "chaos"}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertEqual(patch.fields, {"allegiance": "chaos"})
        self.assertIsNone(patch.body)

    def test_illegal_select_value_dropped_not_fatal(self) -> None:
        # An out-of-range select is dropped per-field; the valid bio survives,
        # and the whole patch does not fail (ADR §4 / Test surface).
        raw = '{"body": "b", "fields": {"allegiance": "moon", "bio": "kept"}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "b")
        self.assertEqual(patch.fields, {"bio": "kept"})
        self.assertIn("allegiance", patch.dropped)

    def test_reference_field_excluded_even_if_valid(self) -> None:
        # entity_ref is never proposed (§4) — dropped by type, not value.
        raw = f'{{"fields": {{"patron": "{self.hero.id}"}}}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertEqual(patch.fields, {})
        self.assertIn("patron", patch.dropped)

    def test_unknown_field_dropped(self) -> None:
        raw = '{"fields": {"nonesuch": "x"}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertEqual(patch.fields, {})
        self.assertIn("nonesuch", patch.dropped)

    def test_field_not_allowed_for_type_dropped(self) -> None:
        # `status` is a defined field, but a scene field — not on lore:character.
        raw = '{"fields": {"status": "married"}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertEqual(patch.fields, {})
        self.assertIn("status", patch.dropped)

    def test_hidden_field_dropped_even_if_on_type(self) -> None:
        # A hidden field is never proposable (#2): dropped by hiddenness, not by
        # value or type — a stray proposal for it is ignored, never written.
        raw = '{"fields": {"secret_note": "leaked", "bio": "kept"}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertEqual(patch.fields, {"bio": "kept"})
        self.assertIn("secret_note", patch.dropped)

    def test_title_rename_kept(self) -> None:
        # An AI-proposed rename IS proposable and adoptable (title is not in the
        # non-proposable set) — validated like any text field and kept.
        raw = '{"fields": {"title": "Dame Seren"}}'
        patch = self.service.validate_ai_entry_patch(self.hero.id, raw)
        self.assertEqual(patch.fields, {"title": "Dame Seren"})
        self.assertEqual(patch.dropped, [])

    def test_garbled_reply_flagged(self) -> None:
        patch = self.service.validate_ai_entry_patch(
            self.hero.id, "Sorry, I didn't catch that."
        )
        self.assertTrue(patch.garbled)
        self.assertIsNone(patch.body)
        self.assertEqual(patch.fields, {})

    def test_empty_but_valid_patch_is_not_garbled(self) -> None:
        # A parseable object proposing nothing is "no changes", not garble.
        patch = self.service.validate_ai_entry_patch(self.hero.id, '{"fields": {}}')
        self.assertFalse(patch.garbled)
        self.assertIsNone(patch.body)
        self.assertEqual(patch.fields, {})

    def test_fields_lists_full_roster_with_proposable_flag(self) -> None:
        # ADR-0060 §3: `fields()` returns the FULL roster — nothing is pre-filtered.
        # Proposability is an advisory per-descriptor flag the template reads; the
        # roster hides nothing (the old `is_proposable_field` pre-filter is gone).
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, self.hero.id)
        by_id = {f["id"]: f for f in roster}
        # long_text + select are proposable and carry their type / options.
        self.assertEqual(by_id["bio"]["type"], "long_text")
        self.assertTrue(by_id["bio"]["proposable"])
        self.assertEqual(by_id["allegiance"]["type"], "select")
        self.assertEqual(by_id["allegiance"]["options"], ["order", "chaos"])
        self.assertTrue(by_id["allegiance"]["proposable"])
        # `title` IS proposable — an AI rename is adoptable (#4).
        self.assertTrue(by_id["title"]["proposable"])
        # References and hidden fields are now PRESENT in the roster (full list)
        # but flagged not-proposable — the template decides, the list hides nothing.
        self.assertIn("patron", by_id)
        self.assertFalse(by_id["patron"]["proposable"])
        self.assertIn("secret_note", by_id)
        self.assertFalse(by_id["secret_note"]["proposable"])
        # The structural id/entry_type and computed fields are membership fields,
        # so the full roster carries them too — flagged not-proposable.
        self.assertFalse(by_id["id"]["proposable"])
        self.assertFalse(by_id["entry_type"]["proposable"])
        self.assertFalse(by_id["character_cost"]["proposable"])  # computed

    def test_fields_usable_from_jinja(self) -> None:
        # The helper is registered and the for-if filter the template uses works —
        # the template keeps `f.proposable` itself (no engine pre-filter).
        env = create_environment_for_project(self.service)
        rendered = env.from_string(
            "{% for f in fields(inputs.entry) if f.proposable and f.type == 'long_text' %}"
            "{{ f.id }},{% endfor %}"
        ).render(inputs={"entry": self.hero.id})
        self.assertIn("bio", rendered)

    def test_fields_applies_per_type_label_override(self) -> None:
        # #1009: `title` carries a per-type label override — "Name" on lore — so
        # the roster must present the field by the name the author sees, not
        # the shared field def's global "Title". Otherwise the brainstorm prompt
        # tells the model to fill a "Title" when the author is drafting a
        # character/item/location whose field reads "Name".
        schema = self.service.read_metadata_schema()
        self.assertEqual(schema.fields["title"].name, "Title")  # global name is Title
        roster = _fields(self.service, schema, self.hero.id)
        by_id = {f["id"]: f for f in roster}
        self.assertEqual(by_id["title"]["label"], "Name")  # lore override wins

    def test_fields_carries_field_description(self) -> None:
        # #1004: a field's author description rides in the roster so the
        # brainstorm/extraction model sees what the field is FOR. Present as None
        # when unset, so the template can test it without hitting StrictUndefined.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["bio"]["description"] = "The character's backstory in brief."
        self.service._write_yaml(schema_path, data)
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, self.hero.id)
        by_id = {f["id"]: f for f in roster}
        self.assertEqual(by_id["bio"]["description"], "The character's backstory in brief.")
        self.assertIsNone(by_id["allegiance"]["description"])

    def test_fields_carries_builtin_field_descriptions(self) -> None:
        # #1035: the built-in fields a brainstorm actually proposes now ship with
        # descriptions in the default schema, so the model gets real guidance
        # instead of `null` (the cause of the "invent a rationale" nonsense).
        # These are proposable built-ins a character inherits from lore:base;
        # assert their default descriptions reach the roster.
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, self.hero.id)
        by_id = {f["id"]: f for f in roster}
        for fid in ("color", "aliases"):
            self.assertIn(fid, by_id, f"{fid} should be on a character")
            self.assertTrue(by_id[fid]["proposable"], f"{fid} should be proposable")
            self.assertTrue(
                (by_id[fid].get("description") or "").strip(),
                f"built-in field {fid} should carry a default description",
            )
        # color's guidance explicitly steers off a hex code — the reported bug
        # was the model inventing a hex value + rationale for this field.
        self.assertIn("hex", by_id["color"]["description"].lower())
        # ADR-0082 §2: `tags` is an entity_ref_list now — ADR-0046 §4 already
        # excludes entity_ref/entity_ref_list from AI proposal (no reliable way
        # to name the right node id), so `tags` moved from proposable to the
        # same not-proposable-but-listed treatment `context_policy` gets below.
        # It still carries its description.
        self.assertIn("tags", by_id)
        self.assertFalse(by_id["tags"]["proposable"], "tags is a reference field now — not proposable")
        self.assertTrue(
            (by_id["tags"].get("description") or "").strip(),
            "built-in field tags should carry a default description",
        )
        # ADR-0059 §F: `context_policy` is an author-owned context knob the AI
        # must never set. It ships `ai_proposable: false`, so it stays in the full
        # roster (ADR-0060 §3) but flagged not-proposable for the template to skip.
        self.assertIn("context_policy", by_id)
        self.assertFalse(by_id["context_policy"]["proposable"])

    def test_fields_includes_body_with_description(self) -> None:
        # #1067: `body` is a proposable field, so it appears in the roster — that
        # is what lets the brainstorm create seed list it with its description.
        # Consumers that route body via the top-level "body" key (the extraction
        # contract loop; the revise-mode long_text displays) filter `f.id != "body"`
        # themselves; the roster itself must yield it, carrying its description.
        schema = self.service.read_metadata_schema()
        self.assertIn("body", schema.entry_types["lore:character"].fields)  # in membership
        by_id = {f["id"]: f for f in _fields(self.service, schema, self.hero.id)}
        self.assertIn("body", by_id)
        self.assertTrue(by_id["body"]["proposable"])
        self.assertTrue((by_id["body"].get("description") or "").strip())

    def test_is_proposable_field_honors_ai_proposable(self) -> None:
        # ADR-0059 §E: the single predicate gates on `ai_proposable` (default
        # True). This is the one place the contract loop and the validate-time
        # filter both consult, so an off-limits field is invisible to the model
        # AND dropped if smuggled in.
        yes = MetadataFieldDefinition(name="Yes", type="text")
        no = MetadataFieldDefinition(name="No", type="text", ai_proposable=False)
        self.assertTrue(is_proposable_field("yes", yes))
        self.assertFalse(is_proposable_field("no", no))

    def test_stray_fields_body_is_dropped(self) -> None:
        # ADR-0059 §B/§E: `body` is single-sourced via the top-level "body" key;
        # a `body` smuggled into the fields object is dropped, never adopted as a
        # field value (it is excluded from the fields allow-list).
        patch = self.service.validate_ai_entry_patch_for_type(
            "lore:character", '{"fields": {"body": "smuggled"}}'
        )
        self.assertNotIn("body", patch.fields)
        self.assertIn("body", patch.dropped)

    def test_body_kept_by_default_then_dropped_when_not_ai_proposable(self) -> None:
        # ADR-0059 §E: body enforces `ai_proposable` at the verbatim-adopt site
        # (it does not travel through is_proposable_field). Default schema keeps a
        # proposed body; a layer marking body off-limits drops it.
        kept = self.service.validate_ai_entry_patch_for_type(
            "lore:character", '{"body": "kept prose", "fields": {}}'
        )
        self.assertEqual(kept.body, "kept prose")

        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["body"] = {"ai_proposable": False}
        self.service._write_yaml(schema_path, data)

        dropped = self.service.validate_ai_entry_patch_for_type(
            "lore:character", '{"body": "off-limits prose", "fields": {}}'
        )
        self.assertIsNone(dropped.body)

    def test_body_dropped_for_bodiless_type(self) -> None:
        # ADR-0059 §B: a bodiless type has no body field, so a proposed top-level
        # "body" is dropped on adopt rather than written to a type with no body.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("entry_types", {})["lore:token"] = {
            "name": "Token",
            "kind": "lore",
            "parent": "lore:base",
            "has_body": False,
        }
        self.service._write_yaml(schema_path, data)
        patch = self.service.validate_ai_entry_patch_for_type(
            "lore:token", '{"body": "nope", "fields": {}}'
        )
        self.assertIsNone(patch.body)


class ValidateAiEntryDraftTests(unittest.TestCase):
    """ADR-0046 §6.4 — the create-mode sibling. `validate_ai_entry_draft`
    scopes validation to a target entry_type with NO entry to read; same
    per-field drop rules as the revise path."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "AI Draft Tests")
        add_character_patch_fields(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_title_body_and_fields_kept(self) -> None:
        raw = (
            '{"body": "A wandering knight.", '
            '"fields": {"title": "Seren", "bio": "Old bio.", "allegiance": "order"}}'
        )
        patch = self.service.validate_ai_entry_draft("lore:character", raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "A wandering knight.")
        self.assertEqual(
            patch.fields, {"title": "Seren", "bio": "Old bio.", "allegiance": "order"}
        )
        self.assertEqual(patch.dropped, [])

    def test_illegal_and_hidden_dropped_not_fatal(self) -> None:
        raw = (
            '{"fields": {"title": "Seren", "allegiance": "moon", '
            '"secret_note": "leaked", "bio": "kept"}}'
        )
        patch = self.service.validate_ai_entry_draft("lore:character", raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.fields, {"title": "Seren", "bio": "kept"})
        self.assertIn("allegiance", patch.dropped)
        self.assertIn("secret_note", patch.dropped)

    def test_reference_excluded(self) -> None:
        raw = '{"fields": {"patron": "lore_whoever"}}'
        patch = self.service.validate_ai_entry_draft("lore:character", raw)
        self.assertEqual(patch.fields, {})
        self.assertIn("patron", patch.dropped)

    def test_garbled_flagged(self) -> None:
        patch = self.service.validate_ai_entry_draft("lore:character", "no json here")
        self.assertTrue(patch.garbled)

    def test_unknown_entry_type_drops_all_but_keeps_body(self) -> None:
        # No such type → no allowed fields, so every field drops, but the reply
        # is well-formed (not garbled) and the body still comes through.
        raw = '{"body": "text", "fields": {"bio": "x"}}'
        patch = self.service.validate_ai_entry_draft("lore:nonesuch", raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "text")
        self.assertEqual(patch.fields, {})
        self.assertIn("bio", patch.dropped)


class FieldRosterFromTypeTests(unittest.TestCase):
    """The roster / name helpers used by the create-mode template, which names
    a target entry_type rather than an entry (ADR-0046 §6.4)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Roster Tests")
        add_character_patch_fields(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fields_accepts_an_entry_type_string(self) -> None:
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, "lore:character")
        by_id = {f["id"]: f for f in roster}
        self.assertEqual(by_id["allegiance"]["type"], "select")
        self.assertEqual(by_id["allegiance"]["options"], ["order", "chaos"])
        self.assertTrue(by_id["title"]["proposable"])  # proposable in create mode too
        # Full roster in create mode too: reference / hidden present, not-proposable.
        self.assertFalse(by_id["patron"]["proposable"])
        self.assertFalse(by_id["secret_note"]["proposable"])

    def test_fields_unknown_type_is_empty(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertEqual(_fields(self.service, schema, "lore:nonesuch"), [])

    def test_type_name_uses_definition_name(self) -> None:
        schema = self.service.read_metadata_schema()
        expected = schema.entry_types["lore:character"].name
        self.assertEqual(_type_name(schema, "lore:character"), expected)

    def test_type_name_falls_back_to_last_segment(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertEqual(_type_name(schema, "lore:nonesuch"), "nonesuch")

    def test_revise_entry_template_renders_both_modes(self) -> None:
        # The materialized prompt body branches on `input.entry`: present ⇒
        # revise, absent ⇒ create. Render both and assert each takes its branch
        # without a StrictUndefined error.
        # The shipped revise:entry body lives in the built-in Library now
        # (ADR-0049 §7), not a freshly-created instance's `default_body`.
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Revise entry"))
        env = create_environment_for_project(self.service)
        template = env.from_string(prompt.body)
        label = self.service.read_metadata_schema().entry_types["lore:character"].name

        create_mode = template.render(inputs={"entry": "", "entry_type": "lore:character"})
        self.assertIn("create a new", create_mode)
        self.assertIn(label, create_mode)
        self.assertIn("allegiance", create_mode)  # fields to develop listed
        self.assertNotIn("entry under revision", create_mode)
        # ADR-0051 S4: goal-directed seed — it drives toward a committable result
        # and the structured result is extracted separately, so the seed no longer
        # carries the JSON format contract.
        self.assertIn("ready to commit", create_mode)
        self.assertNotIn('"fields"', create_mode)

        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        revise_mode = template.render(inputs={"entry": hero.id, "entry_type": ""})
        self.assertIn("revise **Seren**", revise_mode)  # took the revise branch
        self.assertNotIn("create a new", revise_mode)
        # The revise branch names the fields to develop (the contract, driven off
        # `field_contract`), but no format contract — that's the extraction
        # endpoint's job now (S4). Current values are delivered via use(), below.
        self.assertIn("allegiance", revise_mode)
        self.assertIn("fields you can develop", revise_mode)
        self.assertIn("ready to commit", revise_mode)
        self.assertNotIn('"fields"', revise_mode)

    def test_revise_delivers_current_values_via_use(self) -> None:
        # #1220: a genuine revise is informed by the entry's current values — but
        # they are delivered through the use() block the backend places (every
        # field, correctly typed, including long_text and body), not printed into
        # the prompt text. So the render registers the subject for use() and does
        # NOT inline the raw values; the per-type value formatting those values get
        # is covered by the lore_block renderer tests (#1230), not here.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["aliases"] = {"name": "Aliases", "type": "multi_select"}
        character = data["entry_types"]["lore:character"]
        character["fields"] = ["aliases", *character["fields"]]
        self.service._write_yaml(schema_path, data)

        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self.service.save_lore_entry(
            hero.id,
            SaveLoreEntryRequest(
                title="Seren",
                body="A knight.",
                entry_type="lore:character",
                metadata={"allegiance": "order", "aliases": ["The Grey", "Wanderer"]},
            ),
        )
        # The shipped revise:entry body lives in the built-in Library now
        # (ADR-0049 §7), not a freshly-created instance's `default_body`.
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Revise entry"))
        env = create_environment_for_project(self.service)
        rendered = env.from_string(prompt.body).render(
            inputs={"entry": hero.id, "entry_type": ""}
        )
        self.assertIn(hero.id, env.used_nodes)  # subject registered for use()
        # The raw current values are NOT baked into the prompt text — they ride
        # the backend block. ("order" would appear as an allegiance *option* in the
        # field descriptors, so assert on an alias value, which is not an option.)
        self.assertNotIn("The Grey", rendered)
        self.assertNotIn("A knight.", rendered)  # body not inline either


class KindAgnosticSeamTests(unittest.TestCase):
    """ADR-0048 §5 — `validate_ai_entry_patch` resolves the target's entry_type
    from the node index, so it works for ANY schema-typed node kind, not just
    lore. These pin that the lore read is gone: a missing id is a plain 404, and
    a non-lore node is validated against its OWN entry_type's schema."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Kind-agnostic seam")
        # `bio` becomes a lore:character field (and a global field def).
        add_character_patch_fields(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_node_is_a_plain_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.validate_ai_entry_patch("does-not-exist", '{"fields": {}}')
        self.assertEqual(ctx.exception.status_code, 404)

    def test_resolves_a_scenes_own_entry_type_not_lore(self) -> None:
        # A scene under a chapter: a non-lore schema-typed node. `bio` is a
        # lore:character field absent from the scene's type, so validating a
        # patch that proposes it must DROP it — proof the seam resolved the
        # scene's entry_type from the index. Had it wrongly read lore, `bio`
        # would survive.
        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter", entry_type="manuscript:chapter", parent_id=structure.root.id
            )
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "manuscript:chapter")
        scene = self.service.create_scene(
            CreateSceneRequest(title="Scene", parent_id=chapter_id)
        )
        patch = self.service.validate_ai_entry_patch(
            scene.id, '{"fields": {"bio": "not a scene field"}}'
        )
        self.assertEqual(patch.fields, {})
        self.assertIn("bio", patch.dropped)


class EntryPatchRoutesTests(unittest.TestCase):
    """ADR-0048 §5 — the validate/review path is kind-neutral at the HTTP edge:
    `/api/ai/entry-patch/{id}` and `/api/ai/entry-draft`, off the `/api/lore`
    prefix (pre-1.0: the old lore-prefixed routes are removed, not aliased)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Entry-patch routes")
        add_character_patch_fields(self.service, self.root)
        self.hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_kind_neutral_patch_route_validates(self) -> None:
        resp = self.client.post(
            f"/api/ai/entry-patch/{self.hero.id}",
            json={"raw": '{"body": "New.", "fields": {"bio": "A new bio."}}'},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["body"], "New.")
        self.assertEqual(body["fields"], {"bio": "A new bio."})

    def test_kind_neutral_draft_route_validates(self) -> None:
        resp = self.client.post(
            "/api/ai/entry-draft",
            json={"entry_type": "lore:character", "raw": '{"fields": {"bio": "Drafted."}}'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["fields"], {"bio": "Drafted."})

    def test_patch_route_maps_missing_node_to_http_404(self) -> None:
        # The service raises ProjectServiceError(404) for an id absent from the
        # node index; the route's `translate_errors()` must surface that as an HTTP
        # 404, not a 500 — the edge mapping the service-level test can't exercise.
        resp = self.client.post(
            "/api/ai/entry-patch/does-not-exist", json={"raw": '{"fields": {}}'}
        )
        self.assertEqual(resp.status_code, 404)

    def test_old_lore_prefixed_routes_are_gone(self) -> None:
        # The old POST routes no longer serve the loop. The exact "gone" status is
        # NOT stable across environments: when a frontend build is present
        # (`frontend/dist` → `main.py` mounts a `/` SPA StaticFiles catch-all), an
        # unmatched API path falls through to it and returns 405 (GET/HEAD only)
        # instead of 404. CI's backend job builds no frontend → 404; a local run
        # after `npm run build` → 405 (#1428). So assert the mount-independent
        # invariant — the old route does NOT serve (never a 2xx) — allowing either
        # code, rather than pinning an exact 404 that flips with local build state.
        self.assertIn(
            self.client.post(
                f"/api/lore/{self.hero.id}/ai-patch", json={"raw": "{}"}
            ).status_code,
            (404, 405),
        )
        # `/api/lore/ai-draft` is shadowed by GET `/api/lore/{entry_id}`
        # (entry_id="ai-draft"), a specific route that wins over the `/` catch-all
        # and registers no POST handler → 405 regardless of build state.
        self.assertEqual(
            self.client.post(
                "/api/lore/ai-draft",
                json={"entry_type": "lore:character", "raw": "{}"},
            ).status_code,
            405,
        )


class SceneSummaryPromptTests(unittest.TestCase):
    """ADR-0051 S5-next — the "Summarize scene" brainstorm: the `revise:entry`
    entry_patch loop pointed at a scene's `summary` field, reviewed in `replace`
    mode (a whole-field swap, no run-diff). Pins the shipped entry_type shape, the
    fields-only template, and that a summary patch validates on a scene."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Scene summary")
        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter", entry_type="manuscript:chapter", parent_id=structure.root.id
            )
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "manuscript:chapter")
        created = self.service.create_scene(
            CreateSceneRequest(title="Storm", parent_id=chapter_id)
        )
        self.scene_id = created.id
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body="Seren rides into the storm, chasing the thief who took the relic.",
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"summary": "Old synopsis."},
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_instance_declares_replace_review_and_targets_a_scene(self) -> None:
        # ADR-0065 S3 collapsed `prompt:revise:scene_summary` into `prompt:general`
        # — the commit config that used to live on the type now rides the shipped
        # node's own instance `context_strategy`.
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Summarize scene"))
        self.assertEqual(prompt.entry_type, "prompt:general")
        assert prompt.context_strategy is not None
        # A brainstorm chat with a commit (ADR-0054 §2 / ADR-0065): the handler is
        # `extract_to_node` and the review + extraction ride on the `commit`. The first
        # non-default `review` value — `replace`, not `visual_diff` — is the signal
        # that flips the review off the run-diff engine (S5-next).
        output = prompt.context_strategy.output
        assert output is not None and output.commit is not None
        self.assertEqual(output.handler, "extract_to_node")
        self.assertEqual(output.commit.review, "replace")
        # REVISE-ONLY: a required `entry` input targeting a scene (no create mode).
        inputs = {i.name: i for i in prompt.inputs}
        self.assertEqual(list(inputs), ["entry"])
        self.assertTrue(inputs["entry"].required)
        self.assertEqual(inputs["entry"].type, "context_pick")
        sources = (inputs["entry"].target or {}).get("sources") or [{}]
        self.assertEqual(sources[0].get("kind"), "scene")

    def test_shipped_prompt_resolves_as_general(self) -> None:
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Summarize scene"))
        self.assertEqual(prompt.entry_type, "prompt:general")

    def test_template_hands_the_scene_prose_but_carries_no_contract(self) -> None:
        # ADR-0051 S4 / ADR-0067 S2: the goal-directed seed hands the model the
        # scene's prose and current summary to work from; the JSON format
        # envelope is NOT in the seed — it is built at commit from the field
        # set the seed's own `field_contract` loop registered (asserted in
        # test_ai_extraction).
        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Summarize scene"))
        env = create_environment_for_project(self.service)
        rendered = env.from_string(prompt.body).render(inputs={"entry": self.scene_id})
        self.assertIn("chasing the thief", rendered)
        self.assertIn("Old synopsis.", rendered)
        self.assertNotIn('{"fields"', rendered)

    def test_summary_patch_validates_on_a_scene(self) -> None:
        # `summary` is a manuscript:base long_text field → proposable, so a summary
        # patch on a scene is kept end to end (the commit target of S5-next).
        patch = self.service.validate_ai_entry_patch(
            self.scene_id,
            '{"fields": {"summary": "Seren pursues the relic-thief through a storm."}}',
        )
        self.assertFalse(patch.garbled)
        self.assertEqual(
            patch.fields, {"summary": "Seren pursues the relic-thief through a storm."}
        )
        self.assertEqual(patch.dropped, [])


class ColorFieldSnapTests(unittest.TestCase):
    """#696 — a colour field's value space is the palette. The AI can emit a raw
    hex or unknown name; the patch must snap it onto a swatch id (so it renders,
    and the colour is not silently lost on adoption) or drop it if unmappable."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Color Snap Tests")
        # Add a colour field to lore:character.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["hue"] = {"name": "Hue", "type": "color"}
        character = data["entry_types"].get("lore:character") or {}
        own = list(character.get("fields") or [])
        if "hue" not in own:
            own.insert(0, "hue")
        character["fields"] = own
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)
        self.hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self.palette_ids = {s.id for s in machine_palette()}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_raw_hex_is_snapped_to_a_palette_swatch(self) -> None:
        patch = self.service.validate_ai_entry_patch(self.hero.id, '{"fields": {"hue": "#660066"}}')
        self.assertFalse(patch.garbled)
        snapped = patch.fields.get("hue")
        # No longer the raw hex, and now a real palette id the UI can resolve.
        self.assertNotEqual(snapped, "#660066")
        self.assertIn(snapped, self.palette_ids)
        self.assertEqual(patch.dropped, [])

    def test_existing_palette_id_passes_through(self) -> None:
        swatch_id = next(iter(self.palette_ids))
        patch = self.service.validate_ai_entry_patch(
            self.hero.id, f'{{"fields": {{"hue": "{swatch_id}"}}}}'
        )
        self.assertEqual(patch.fields, {"hue": swatch_id})
        self.assertEqual(patch.dropped, [])

    def test_unmappable_colour_is_dropped_not_stored(self) -> None:
        patch = self.service.validate_ai_entry_patch(self.hero.id, '{"fields": {"hue": "banana"}}')
        self.assertEqual(patch.fields, {})
        self.assertIn("hue", patch.dropped)

    def test_create_draft_path_also_snaps(self) -> None:
        # The create sibling shares the same validation, so the from-scratch
        # draft must snap too (it is where #696 was first seen).
        patch = self.service.validate_ai_entry_draft(
            "lore:character", '{"fields": {"hue": "#0b6"}}'
        )
        snapped = patch.fields.get("hue")
        self.assertIn(snapped, self.palette_ids)
        self.assertNotIn(snapped, {"#0b6", "#00bb66"})


if __name__ == "__main__":
    unittest.main()
