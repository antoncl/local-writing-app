"""ADR-0046 slice 3a — the brainstorm commit's structured patch.

Covers the three new backend pieces:
- `parse_entry_patch_json` — turning a (possibly fenced / prose-wrapped) model
  reply into a patch dict, or flagging it garbled;
- `validate_ai_entry_patch` — validate-on-return: per-field validation against
  the entry_type's schema, dropping the illegal ones without failing the whole
  patch, references / computed always excluded (§4);
- `field_catalog` — the Jinja helper that lists an entry's proposable fields so
  the prompt names real field ids.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
from app.services.ai.entry_patch import parse_entry_patch_json
from app.services.ai.helpers import (
    _entry_type_label,
    _field_catalog,
    create_environment_for_project,
)
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

    def test_field_catalog_lists_proposable_fields_only(self) -> None:
        schema = self.service.read_metadata_schema()
        catalog = _field_catalog(self.service, schema, self.hero.id)
        by_id = {f["id"]: f for f in catalog}
        # long_text + select are proposable and carry their type / options.
        self.assertEqual(by_id["bio"]["type"], "long_text")
        self.assertEqual(by_id["allegiance"]["type"], "select")
        self.assertEqual(by_id["allegiance"]["options"], ["order", "chaos"])
        # `title` IS proposable — an AI rename is adoptable (#4).
        self.assertIn("title", by_id)
        # References, computed, the structural id/entry_type, and hidden fields
        # are never offered.
        self.assertNotIn("patron", by_id)
        self.assertNotIn("id", by_id)
        self.assertNotIn("entry_type", by_id)
        self.assertNotIn("secret_note", by_id)

    def test_field_catalog_usable_from_jinja(self) -> None:
        # The helper is registered and the for-if filter the template uses works.
        env = create_environment_for_project(self.service)
        rendered = env.from_string(
            "{% for f in field_catalog(input.entry) if f.type == 'long_text' %}"
            "{{ f.id }},{% endfor %}"
        ).render(input={"entry": self.hero.id})
        self.assertIn("bio", rendered)


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


class FieldCatalogFromTypeTests(unittest.TestCase):
    """The catalog / label helpers used by the create-mode template, which names
    a target entry_type rather than an entry (ADR-0046 §6.4)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Catalog Tests")
        add_character_patch_fields(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_field_catalog_accepts_an_entry_type_string(self) -> None:
        schema = self.service.read_metadata_schema()
        catalog = _field_catalog(self.service, schema, "lore:character")
        by_id = {f["id"]: f for f in catalog}
        self.assertEqual(by_id["allegiance"]["type"], "select")
        self.assertEqual(by_id["allegiance"]["options"], ["order", "chaos"])
        self.assertIn("title", by_id)  # proposable in create mode too
        self.assertNotIn("patron", by_id)
        self.assertNotIn("secret_note", by_id)

    def test_field_catalog_unknown_type_is_empty(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertEqual(_field_catalog(self.service, schema, "lore:nonesuch"), [])

    def test_entry_type_label_uses_definition_name(self) -> None:
        schema = self.service.read_metadata_schema()
        expected = schema.entry_types["lore:character"].name
        self.assertEqual(_entry_type_label(schema, "lore:character"), expected)

    def test_entry_type_label_falls_back_to_last_segment(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertEqual(_entry_type_label(schema, "lore:nonesuch"), "nonesuch")

    def test_revise_entry_template_renders_both_modes(self) -> None:
        # The materialized prompt body branches on `input.entry`: present ⇒
        # revise, absent ⇒ create. Render both and assert each takes its branch
        # without a StrictUndefined error.
        # The shipped revise:entry body lives in the built-in Library now
        # (ADR-0049 §7), not a freshly-created instance's `default_body`.
        prompt = self.service.read_prompt_entry("builtin-revise-entry")
        env = create_environment_for_project(self.service)
        template = env.from_string(prompt.body)
        label = self.service.read_metadata_schema().entry_types["lore:character"].name

        create_mode = template.render(input={"entry": "", "entry_type": "lore:character"})
        self.assertIn("create a new", create_mode)
        self.assertIn(label, create_mode)
        self.assertIn("allegiance", create_mode)  # full catalog offered
        self.assertIn("title", create_mode)  # title required in create mode
        self.assertNotIn("entry under revision", create_mode)

        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        revise_mode = template.render(input={"entry": hero.id, "entry_type": ""})
        self.assertIn("entry under revision", revise_mode)
        self.assertNotIn("create a new", revise_mode)
        # The revise branch now offers the full proposable catalog, not just
        # long-text fields (#653): a `select` is listed with its options and
        # the instruction covers list/select shapes, so slice 3b's structured
        # flips are actually reachable end-to-end.
        self.assertIn("allegiance", revise_mode)
        self.assertIn("one of: order, chaos", revise_mode)
        self.assertIn("listed options exactly", revise_mode)
        self.assertIn("Current field values", revise_mode)

    def test_revise_appendix_shows_current_structured_values(self) -> None:
        # So a genuine revise is informed, the appendix now lists the entry's
        # current non-long-text values (#653). Cover every render branch: a
        # scalar string as-is, a list joined, a falsy-but-set number (0) and
        # boolean (False) rendered rather than swallowed, and an unset field
        # shown as empty — the exact distinctions a naive `val or "…"` loses.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["aliases"] = {"name": "Aliases", "type": "multi_select"}
        data["fields"]["age"] = {"name": "Age", "type": "number"}
        data["fields"]["deceased"] = {"name": "Deceased", "type": "boolean"}
        data["fields"]["epithet"] = {"name": "Epithet", "type": "text"}
        character = data["entry_types"]["lore:character"]
        character["fields"] = ["aliases", "age", "deceased", "epithet", *character["fields"]]
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
                metadata={
                    "allegiance": "order",
                    "aliases": ["The Grey", "Wanderer"],
                    "age": 0,
                    "deceased": False,
                    # `epithet` deliberately left unset.
                },
            ),
        )
        # The shipped revise:entry body lives in the built-in Library now
        # (ADR-0049 §7), not a freshly-created instance's `default_body`.
        prompt = self.service.read_prompt_entry("builtin-revise-entry")
        env = create_environment_for_project(self.service)
        rendered = env.from_string(prompt.body).render(
            input={"entry": hero.id, "entry_type": ""}
        )
        self.assertIn("Allegiance (allegiance): order", rendered)
        self.assertIn("Aliases (aliases): The Grey, Wanderer", rendered)
        self.assertIn("Age (age): 0", rendered)
        self.assertIn("Deceased (deceased): False", rendered)
        self.assertIn("Epithet (epithet): _(empty)_", rendered)


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
                title="Chapter", entry_type="scene:chapter", parent_id=structure.root.id
            )
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "scene:chapter")
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
        # The old POST routes no longer serve the loop, and each is gone in a
        # DIFFERENT way — assert both exactly so a 404↔405 drift is caught:
        #   `…/{id}/ai-patch` has no registered subpath at all           → 404
        #   `/api/lore/ai-draft` is shadowed by GET `/api/lore/{entry_id}`
        #   (entry_id="ai-draft"), which registers no POST handler        → 405
        self.assertEqual(
            self.client.post(
                f"/api/lore/{self.hero.id}/ai-patch", json={"raw": "{}"}
            ).status_code,
            404,
        )
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
                title="Chapter", entry_type="scene:chapter", parent_id=structure.root.id
            )
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "scene:chapter")
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
                entry_type="scene:scene",
                metadata={"summary": "Old synopsis."},
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_entry_type_declares_replace_review_and_targets_a_scene(self) -> None:
        schema = self.service.read_metadata_schema()
        etype = schema.entry_types["prompt:revise:scene_summary"]
        self.assertFalse(etype.abstract)
        self.assertEqual(etype.parent, "prompt:revise")
        assert etype.prompt is not None and etype.prompt.context_strategy is not None
        # The first non-default `review` value — `replace`, not `visual_diff` —
        # is the signal that flips the review off the run-diff engine (S5-next).
        self.assertEqual(
            etype.prompt.context_strategy.output,
            {"kind": "entry_patch", "review": "replace"},
        )
        # REVISE-ONLY: a required `entry` input targeting a scene (no create mode).
        inputs = {i.name: i for i in etype.default_inputs}
        self.assertEqual(list(inputs), ["entry"])
        self.assertTrue(inputs["entry"].required)
        self.assertEqual(inputs["entry"].type, "context_pick")
        sources = (inputs["entry"].target or {}).get("sources") or [{}]
        self.assertEqual(sources[0].get("kind"), "scene")

    def test_shipped_prompt_resolves_with_the_type(self) -> None:
        prompt = self.service.read_prompt_entry("builtin-summarize-scene")
        self.assertEqual(prompt.entry_type, "prompt:revise:scene_summary")

    def test_template_emits_fields_only_summary_and_never_a_body(self) -> None:
        prompt = self.service.read_prompt_entry("builtin-summarize-scene")
        env = create_environment_for_project(self.service)
        rendered = env.from_string(prompt.body).render(input={"entry": self.scene_id})
        # The exact commit shape: only the `summary` field, no `body` key.
        self.assertIn('{"fields": {"summary"', rendered)
        # The revise:entry-style `{"body": "<...>", ...}` shape must NOT appear —
        # a scene's prose body is never rewritten by a summary regenerate.
        self.assertNotIn('"body": "<', rendered)
        # The scene's prose and current summary are handed to the model to work from.
        self.assertIn("chasing the thief", rendered)
        self.assertIn("Old synopsis.", rendered)

    def test_summary_patch_validates_on_a_scene(self) -> None:
        # `summary` is a scene:base long_text field → proposable, so a summary
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


if __name__ == "__main__":
    unittest.main()
