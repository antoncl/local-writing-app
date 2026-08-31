from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import (
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
)
from app.models.project import ProjectInfo
from app.services.ai.entry_ref import ProjectInfoRef
from app.services.ai.helpers import (
    create_environment_for_project,
    last_words,
)
from app.services.ai.lore_block import (
    _format_lore_block,
    _render_lore_entries,
    _wrap_lore_block,
)
from app.services.ai.lore_selection import (
    _relevant_lore,
    _relevant_lore_ids,
    _tier_lore_ids,
)
from app.services.ai.sessions import AISession
from app.services.ai.templates import render_template
from app.services.project_service import ProjectService


class LastWordsTests(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(last_words("one two three four five", 2), "four five")

    def test_returns_all_when_n_exceeds_count(self) -> None:
        self.assertEqual(last_words("one two three", 10), "one two three")

    def test_n_zero_returns_empty(self) -> None:
        self.assertEqual(last_words("anything", 0), "")

    def test_n_negative_returns_empty(self) -> None:
        self.assertEqual(last_words("anything", -3), "")

    def test_none_text_returns_empty(self) -> None:
        self.assertEqual(last_words(None, 5), "")

    def test_whitespace_only_returns_empty(self) -> None:
        self.assertEqual(last_words("   \n  ", 5), "")

    def test_n_non_integer_returns_empty(self) -> None:
        self.assertEqual(last_words("hi there", "lots"), "")


class _HelperFixtureBase(unittest.TestCase):
    """Shared setup: creates a project with one act + two scenes + lore entries."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService.created_at(self.root, "Helper Tests")

        # `home_place` is a built-in entity_ref field on Character (#1316),
        # so the tests below can use it directly with no local schema setup.

        # Lore: Honor Harrington (character), Manticore (place), Nimitz (character)
        self.honor = self._make_lore(
            title="Honor Harrington",
            entry_type="lore:character",
            metadata={"aliases": ["The Salamander"], "home_place": None},
            body="Captain of the Fearless. Treecat-adopted.",
        )
        self.manticore = self._make_lore(
            title="Manticore",
            entry_type="lore:location",
            metadata={"aliases": ["Star Kingdom"]},
            body="A binary star system; the capital world of the Star Kingdom.",
        )
        self.nimitz = self._make_lore(
            title="Nimitz",
            entry_type="lore:character",
            metadata={"aliases": []},
            body="Honor's treecat companion.",
        )
        # Link Honor → Nimitz via related_entries (the ref graph hop)
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless. Treecat-adopted.",
        )

        # Manuscript structure: Act → Scene 1, Scene 2
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        self.act_node = next(c for c in structure.root.children if c.type == "manuscript:act")
        s1 = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="manuscript:scene", parent_id=self.act_node.id
            )
        )
        self.scene_one_node = self._latest_scene_under(s1.root, self.act_node.id)
        s2 = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Arrival", entry_type="manuscript:scene", parent_id=self.act_node.id
            )
        )
        self.scene_two_node = self._latest_scene_under(s2.root, self.act_node.id)

        # Populate scene_one with a summary mentioning Honor (alias) + characters list
        self._update_scene(
            self.scene_one_node.scene_id,
            title="The Departure",
            entry_type="manuscript:scene",
            metadata={
                "summary": "Honor takes the Salamander into battle.",
                "characters": [self.honor["id"]],
            },
            body="Scene one body.",
        )
        # Populate scene_two with a summary that mentions Manticore (alias-only)
        self._update_scene(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={
                "summary": "The fleet returns to Star Kingdom under quiet stars.",
                "characters": [],
                "pov": self.honor["id"],
            },
            body="Scene two body.",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ---- helpers for setup ----

    def _make_lore(self, *, title: str, entry_type: str, metadata: dict, body: str) -> dict:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type=entry_type)
        )
        self._update_lore(created.id, entry_type=entry_type, metadata=metadata, body=body)
        # Re-read to get updated revision
        updated = self.service.read_lore_entry(created.id)
        return {"id": updated.id, "title": updated.title, "entry": updated}

    def _update_lore(self, entry_id: str, *, entry_type: str, metadata: dict, body: str) -> None:
        existing = self.service.read_lore_entry(entry_id)
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=existing.title,
                body=body,
                base_revision=existing.revision,
                entry_type=entry_type,
                metadata=metadata,
            ),
        )

    def _update_scene(
        self, scene_id: str, *, title: str, entry_type: str, metadata: dict, body: str
    ) -> None:
        existing = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                status="draft",
                entry_type=entry_type,
                metadata=metadata,
            ),
        )

    def _latest_scene_under(self, root, act_id):
        # Find the act node, return its last scene child.
        for child in root.children:
            if child.id == act_id:
                scenes = [c for c in child.children if c.scene_id]
                return scenes[-1]
            found = self._latest_scene_under(child, act_id)
            if found:
                return found
        return None


class EntryTypeAncestryTests(_HelperFixtureBase):
    """The shared `entry_type_ancestry` primitive + the `is_a` Jinja helper
    (ADR-0026 / #83). A `lore:deity` sub-type inherits `lore:character`."""

    def setUp(self) -> None:
        super().setUp()
        # Add a sub-type deity → character to exercise inheritance.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["entry_types"]["lore:deity"] = {
            "name": "Deity",
            "kind": "lore",
            "parent": "lore:character",
        }
        self.service._write_yaml(schema_path, data)
        self.athena = self._make_lore(
            title="Athena",
            entry_type="lore:deity",
            metadata={"aliases": []},
            body="Goddess of wisdom.",
        )

    def test_ancestry_walks_parent_chain(self) -> None:
        # Full chain incl. the built-in base type character inherits from.
        self.assertEqual(
            self.service.entry_type_ancestry("lore:deity"),
            ["lore:deity", "lore:character", "lore:base"],
        )

    def test_ancestry_of_seeded_type_reaches_base(self) -> None:
        self.assertEqual(
            self.service.entry_type_ancestry("lore:character"),
            ["lore:character", "lore:base"],
        )

    def test_ancestry_of_unknown_type_is_itself(self) -> None:
        self.assertEqual(self.service.entry_type_ancestry("lore:nope"), ["lore:nope"])

    def _render_is_a(self, entry_obj, fqn: str) -> str:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}'
            '{% if is_a(entry, "' + fqn + '") %}yes{% else %}no{% endif %}'
            "{% endrole %}",
            context={"entry": entry_obj},
            env=env,
        )
        return out.messages[0].text

    def test_is_a_true_for_exact_type(self) -> None:
        honor = self.service.read_lore_entry(self.honor["id"])
        self.assertEqual(self._render_is_a(honor, "lore:character"), "yes")

    def test_is_a_true_for_descendant(self) -> None:
        athena = self.service.read_lore_entry(self.athena["id"])
        # deity inherits character → is_a(deity, "lore:character") holds.
        self.assertEqual(self._render_is_a(athena, "lore:character"), "yes")
        self.assertEqual(self._render_is_a(athena, "lore:deity"), "yes")

    def test_is_a_false_for_unrelated_type(self) -> None:
        manticore = self.service.read_lore_entry(self.manticore["id"])
        self.assertEqual(self._render_is_a(manticore, "lore:character"), "no")

    def test_is_a_false_for_empty_or_missing_arg(self) -> None:
        from app.services.ai.helpers import _is_a

        schema = self.service.read_metadata_schema()
        honor = self.service.read_lore_entry(self.honor["id"])
        self.assertFalse(_is_a(self.service, schema, honor, ""))
        self.assertFalse(_is_a(self.service, schema, honor, None))
        self.assertFalse(_is_a(self.service, schema, None, "lore:character"))

    def test_is_a_falls_back_to_exact_match_without_schema(self) -> None:
        from app.services.ai.helpers import _is_a

        honor = self.service.read_lore_entry(self.honor["id"])
        self.assertTrue(_is_a(self.service, None, honor, "lore:character"))
        # No schema → no inheritance resolution, so a descendant match fails.
        athena = self.service.read_lore_entry(self.athena["id"])
        self.assertFalse(_is_a(self.service, None, athena, "lore:character"))


class PovHelperTests(_HelperFixtureBase):
    def test_pov_resolves_lore_entity_to_dict(self) -> None:
        scene = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}POV: {{ pov(scene).title }}{% endrole %}',
            context={"scene": scene},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "POV: Honor Harrington")

    def test_pov_returns_none_when_absent(self) -> None:
        scene = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}'
            "{% if pov(scene) %}has POV{% else %}no POV{% endif %}"
            "{% endrole %}",
            context={"scene": scene},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "no POV")


class ResolvedNarrationHelperTests(_HelperFixtureBase):
    def test_gate_drops_character_for_no_character_modes(self) -> None:
        from app.services.project.narration import resolved_narration

        # A character-bearing mode keeps the resolved character.
        rc = {"pov_mode": {"value": "third_limited"}, "pov": {"value": "char_x"}}
        self.assertEqual(resolved_narration(rc), {"mode": "third_limited", "character": "char_x"})
        # Omniscient / objective have no viewpoint character — dropped.
        for mode in ("third_omniscient", "third_objective"):
            rc = {"pov_mode": {"value": mode}, "pov": {"value": "char_x"}}
            self.assertEqual(resolved_narration(rc), {"mode": mode, "character": None})
        # Unset all the way down → both None (never raises).
        self.assertEqual(resolved_narration(None), {"mode": None, "character": None})
        self.assertEqual(resolved_narration({}), {"mode": None, "character": None})

    def test_resolved_narration_global_folds_to_the_character(self) -> None:
        # The global is registered and resolves the scene's POV off resolved_cascade
        # (scene_two owns pov=Honor; mode unset, so not gated).
        scene = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}POV: {{ resolved_narration(scene).character.title }}{% endrole %}',
            context={"scene": scene},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "POV: Honor Harrington")

    def test_gate_is_applied_through_the_global(self) -> None:
        # An omniscient scene: the global drops the character (the gate runs INSIDE
        # the helper, not just in the pure function), while `pov(scene)` — the raw
        # own field — still returns it.
        from app.models import SaveSceneRequest

        scene = self.service.read_scene(self.scene_two_node.scene_id)
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                metadata={**scene.metadata, "pov_mode": "third_omniscient"},
            ),
        )
        scene = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}'
            "narration=[{% if resolved_narration(scene).character %}"
            "{{ resolved_narration(scene).character.title }}{% else %}none{% endif %}] "
            "own=[{{ pov(scene).title }}]"
            "{% endrole %}",
            context={"scene": scene},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "narration=[none] own=[Honor Harrington]")


class ScenesBeforeHelperTests(_HelperFixtureBase):
    def test_collects_summaries_of_prior_scenes_only(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ story_so_far(scene) }}{% endrole %}',
            context={"scene": scene_two},
            env=env,
        )
        text = out.messages[0].text
        self.assertIn("The Departure", text)
        self.assertIn("Honor takes the Salamander into battle.", text)
        self.assertNotIn("The Arrival", text)

    def test_empty_when_no_prior_scenes(self) -> None:
        # An empty role block emits no message.
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ story_so_far(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        self.assertEqual(out.messages, [])


class EntryAsOfHelperTests(_HelperFixtureBase):
    """ADR-0060 §3 (was ADR-0055 §1): `entry(entry, at=scene)` resolves the subject
    through `effective_state` at the explicit anchor scene; no anchor (`at=""`)
    degrades to a book-start read."""

    def _mutate_honor_in_scene_two(self) -> None:
        from urllib.parse import quote

        new_body = quote("Admiral of the Fleet. Battle-hardened.")
        self._update_scene(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "The fleet returns.", "characters": [], "pov": self.honor["id"]},
            body=(
                "Honor is promoted. "
                f"<!-- mutate:entity={self.honor['id']};field=title;value=Admiral%20Harrington;id=m1 -->"
                f"<!-- mutate:entity={self.honor['id']};field=body;value={new_body};id=m2 -->"
            ),
        )

    def _render_as_of(self, scene_id: str) -> str:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}{% set c = entry(who, at=as_of) %}'
            "{{ c.title }}|{{ c.body }}{% endrole %}",
            context={"who": self.honor["id"], "as_of": scene_id},
            env=env,
        )
        # A stored lore body keeps a trailing newline; the value resolved from a
        # marker does not. Strip so the assertions compare content, not storage.
        return out.messages[0].text.strip()

    def test_reads_mutated_state_at_or_after_the_change(self) -> None:
        self._mutate_honor_in_scene_two()
        text = self._render_as_of(self.scene_two_node.scene_id)
        self.assertEqual(text, "Admiral Harrington|Admiral of the Fleet. Battle-hardened.")

    def test_reads_base_state_before_the_change(self) -> None:
        self._mutate_honor_in_scene_two()
        # scene_one precedes scene_two in the manuscript, so the marker is not
        # yet live there — the subject reads at its book-start self.
        text = self._render_as_of(self.scene_one_node.scene_id)
        self.assertEqual(text, "Honor Harrington|Captain of the Fearless. Treecat-adopted.")

    def test_no_anchor_is_a_book_start_read(self) -> None:
        self._mutate_honor_in_scene_two()
        # Empty anchor → exactly `original()` (book-start), even though a
        # mutation exists downstream.
        self.assertEqual(
            self._render_as_of(""),
            "Honor Harrington|Captain of the Fearless. Treecat-adopted.",
        )

    def test_resolves_a_context_pick_scene_value(self) -> None:
        # The anchor input is a scene `context_pick`; when the writer picks in the
        # widget the value is a JSON ref list, not a bare id. It must resolve the
        # same as the bare-id launch seed (ADR-0055 §1).
        import json

        self._mutate_honor_in_scene_two()
        picked = json.dumps([{"id": self.scene_two_node.scene_id, "kind": "manuscript"}])
        self.assertEqual(
            self._render_as_of(picked),
            "Admiral Harrington|Admiral of the Fleet. Battle-hardened.",
        )

    def test_overlays_mutated_metadata_fields_not_just_title_body(self) -> None:
        # Collection (aliases, multi_select) and scalar entity_ref (home_place)
        # mutations must ride the metadata overlay, not only intrinsic title/body.
        self._update_scene(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [], "pov": self.honor["id"]},
            body=(
                f"<!-- mutate:entity={self.honor['id']};field=aliases;op=add;value=Steadholder;id=m1 -->"
                f"<!-- mutate:entity={self.honor['id']};field=home_place;value={self.manticore['id']};id=m2 -->"
            ),
        )
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}{% set c = entry(who, at=as_of) %}'
            "{{ c.aliases | join(',') }}|{{ c.home_place.title if c.home_place else 'none' }}"
            "{% endrole %}",
            context={"who": self.honor["id"], "as_of": self.scene_two_node.scene_id},
            env=env,
        )
        text = out.messages[0].text
        # aliases = base ∪ live add; home_place resolves + wraps to an EntryRef.
        self.assertIn("The Salamander", text)
        self.assertIn("Steadholder", text)
        self.assertTrue(text.endswith("|Manticore"))


class EntryAmbientSceneTests(_HelperFixtureBase):
    """ADR-0060 §3: `entry(x)` reads x as of the prompt's *ambient* `scene` — the
    zero-arg "this node as it is here" default — book-start when no scene is set.
    `original(x)` and an explicit `at=None` are always book-start."""

    def _promote_honor_in_scene_two(self) -> None:
        self._update_scene(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [], "pov": self.honor["id"]},
            body=(
                "Honor is promoted. "
                f"<!-- mutate:entity={self.honor['id']};field=title;value=Admiral%20Harrington;id=m1 -->"
            ),
        )

    def _render(self, template: str, scene: object) -> str:
        env = create_environment_for_project(self.service)
        out = render_template(
            template, context={"who": self.honor["id"], "scene": scene}, env=env
        )
        return out.messages[0].text.strip()

    def test_entry_defaults_to_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        # Ambient scene = scene_two, where the promotion is live → as-of read.
        text = self._render(
            '{% role "system" %}{{ entry(who).title }}{% endrole %}',
            self.scene_two_node.scene_id,
        )
        self.assertEqual(text, "Admiral Harrington")

    def test_entry_book_start_when_no_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        text = self._render(
            '{% role "system" %}{{ entry(who).title }}{% endrole %}', None
        )
        self.assertEqual(text, "Honor Harrington")

    def test_original_ignores_the_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        # Even under a scene where the mutation is live, `original()` is book-start.
        text = self._render(
            '{% role "system" %}{{ original(who).title }}{% endrole %}',
            self.scene_two_node.scene_id,
        )
        self.assertEqual(text, "Honor Harrington")

    def test_explicit_at_none_overrides_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        # `at=None` explicitly forces book-start, even under an as-of ambient scene.
        text = self._render(
            '{% role "system" %}{{ entry(who, at=None).title }}{% endrole %}',
            self.scene_two_node.scene_id,
        )
        self.assertEqual(text, "Honor Harrington")

    def test_node_field_sugar_matches_metadata_escape(self) -> None:
        # `node.<field>` resolves the same value as the `node.metadata.<field>`
        # escape (ADR-0060 §3); the escape stays valid.
        text = self._render(
            '{% role "system" %}{{ entry(who).aliases | join(",") }}'
            '|{{ entry(who).metadata.aliases | join(",") }}{% endrole %}',
            None,
        )
        self.assertEqual(text, "The Salamander|The Salamander")


class ProjectInfoRefTests(unittest.TestCase):
    """ADR-0060 §3: `project.<field>` reads the project node's authored metadata,
    with `.metadata` kept as the whole-map escape and the model's own intrinsics
    winning a name collision."""

    def _ref(self):
        info = ProjectInfo(
            title="My Book",
            root_path="/x",
            metadata={"measurement_system": "metric", "title": "SHADOW"},
        )
        return ProjectInfoRef(info, project=None, schema=None)

    def test_field_sugar_reads_metadata(self) -> None:
        self.assertEqual(self._ref().measurement_system, "metric")

    def test_intrinsic_wins_a_collision(self) -> None:
        # A metadata key colliding with a model field never shadows the intrinsic.
        self.assertEqual(self._ref().title, "My Book")

    def test_metadata_escape_is_the_whole_map(self) -> None:
        ref = self._ref()
        self.assertEqual(ref.metadata.get("measurement_system"), "metric")
        self.assertIn("measurement_system", ref.metadata)

    def test_absent_field_is_none(self) -> None:
        self.assertIsNone(self._ref().nonexistent)


class ImpersonateAsOfPreviewTests(_HelperFixtureBase):
    """The anchor rides the prompt's `as_of` scene input (slider-seeded at launch,
    persisted with the chat's inputs) → `inputs.as_of` → `entry(…, at=as_of)`, so
    an impersonate render reads its subject as-of the anchor scene (ADR-0060 §3).
    Mirrors impersonate.md's two key lines; the render takes no as-of param."""

    IMPERSONATE = (
        '{% set as_of = inputs.as_of if inputs.as_of is defined else "" %}'
        "{% set char = entry(inputs.entry, at=as_of) %}"
        '{% role "system" %}You ARE {{ char.title }}.\n'
        "{% if char.body %}{{ char.body }}{% endif %}{% endrole %}"
    )

    def _mutate(self) -> None:
        from urllib.parse import quote

        new_body = quote("Admiral of the Fleet.")
        self._update_scene(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [], "pov": self.honor["id"]},
            body=(
                f"<!-- mutate:entity={self.honor['id']};field=title;value=Admiral%20Harrington;id=m1 -->"
                f"<!-- mutate:entity={self.honor['id']};field=body;value={new_body};id=m2 -->"
            ),
        )

    def _preview(self, as_of_scene: str) -> str:
        from app.services.ai.preview import PreviewRequest, build_preview

        # The anchor rides the prompt's hidden `as_of` input (launch-seeded),
        # persisted with the chat's inputs — not a build_preview parameter.
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.IMPERSONATE,
                target_scene_id="",
                session_id=None,
                inputs={"entry": self.honor["id"], "as_of": as_of_scene},
                text_before="",
                text_after="",
                commit=False,
                subject=self.honor["id"],
            ),
        )
        return "\n".join(m.text for m in rendered.messages)

    def test_render_reads_as_of_anchor(self) -> None:
        self._mutate()
        text = self._preview(self.scene_two_node.scene_id)
        self.assertIn("You ARE Admiral Harrington.", text)
        self.assertIn("Admiral of the Fleet.", text)

    def test_render_without_anchor_is_base(self) -> None:
        self._mutate()
        text = self._preview("")
        self.assertIn("You ARE Honor Harrington.", text)
        self.assertIn("Captain of the Fearless.", text)


class RelevantLoreHelperTests(_HelperFixtureBase):
    """ADR-0060 §2 retired the emitting `relevant_lore()` Jinja global; the one
    lore selector survives as the internal `_relevant_lore`, which the send path
    calls (chat.py). These tests exercise that selector directly."""

    def _lore(self, scene, mode: str = "implicit", *, journal=None) -> str:
        return _relevant_lore(self.service, scene, mode, journal=journal)

    def test_implicit_finds_alias_match_and_one_hop(self) -> None:
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        text = self._lore(scene_one)
        # Honor — direct ref via 'characters' field
        self.assertIn("Honor Harrington", text)
        # Nimitz — one-hop expansion through Honor's related_entries
        self.assertIn("Nimitz", text)

    def test_implicit_alias_only_match(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        text = self._lore(scene_two)
        # 'Star Kingdom' alias for Manticore appears in the summary
        self.assertIn("Manticore", text)

    def test_explicit_skips_alias_scan(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        text = self._lore(scene_two, "explicit")
        # Scene two has no characters in its list and Manticore is alias-only
        self.assertNotIn("Manticore", text)
        # But pov is an entity_ref → Honor should be picked up
        self.assertIn("Honor Harrington", text)

    def test_implicit_finds_textual_one_hop_in_body(self) -> None:
        # Add a third character not referenced by anyone, then mention him
        # textually in Honor's body. Textual depth-1 should pull him in
        # even though no entity_ref links Honor → Pavel.
        self._make_lore(
            title="Pavel Young",
            entry_type="lore:character",
            metadata={"aliases": []},
            body="Captain who hates Honor.",
        )
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],  # NOT Pavel
            },
            body="Captain of the Fearless. Treecat-adopted. Rival of Pavel Young.",
        )

        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        text = self._lore(scene_one)
        # Honor is the direct entry (via characters field)
        self.assertIn("Honor Harrington", text)
        # Nimitz arrives via structural one-hop (related_entries on Honor)
        self.assertIn("Nimitz", text)
        # Pavel arrives via NEW textual one-hop (mentioned in Honor's body,
        # no entity_ref between them)
        self.assertIn("Pavel Young", text)

    def test_textual_one_hop_is_depth_one_only(self) -> None:
        # Pavel mentions a third character "Anders" in his body. Anders
        # should NOT be pulled in — textual expansion stops at depth 1.
        self._make_lore(
            title="Anders Pierce",
            entry_type="lore:character",
            metadata={"aliases": []},
            body="Some other captain.",
        )
        self._make_lore(
            title="Pavel Young",
            entry_type="lore:character",
            metadata={"aliases": []},
            body="Captain. Friend of Anders Pierce.",  # mentions Anders
        )
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless. Rival of Pavel Young.",  # mentions Pavel
        )

        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        text = self._lore(scene_one)
        # Check entity inclusion by the rendered XML tag, not raw substring —
        # Pavel's body literally contains "Anders Pierce" as prose.
        self.assertIn('name="Honor Harrington"', text)
        self.assertIn('name="Pavel Young"', text)        # depth 1: yes
        self.assertNotIn('name="Anders Pierce"', text)   # depth 2: stop

    def test_journal_mode_trusts_journal_skips_alias_scan(self) -> None:
        # When a journal is bound, the selector does NOT rescan the scene
        # summary — it uses the journal as source of truth for detected
        # context. Scene one's summary mentions Honor's alias "Salamander",
        # but with an EMPTY journal we should only get the structural
        # entity_ref picks (characters: [Honor]).
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        text = self._lore(scene_one, journal=[])
        # Honor — structural ref via characters[]
        self.assertIn("Honor Harrington", text)
        # Nimitz — structural one-hop via Honor's related_entries (still runs)
        self.assertIn("Nimitz", text)
        # NOTE: With journal mode active and EMPTY journal, the alias scan
        # is skipped. No extra entities should appear beyond the structural
        # picks. Without journal mode, the summary's mention of "Salamander"
        # would also pull Honor (already present), so no observable diff
        # here — the key behavior is that we didn't crash and didn't double.

    def test_journal_mode_includes_journal_entries(self) -> None:
        # With a populated journal, those entries appear in the output —
        # even though the scene summary wouldn't have surfaced them via
        # alias scan.
        from app.models import ChatSessionJournalEntry

        # Manticore is not referenced or mentioned in scene one's summary
        # ("Honor takes the Salamander into battle.") nor in Honor's metadata.
        # Adding it to the journal forces it into scope.
        journal = [
            ChatSessionJournalEntry(
                entry_id=self.manticore["id"],
                title="Manticore",
                entry_type="lore:location",
                added_at_turn=2,
                source="user_message",
            )
        ]
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        text = self._lore(scene_one, journal=journal)
        self.assertIn("Honor Harrington", text)  # structural
        self.assertIn("Nimitz", text)            # structural one-hop
        self.assertIn("Manticore", text)         # via journal

    def test_journal_mode_skips_textual_one_hop(self) -> None:
        # Without journal: textual depth-1 fires (we just added it in step 1).
        # With journal: textual depth-1 is skipped — the send-time pipeline
        # is supposed to have done that already and put results into journal.
        # Add Pavel; mention him in Honor's body. Without journal, Pavel
        # would arrive via textual depth-1. With empty journal, he should NOT.
        self._make_lore(
            title="Pavel Young",
            entry_type="lore:character",
            metadata={"aliases": []},
            body="Disgraced Captain.",
        )
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless. Rival of Pavel Young.",
        )

        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        text = self._lore(scene_one, journal=[])
        self.assertIn('name="Honor Harrington"', text)
        self.assertIn('name="Nimitz"', text)
        # Pavel was found via textual depth-1 in journal=None mode, but with
        # an explicit empty journal the selector trusts that signal: send-time
        # would have added Pavel to the journal if it wanted him.
        self.assertNotIn('name="Pavel Young"', text)

    def test_pinned_only_returns_empty(self) -> None:
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        # No pinning machinery yet → empty block.
        self.assertEqual(self._lore(scene_one, "pinned_only"), "")

    def test_used_ids_are_exact_no_fanout(self) -> None:
        # #1230: a use()'d node joins the set EXACTLY — its own refs are not
        # fan-out seeds (only the scene's structural/textual refs expand). Give
        # Nimitz a neighbour (Pavel); use()'ing Nimitz on a scene that
        # references neither must include Nimitz but NOT Pavel.
        pavel = self._make_lore(
            title="Pavel Young", entry_type="lore:character",
            metadata={"aliases": []}, body="A captain.",
        )
        self._update_lore(
            self.nimitz["id"], entry_type="lore:character",
            metadata={"aliases": [], "related_entries": [pavel["id"]]},
            body="Honor's treecat companion.",
        )
        # Strip scene_two down to no structural refs and no alias mentions.
        self._update_scene(
            self.scene_two_node.scene_id, title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "Quiet stars.", "characters": []},
            body="Scene two body.",
        )
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        ids = _relevant_lore_ids(
            self.service, scene_two, "implicit", None, [self.nimitz["id"]]
        )
        self.assertIn(self.nimitz["id"], ids)   # exact include
        self.assertNotIn(pavel["id"], ids)      # no fan-out through a use()'d node

    def test_manual_only_lore_via_structural_expansion_is_excluded(self) -> None:
        # #1024: a manual_only entry reachable via an entity_ref (structural
        # one-hop through Honor's related_entries) must NOT leak into an implicit
        # render — manual_only means "explicit picker only". Nimitz, an `auto`
        # entry on the same hop, still arrives.
        secret = self._make_lore(
            title="Grayson Conclave",
            entry_type="lore:character",
            metadata={"aliases": [], "context_policy": "manual_only"},
            body="A secret cabal.",
        )
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"], secret["id"]],
            },
            body="Captain of the Fearless. Treecat-adopted.",
        )
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        ids = _relevant_lore_ids(self.service, scene_one, "implicit", None, None)
        self.assertIn(self.honor["id"], ids)     # direct scene ref
        self.assertIn(self.nimitz["id"], ids)    # `auto`, arrives via structural hop
        self.assertNotIn(secret["id"], ids)      # manual_only: not fanned in (#1024)
        # And its content never reaches a rendered block (its title may still show
        # as a bare ref label inside Honor's related_entries — that is how
        # entity_ref fields render for any policy; #1024 is about the entry's
        # CONTENT being pulled into context, which it now is not).
        self.assertNotIn("A secret cabal", self._lore(scene_one))

    def test_manual_only_lore_is_included_when_used(self) -> None:
        # #1024: use() is exactly the explicit-picker route manual_only DOES
        # allow. A use()'d manual_only id joins the set even though structural
        # expansion drops it — otherwise manual_only would collapse into never.
        secret = self._make_lore(
            title="Grayson Conclave",
            entry_type="lore:character",
            metadata={"aliases": [], "context_policy": "manual_only"},
            body="A secret cabal.",
        )
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"], secret["id"]],
            },
            body="Captain of the Fearless. Treecat-adopted.",
        )
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        # Without use(): excluded via the structural route.
        implicit_ids = _relevant_lore_ids(self.service, scene_one, "implicit", None, None)
        self.assertNotIn(secret["id"], implicit_ids)
        # With use(): the explicit picker overrides manual_only.
        used_ids = _relevant_lore_ids(
            self.service, scene_one, "implicit", None, [secret["id"]]
        )
        self.assertIn(secret["id"], used_ids)

    def test_format_lore_block_renders_non_lore_node(self) -> None:
        # #1230: use() accepts any Node; the renderer must load a non-lore node
        # (a scene) and deliver it, not silently skip it as the lore-only reader
        # once did.
        scene_id = self.scene_one_node.scene_id
        block = _format_lore_block(self.service, [scene_id])
        self.assertIn(f'<scene id="{scene_id}"', block)
        self.assertIn("Scene one body.", block)

    def test_format_lore_block_matches_wrapped_render_lore_entries(self) -> None:
        # ADR-0076 S7 refactor regression: `_format_lore_block` must stay
        # byte-identical to wrapping `_render_lore_entries` directly — the
        # extraction is pure, no drift between the tier blob and the per-entry
        # leaves the Context door drills into.
        ids = [self.honor["id"], self.nimitz["id"]]
        direct = _format_lore_block(self.service, ids)
        entries = _render_lore_entries(self.service, ids)
        self.assertEqual(direct, _wrap_lore_block(entries))

    def test_render_lore_entries_returns_per_entry_pairs_in_order(self) -> None:
        # Each pair is the SAME element `_format_lore_block` concatenates —
        # the per-entry leaf the Context door drills an entry down to.
        ids = [self.honor["id"], self.nimitz["id"]]
        entries = _render_lore_entries(self.service, ids)
        self.assertEqual([i for i, _ in entries], ids)
        for entry_id, xml in entries:
            self.assertIn(f'id="{entry_id}"', xml)
        wrapped = _format_lore_block(self.service, ids)
        self.assertEqual(wrapped, "<lore>\n" + "\n\n".join(x for _, x in entries) + "\n</lore>")

    def test_render_lore_entries_skips_unreadable_ids(self) -> None:
        # Mirrors the old blob loop: an id whose node can't be read is simply
        # skipped, not surfaced as an empty/error pair.
        ids = [self.honor["id"], "does-not-exist", self.nimitz["id"]]
        entries = _render_lore_entries(self.service, ids)
        self.assertEqual([i for i, _ in entries], [self.honor["id"], self.nimitz["id"]])

    def test_wrap_lore_block_empty_entries_is_empty_string(self) -> None:
        self.assertEqual(_wrap_lore_block([]), "")


class UseHelperTests(_HelperFixtureBase):
    """ADR-0060 §2: `use(node)` records the selection onto the env slot that
    `build_preview` carries to `RenderedTemplate.used_node_ids`, flips the lore
    gate, and emits nothing inline."""

    def _render(self, template_source: str):
        from app.services.ai.preview import PreviewRequest, build_preview

        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=template_source,
                target_scene_id="",
                session_id=None,
                inputs={},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        return rendered

    def test_use_records_id_flips_gate_and_emits_nothing(self) -> None:
        rendered = self._render(
            '{% role "system" %}[{{ use("' + self.nimitz["id"] + '") }}]{% endrole %}'
        )
        # The id is carried to used_node_ids and the lore gate is flipped.
        self.assertEqual(rendered.used_node_ids, [self.nimitz["id"]])
        self.assertTrue(rendered.lore_invoked)
        # use() emits nothing — the node is backend-placed, not inline. The
        # brackets render adjacent (empty between them) and no body leaks.
        text = "".join(m.text for m in rendered.messages)
        self.assertIn("[]", text)
        self.assertNotIn("treecat", text.lower())

    def test_use_dedupes_repeated_ids_preserving_order(self) -> None:
        rendered = self._render(
            '{% role "system" %}'
            '{{ use("' + self.honor["id"] + '") }}'
            '{{ use("' + self.nimitz["id"] + '") }}'
            '{{ use("' + self.honor["id"] + '") }}'
            "{% endrole %}"
        )
        self.assertEqual(
            rendered.used_node_ids, [self.honor["id"], self.nimitz["id"]]
        )

    def test_use_of_an_entry_ref_object_records_its_id(self) -> None:
        # `use(entry(x))` / `use(pov(scene))` — an EntryRef argument resolves the
        # same as an id string (the coercion `entry()` uses).
        rendered = self._render(
            '{% role "system" %}{{ use(entry("' + self.honor["id"] + '")) }}{% endrole %}'
        )
        self.assertEqual(rendered.used_node_ids, [self.honor["id"]])


class ContextPolicyTests(_HelperFixtureBase):
    """Per-entry context_policy: always / auto (default) / manual_only / never."""

    def _set_policy(self, entry_id: str, policy: str) -> None:
        existing = self.service.read_lore_entry(entry_id)
        metadata = dict(existing.metadata)
        metadata["context_policy"] = policy
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=existing.title,
                body=existing.body,
                base_revision=existing.revision,
                entry_type=existing.entry_type,
                metadata=metadata,
            ),
        )

    def _render_scene_one(self) -> str:
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        return _relevant_lore(self.service, scene_one)

    def test_always_policy_unioned_into_implicit_render(self) -> None:
        # A character that's NOT referenced by scene_one and whose name is
        # NOT in the summary. Default would be excluded; "always" pulls in.
        pavel = self._make_lore(
            title="Pavel Young",
            entry_type="lore:character",
            metadata={"aliases": []},
            body="Captain who hates Honor.",
        )
        # Sanity: default policy → not in implicit render
        baseline = self._render_scene_one()
        self.assertNotIn('name="Pavel Young"', baseline)
        # Flip to always → appears
        self._set_policy(pavel["id"], "always")
        self.assertIn('name="Pavel Young"', self._render_scene_one())

    def test_manual_only_policy_skipped_by_alias_match(self) -> None:
        # Mention "Manticore" alias "Star Kingdom" in scene_one's summary.
        # Default auto would pull Manticore in. manual_only must not.
        self._update_scene(
            self.scene_one_node.scene_id,
            title="The Departure",
            entry_type="manuscript:scene",
            metadata={
                "summary": "Honor takes the Salamander into Star Kingdom space.",
                "characters": [self.honor["id"]],
            },
            body="Scene one body.",
        )
        # Baseline (auto): Manticore appears via alias
        self.assertIn('name="Manticore"', self._render_scene_one())
        # Switch to manual_only: alias-match must skip
        self._set_policy(self.manticore["id"], "manual_only")
        self.assertNotIn('name="Manticore"', self._render_scene_one())

    def test_manual_only_appears_via_explicit_ref(self) -> None:
        # manual_only still respects explicit picks. Ref Manticore via the
        # `location` entity_ref on scene_one.
        self._set_policy(self.manticore["id"], "manual_only")
        self._update_scene(
            self.scene_one_node.scene_id,
            title="The Departure",
            entry_type="manuscript:scene",
            metadata={
                "summary": "Honor takes the Salamander into battle.",
                "characters": [self.honor["id"]],
                "location": self.manticore["id"],
            },
            body="Scene one body.",
        )
        self.assertIn('name="Manticore"', self._render_scene_one())

    def test_never_policy_excluded_even_via_explicit_ref(self) -> None:
        # Honor is referenced via scene_one's `characters` field. Marking
        # Honor as "never" must still exclude her from the render.
        self.assertIn('name="Honor Harrington"', self._render_scene_one())
        self._set_policy(self.honor["id"], "never")
        self.assertNotIn('name="Honor Harrington"', self._render_scene_one())

    def test_default_policy_preserves_alias_match(self) -> None:
        # Unset / unknown policy values fall back to auto. Confirm that
        # an entry with no policy key still alias-matches as before.
        text = self._render_scene_one()
        self.assertIn('name="Honor Harrington"', text)
        self.assertIn('name="Nimitz"', text)


class SessionTierTests(_HelperFixtureBase):
    """ADR-0060 §5: the send path computes the one selector once (`_relevant_lore_ids`)
    then splits it into (stable, volatile) via `_tier_lore_ids` against the session
    baseline — the `partition=` two-call form is retired. Also covers the
    revision-bounded `use(node, hint)` placement prior."""

    def setUp(self) -> None:
        super().setUp()
        self.session = AISession(id="test-scene-one")
        self.scene_one = self.service.read_scene(self.scene_one_node.scene_id)

    def _tier(self, hints: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
        ids = _relevant_lore_ids(self.service, self.scene_one, "implicit")
        return _tier_lore_ids(self.service, ids, self.session, hints)

    def _edit_honor(self, body: str) -> None:
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body=body,
        )

    def test_first_call_everything_is_volatile(self) -> None:
        # Baseline is empty; everything looks new.
        stable, volatile = self._tier()
        self.assertEqual(stable, [])
        self.assertIn(self.honor["id"], volatile)
        self.assertIn(self.nimitz["id"], volatile)

    def test_after_commit_unchanged_entries_are_stable(self) -> None:
        self._tier()
        self.session.commit()
        stable, volatile = self._tier()
        self.assertIn(self.honor["id"], stable)
        self.assertIn(self.nimitz["id"], stable)
        self.assertEqual(volatile, [])

    def test_modified_entry_is_volatile_others_stable(self) -> None:
        self._tier()
        self.session.commit()
        self._edit_honor("Captain of the Fearless. Treecat-adopted. EDITED.")
        stable, volatile = self._tier()
        self.assertIn(self.honor["id"], volatile)  # revision changed
        self.assertNotIn(self.honor["id"], stable)
        self.assertIn(self.nimitz["id"], stable)  # untouched
        self.assertNotIn(self.nimitz["id"], volatile)

    def test_stable_hint_starts_a_new_node_stable(self) -> None:
        # A "stable"-hinted node skips the volatile-first turn (the placement prior).
        stable, volatile = self._tier(hints={self.honor["id"]: "stable"})
        self.assertIn(self.honor["id"], stable)  # hinted → stable on turn 1
        self.assertIn(self.nimitz["id"], volatile)  # unhinted, new → volatile

    def test_stable_hint_still_re_writes_a_changed_node(self) -> None:
        # Revision-bounded: a hinted-stable node that actually changed goes volatile
        # (never rides stale bytes).
        self._tier()
        self.session.commit()
        self._edit_honor("Captain of the Fearless. Treecat-adopted. EDITED.")
        stable, volatile = self._tier(hints={self.honor["id"]: "stable"})
        self.assertIn(self.honor["id"], volatile)  # changed → volatile despite hint
        self.assertNotIn(self.honor["id"], stable)

    def test_volatile_hint_pins_a_settled_node_volatile(self) -> None:
        # A "volatile"-hinted node stays in the 5m tier even once settled.
        self._tier()
        self.session.commit()
        stable, volatile = self._tier(hints={self.honor["id"]: "volatile"})
        self.assertIn(self.honor["id"], volatile)  # pinned volatile
        self.assertIn(self.nimitz["id"], stable)  # unhinted, settled → stable

    def test_relevant_lore_returns_everything_untiered(self) -> None:
        # The untiered form (one-shot / preview) returns all relevant entries.
        text = _relevant_lore(
            self.service, self.scene_one, "implicit", session=self.session
        )
        self.assertIn("Honor Harrington", text)
        self.assertIn("Nimitz", text)

    def test_no_session_relevant_lore_returns_all(self) -> None:
        text = _relevant_lore(self.service, self.scene_one, "implicit")
        self.assertIn("Honor Harrington", text)
        self.assertIn("Nimitz", text)


class HelperIntegrationTests(_HelperFixtureBase):
    def test_full_template_with_multiple_helpers(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}You are a writer.{% endrole %}'
            '{% role "user" %}'
            "POV: {{ pov(scene).title }}\n"
            # ADR-0060 §2: use_lore() selects lore for backend placement and emits
            # nothing inline; story_so_far is a surviving derived-recap emitter.
            "{{ use_lore() }}"
            "Story so far:\n{{ story_so_far(scene) }}"
            "{% endrole %}",
            context={"scene": scene_two},
            env=env,
        )
        self.assertEqual(len(out.messages), 2)
        user_text = out.messages[1].text
        self.assertIn("POV: Honor Harrington", user_text)
        self.assertIn("The Departure", user_text)


class EntryRefTests(_HelperFixtureBase):
    def setUp(self) -> None:
        super().setUp()
        # Link Honor's home_place → Manticore so we have a single-ref to chase.
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
                "home_place": self.manticore["id"],
            },
            body="Captain of the Fearless.",
        )

    def test_entry_helper_returns_ref_with_title(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ entry("' + self.honor["id"] + '").title }}{% endrole %}',
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "Honor Harrington")

    def test_entry_id_exposes_raw_string_without_resolving(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ entry("' + self.honor["id"] + '").id }}{% endrole %}',
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, self.honor["id"])

    def test_entity_ref_field_auto_resolves(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ entry("'
            + self.honor["id"]
            + '").home_place.title }}{% endrole %}',
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "Manticore")

    def test_entity_ref_list_auto_resolves_to_refs(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}'
            '{% for related in entry("' + self.honor["id"] + '").related_entries %}'
            "{{ related.title }};"
            "{% endfor %}"
            "{% endrole %}",
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "Nimitz;")

    def test_unknown_id_resolves_to_falsy_ref(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}'
            '{% if entry("lore_does_not_exist").found %}YES{% else %}NO{% endif %}'
            "{% endrole %}",
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "NO")

    def test_cycle_resolves_through_within_depth_limit(self) -> None:
        # Close the loop: Nimitz related_entries → Honor. Honor → Nimitz already
        # exists from the base fixture. So Honor → Nimitz → Honor is a 2-node
        # cycle via related_entries.
        self._update_lore(
            self.nimitz["id"],
            entry_type="lore:character",
            metadata={"aliases": [], "related_entries": [self.honor["id"]]},
            body="Honor's treecat.",
        )
        env = create_environment_for_project(self.service)
        # Chain hops through the cycle: each resolves to the right title at
        # this depth (well within MAX_DEPTH).
        out = render_template(
            '{% role "user" %}'
            "{{ entry('" + self.honor["id"] + "').related_entries[0].title }}|"
            "{{ entry('"
            + self.honor["id"]
            + "').related_entries[0].related_entries[0].title }}|"
            "{{ entry('"
            + self.honor["id"]
            + "').related_entries[0].related_entries[0].related_entries[0].title }}"
            "{% endrole %}",
            context={},
            env=env,
        )
        parts = out.messages[0].text.split("|")
        self.assertEqual(parts[0], "Nimitz")
        self.assertEqual(parts[1], "Honor Harrington")
        self.assertEqual(parts[2], "Nimitz")

    def test_depth_limit_returns_raw_id_at_truncation(self) -> None:
        # Close the cycle. Then chain exactly _ENTRY_REF_MAX_DEPTH hops; the
        # final EntryRef refuses to load and `.title` falls back to the raw id.
        self._update_lore(
            self.nimitz["id"],
            entry_type="lore:character",
            metadata={"aliases": [], "related_entries": [self.honor["id"]]},
            body="Honor's treecat.",
        )
        env = create_environment_for_project(self.service)
        # 6 hops at depth limit 6 → the 6th EntryRef has depth=6 and refuses.
        chain = "entry('" + self.honor["id"] + "')"
        for _ in range(6):
            chain += ".related_entries[0]"
        out = render_template(
            '{% role "user" %}{{ ' + chain + ".title }}{% endrole %}",
            context={},
            env=env,
        )
        # The cycle alternates honor → nimitz → honor; 6 hops lands on honor.
        text = out.messages[0].text
        self.assertEqual(text, self.honor["id"])


class JsonFilterTests(_HelperFixtureBase):
    """ADR-0060 §7: the one `json` filter — insertion-order-preserving, no
    surprise HTML-escaping (retires `plain_json` / `tojson`)."""

    def test_json_filter_preserves_order_and_does_not_escape(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}{{ value | json }}{% endrole %}',
            context={"value": {"b": 1, "a": "<x> & 'y'"}},
            env=env,
        )
        # Member order preserved (b before a); `<`, `>`, `&`, `'` NOT \uXXXX-escaped
        # the way Jinja's built-in `tojson` would.
        self.assertEqual(out.messages[0].text, '{"b": 1, "a": "<x> & \'y\'"}')


class FullOutlineTests(_HelperFixtureBase):
    def test_returns_act_with_scene_children(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}'
            "{% for top in full_outline() %}"
            "TOP={{ top.title }};"
            "{% for child in top.children %}"
            "CHILD={{ child.title }}/{{ child.summary }};"
            "{% endfor %}"
            "{% endfor %}"
            "{% endrole %}",
            context={},
            env=env,
        )
        text = out.messages[0].text
        self.assertIn("TOP=Act One;", text)
        self.assertIn("CHILD=The Departure/Honor takes the Salamander into battle.;", text)
        self.assertIn("CHILD=The Arrival/", text)


class FullTextTests(_HelperFixtureBase):
    def test_returns_scenes_in_manuscript_order(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}'
            "{% for s in full_text() %}<<{{ s.title }}|{{ s.body|trim }}>>{% endfor %}"
            "{% endrole %}",
            context={},
            env=env,
        )
        text = out.messages[0].text
        # create_project seeds an "Untitled Scene"; the two fixture scenes
        # follow it.
        self.assertIn("<<The Departure|Scene one body.>>", text)
        self.assertIn("<<The Arrival|Scene two body.>>", text)
        self.assertLess(
            text.index("<<The Departure"), text.index("<<The Arrival")
        )


class ContextPresetTests(_HelperFixtureBase):
    def test_full_outline_renders_nested_xml(self) -> None:
        from app.services.ai.context_presets import render_preset

        out = render_preset(self.service, "full_outline")
        self.assertTrue(out.startswith("<outline>"))
        self.assertTrue(out.endswith("</outline>"))
        self.assertIn("Act One", out)
        self.assertIn("The Departure", out)
        self.assertIn("The Arrival", out)
        # Act has children, so it opens and closes (not a self-closing tag).
        self.assertIn("<act title=\"Act One\">", out)
        self.assertIn("</act>", out)
        # Leaf scenes with no children render as self-closing tags.
        self.assertIn("/>", out)

    def test_full_text_renders_scene_bodies(self) -> None:
        from app.services.ai.context_presets import render_preset

        out = render_preset(self.service, "full_text")
        self.assertTrue(out.startswith("<novel_text>"))
        self.assertTrue(out.endswith("</novel_text>"))
        self.assertIn("<scene title=\"The Departure\">", out)
        self.assertIn("Scene one body.", out)
        # Departure precedes Arrival.
        self.assertLess(out.index("The Departure"), out.index("The Arrival"))

    def test_unknown_preset_raises(self) -> None:
        from app.services.ai.context_presets import render_preset

        with self.assertRaises(ValueError):
            render_preset(self.service, "not_a_preset")


class ResearchNoteEntryRefTests(unittest.TestCase):
    """`entry()` Jinja helper resolves picked research notes.

    Covers slice 4 of docs/research-strategy.md: research notes
    participate in the explicit context picker, so a context_pick input
    that resolves to a research note must be readable as an EntryRef in
    templates (title, body, metadata).
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService.created_at(self.root, "Research Helper Tests")
        # Create a research note via the structure CRUD (the route the
        # frontend uses). Capture the leaf's note id from the returned tree.
        tree = self.service.create_research_node(
            CreateStructureNodeRequest(title="Lancashire mill towns", entry_type="research:note")
        )
        leaf = next(child for child in tree.root.children if child.type == "research:note")
        self.note_id = leaf.scene_id
        # Populate the note's body via save_research_note so EntryRef has
        # content to surface.
        from app.models import SaveResearchNoteRequest

        note = self.service.read_research_note(self.note_id)
        self.service.save_research_note(
            self.note_id,
            SaveResearchNoteRequest(
                title="Lancashire mill towns",
                body="Mills employed children from age 8.",
                base_revision=note.revision,
                entry_type="research:note",
                metadata={"tags": ["industrial", "labor"]},
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_entry_resolves_research_note_title(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ entry("' + self.note_id + '").title }}{% endrole %}',
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "Lancashire mill towns")

    def test_entry_resolves_research_note_body(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ entry("'
            + self.note_id
            + '").body }}{% endrole %}',
            context={},
            env=env,
        )
        self.assertIn("Mills employed children from age 8.", out.messages[0].text)

    def test_entry_resolves_research_note_entry_type(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ entry("'
            + self.note_id
            + '").entry_type }}{% endrole %}',
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "research:note")

    def test_entry_resolves_research_note_found(self) -> None:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}'
            '{% if entry("' + self.note_id + '").found %}YES{% else %}NO{% endif %}'
            "{% endrole %}",
            context={},
            env=env,
        )
        self.assertEqual(out.messages[0].text, "YES")


if __name__ == "__main__":
    unittest.main()
