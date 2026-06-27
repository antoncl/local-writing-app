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
from app.services.ai.helpers import (
    create_environment_for_project,
    last_words,
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
        self.root = Path(self.temp_dir.name) / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Helper Tests")
        # Several tests in this file use `home_place` as a convenient
        # single-ref field on Character to exercise EntryRef / ref-graph
        # behaviour. The seed schema no longer ships it (it was test
        # cruft polluting real Character entries) — re-add it locally
        # so the tests stay hermetic.
        self._add_home_place_to_character_schema()

        # Lore: Honor Harrington (character), Manticore (place), Nimitz (character)
        self.honor = self._make_lore(
            title="Honor Harrington",
            entry_type="character",
            metadata={"aliases": ["The Salamander"], "home_place": None},
            body="Captain of the Fearless. Treecat-adopted.",
        )
        self.manticore = self._make_lore(
            title="Manticore",
            entry_type="place",
            metadata={"aliases": ["Star Kingdom"]},
            body="A binary star system; the capital world of the Star Kingdom.",
        )
        self.nimitz = self._make_lore(
            title="Nimitz",
            entry_type="character",
            metadata={"aliases": []},
            body="Honor's treecat companion.",
        )
        # Link Honor → Nimitz via related_entries (the ref graph hop)
        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless. Treecat-adopted.",
        )

        # Manuscript structure: Act → Scene 1, Scene 2
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        self.act_node = next(c for c in structure.root.children if c.type == "act")
        s1 = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Departure", entry_type="scene", parent_id=self.act_node.id
            )
        )
        self.scene_one_node = self._latest_scene_under(s1.root, self.act_node.id)
        s2 = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="The Arrival", entry_type="scene", parent_id=self.act_node.id
            )
        )
        self.scene_two_node = self._latest_scene_under(s2.root, self.act_node.id)

        # Populate scene_one with a summary mentioning Honor (alias) + characters list
        self._update_scene(
            self.scene_one_node.scene_id,
            title="The Departure",
            entry_type="scene",
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
            entry_type="scene",
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

    def _add_home_place_to_character_schema(self) -> None:
        """Inject a `home_place: entity_ref(place)` field onto Character
        in the project's schema. Used by tests that need a single-ref
        field on Character to test EntryRef / ref-graph machinery.
        Writes directly to the schema YAML rather than going through the
        upsert APIs to keep setup terse."""
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["home_place"] = {
            "name": "Home Place",
            "type": "entity_ref",
            "target": {"entry_type": "place"},
        }
        character = data["entry_types"].get("character") or {}
        fields = list(character.get("fields") or [])
        if "home_place" not in fields:
            fields.insert(0, "home_place")
            character["fields"] = fields
            data["entry_types"]["character"] = character
        self.service._write_yaml(schema_path, data)

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
                body_markdown=body,
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
                body_markdown=body,
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


class ScenesBeforeHelperTests(_HelperFixtureBase):
    def test_collects_summaries_of_prior_scenes_only(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ scenes_before(scene) }}{% endrole %}',
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
            '{% role "user" %}{{ scenes_before(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        self.assertEqual(out.messages, [])


class RelevantLoreHelperTests(_HelperFixtureBase):
    def test_implicit_finds_alias_match_and_one_hop(self) -> None:
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        text = out.messages[0].text
        # Honor — direct ref via 'characters' field
        self.assertIn("Honor Harrington", text)
        # Nimitz — one-hop expansion through Honor's related_entries
        self.assertIn("Nimitz", text)

    def test_implicit_alias_only_match(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_two},
            env=env,
        )
        text = out.messages[0].text
        # 'Star Kingdom' alias for Manticore appears in the summary
        self.assertIn("Manticore", text)

    def test_explicit_skips_alias_scan(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene, "explicit") }}{% endrole %}',
            context={"scene": scene_two},
            env=env,
        )
        text = out.messages[0].text
        # Scene two has no characters in its list and Manticore is alias-only
        self.assertNotIn("Manticore", text)
        # But pov is an entity_ref → Honor should be picked up
        self.assertIn("Honor Harrington", text)

    def test_implicit_finds_textual_one_hop_in_body(self) -> None:
        # Add a third character not referenced by anyone, then mention him
        # textually in Honor's body. Textual depth-1 should pull him in
        # even though no entity_ref links Honor → Pavel.
        pavel = self._make_lore(
            title="Pavel Young",
            entry_type="character",
            metadata={"aliases": []},
            body="Captain who hates Honor.",
        )
        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],  # NOT Pavel
            },
            body="Captain of the Fearless. Treecat-adopted. Rival of Pavel Young.",
        )

        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        text = out.messages[0].text
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
        anders = self._make_lore(
            title="Anders Pierce",
            entry_type="character",
            metadata={"aliases": []},
            body="Some other captain.",
        )
        pavel = self._make_lore(
            title="Pavel Young",
            entry_type="character",
            metadata={"aliases": []},
            body="Captain. Friend of Anders Pierce.",  # mentions Anders
        )
        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless. Rival of Pavel Young.",  # mentions Pavel
        )

        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        text = out.messages[0].text
        # Check entity inclusion by the rendered XML tag, not raw substring —
        # Pavel's body literally contains "Anders Pierce" as prose.
        self.assertIn('name="Honor Harrington"', text)
        self.assertIn('name="Pavel Young"', text)        # depth 1: yes
        self.assertNotIn('name="Anders Pierce"', text)   # depth 2: stop

    def test_journal_mode_trusts_journal_skips_alias_scan(self) -> None:
        # When a journal is bound, the helper does NOT rescan the scene
        # summary — it uses the journal as source of truth for detected
        # context. Scene one's summary mentions Honor's alias "Salamander",
        # but with an EMPTY journal we should only get the structural
        # entity_ref picks (characters: [Honor]).
        from app.models import ChatSessionJournalEntry
        from app.services.ai.helpers import create_environment_for_project

        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service, journal=[])
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        text = out.messages[0].text
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
        from app.services.ai.helpers import create_environment_for_project

        # Manticore is not referenced or mentioned in scene one's summary
        # ("Honor takes the Salamander into battle.") nor in Honor's metadata.
        # Adding it to the journal forces it into scope.
        journal = [
            ChatSessionJournalEntry(
                entry_id=self.manticore["id"],
                title="Manticore",
                entry_type="place",
                added_at_turn=2,
                source="user_message",
            )
        ]
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service, journal=journal)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        text = out.messages[0].text
        self.assertIn("Honor Harrington", text)  # structural
        self.assertIn("Nimitz", text)            # structural one-hop
        self.assertIn("Manticore", text)         # via journal

    def test_journal_mode_skips_textual_one_hop(self) -> None:
        # Without journal: textual depth-1 fires (we just added it in step 1).
        # With journal: textual depth-1 is skipped — the send-time pipeline
        # is supposed to have done that already and put results into journal.
        from app.services.ai.helpers import create_environment_for_project

        # Add Pavel; mention him in Honor's body. Without journal, Pavel
        # would arrive via textual depth-1. With empty journal, he should NOT.
        pavel = self._make_lore(
            title="Pavel Young",
            entry_type="character",
            metadata={"aliases": []},
            body="Disgraced Captain.",
        )
        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless. Rival of Pavel Young.",
        )

        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service, journal=[])
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        text = out.messages[0].text
        self.assertIn('name="Honor Harrington"', text)
        self.assertIn('name="Nimitz"', text)
        # Pavel was found via textual depth-1 in journal=None mode, but with
        # an explicit empty journal the helper trusts that signal: send-time
        # would have added Pavel to the journal if it wanted him.
        self.assertNotIn('name="Pavel Young"', text)

    def test_pinned_only_returns_empty(self) -> None:
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene, "pinned_only") }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        # No pinning machinery yet → empty body → no message.
        self.assertEqual(out.messages, [])


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
                body_markdown=existing.body_markdown,
                base_revision=existing.revision,
                entry_type=existing.entry_type,
                metadata=metadata,
            ),
        )

    def _render_scene_one(self) -> str:
        scene_one = self.service.read_scene(self.scene_one_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene_one},
            env=env,
        )
        return out.messages[0].text if out.messages else ""

    def test_always_policy_unioned_into_implicit_render(self) -> None:
        # A character that's NOT referenced by scene_one and whose name is
        # NOT in the summary. Default would be excluded; "always" pulls in.
        pavel = self._make_lore(
            title="Pavel Young",
            entry_type="character",
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
            entry_type="scene",
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
        # manual_only still respects explicit picks. Ref Manticore via a
        # `locations` entity_ref_list on scene_one.
        self._set_policy(self.manticore["id"], "manual_only")
        self._update_scene(
            self.scene_one_node.scene_id,
            title="The Departure",
            entry_type="scene",
            metadata={
                "summary": "Honor takes the Salamander into battle.",
                "characters": [self.honor["id"]],
                "locations": [self.manticore["id"]],
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


class SessionPartitionTests(_HelperFixtureBase):
    def setUp(self) -> None:
        super().setUp()
        self.session = AISession(id="test-scene-one")
        self.scene_one = self.service.read_scene(self.scene_one_node.scene_id)

    def _render_with_partition(self, partition: str) -> str:
        env = create_environment_for_project(self.service, session=self.session)
        source = (
            '{% role "user" %}{{ relevant_lore(scene, "implicit", "'
            + partition
            + '") }}{% endrole %}'
        )
        out = render_template(source, context={"scene": self.scene_one}, env=env)
        return out.messages[0].text if out.messages else ""

    def test_first_call_everything_is_volatile(self) -> None:
        # Baseline is empty; everything looks new.
        stable = self._render_with_partition("stable")
        volatile = self._render_with_partition("volatile")
        self.assertEqual(stable, "")
        self.assertIn("Honor Harrington", volatile)
        self.assertIn("Nimitz", volatile)

    def test_after_commit_unchanged_entries_are_stable(self) -> None:
        # First call records revisions; commit promotes them to baseline.
        self._render_with_partition("all")
        self.session.commit()

        # Second call with no edits between → everything stable.
        stable = self._render_with_partition("stable")
        volatile = self._render_with_partition("volatile")
        self.assertIn("Honor Harrington", stable)
        self.assertIn("Nimitz", stable)
        self.assertEqual(volatile, "")

    def test_modified_entry_partitions_volatile_others_stable(self) -> None:
        self._render_with_partition("all")
        self.session.commit()

        # Edit Honor's body; her revision changes, Nimitz's doesn't.
        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless. Treecat-adopted. EDITED.",
        )

        stable = self._render_with_partition("stable")
        volatile = self._render_with_partition("volatile")
        # Honor is volatile (her revision changed)
        self.assertIn("Honor Harrington", volatile)
        self.assertNotIn("Honor Harrington", stable)
        # Nimitz is stable (untouched)
        self.assertIn("Nimitz", stable)
        self.assertNotIn("Nimitz", volatile)

    def test_partition_all_returns_everything_regardless_of_baseline(self) -> None:
        self._render_with_partition("all")
        self.session.commit()

        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="A totally different body.",
        )

        all_text = self._render_with_partition("all")
        self.assertIn("Honor Harrington", all_text)
        self.assertIn("Nimitz", all_text)

    def test_no_session_ignores_partition(self) -> None:
        # No session bound to env → partition param is meaningless but must not crash.
        env = create_environment_for_project(self.service, session=None)
        out_stable = render_template(
            '{% role "user" %}{{ relevant_lore(scene, "implicit", "stable") }}{% endrole %}',
            context={"scene": self.scene_one},
            env=env,
        )
        out_volatile = render_template(
            '{% role "user" %}{{ relevant_lore(scene, "implicit", "volatile") }}{% endrole %}',
            context={"scene": self.scene_one},
            env=env,
        )
        # No session → all entries returned, partition ignored.
        self.assertIn("Honor Harrington", out_stable.messages[0].text)
        self.assertIn("Honor Harrington", out_volatile.messages[0].text)


class XmlOutputStructureTests(_HelperFixtureBase):
    def _render_lore(self, scene_attr: str) -> str:
        scene = self.service.read_scene(getattr(self, scene_attr).scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ relevant_lore(scene) }}{% endrole %}',
            context={"scene": scene},
            env=env,
        )
        return out.messages[0].text

    def test_lore_block_wraps_in_lore_tag(self) -> None:
        text = self._render_lore("scene_one_node")
        self.assertTrue(text.startswith("<lore>"), text[:40])
        self.assertTrue(text.rstrip().endswith("</lore>"), text[-40:])

    def test_lore_entry_uses_entry_type_as_tag(self) -> None:
        text = self._render_lore("scene_one_node")
        # Honor + Nimitz are characters
        self.assertIn('<character name="Honor Harrington"', text)
        self.assertIn('<character name="Nimitz"', text)
        # And properly closed
        self.assertIn("</character>", text)

    def test_aliases_appear_as_attribute(self) -> None:
        text = self._render_lore("scene_one_node")
        self.assertIn('aliases="The Salamander"', text)

    def test_no_aliases_attribute_when_empty(self) -> None:
        text = self._render_lore("scene_one_node")
        # Nimitz has no aliases set — the tag should still appear but without aliases=
        nimitz_block = text[text.index("Nimitz") - 20:text.index("Nimitz") + 80]
        self.assertNotIn("aliases=", nimitz_block)

    def test_body_is_xml_escaped(self) -> None:
        # Edit Honor's body to contain & (the XML-special character that prose
        # legitimately contains — the markdown validator blocks raw HTML so
        # we can't test angle brackets through the normal path).
        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
            },
            body="Captain of the Fearless & treecat-adopted.",
        )
        text = self._render_lore("scene_one_node")
        self.assertIn("&amp;", text)
        self.assertNotIn(" & treecat", text)

    def test_title_with_special_chars_is_attribute_escaped(self) -> None:
        # Title with a double-quote forces quoteattr to switch to single-quoting
        self._update_lore(
            self.honor["id"],
            entry_type="character",
            metadata={"aliases": []},
            body="body",
        )
        existing = self.service.read_lore_entry(self.honor["id"])
        self.service.save_lore_entry(
            self.honor["id"],
            SaveLoreEntryRequest(
                title='Honor "The Salamander" Harrington',
                body_markdown="body",
                base_revision=existing.revision,
                entry_type="character",
                metadata={"aliases": []},
            ),
        )
        text = self._render_lore("scene_one_node")
        # quoteattr will pick whichever quote character avoids the conflict
        self.assertTrue(
            "Honor &quot;The Salamander&quot; Harrington" in text
            or "Honor \"The Salamander\" Harrington" in text,
            text,
        )

    def test_scenes_before_wraps_in_story_so_far(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ scenes_before(scene) }}{% endrole %}',
            context={"scene": scene_two},
            env=env,
        )
        text = out.messages[0].text
        self.assertTrue(text.startswith("<story_so_far>"), text[:40])
        self.assertTrue(text.rstrip().endswith("</story_so_far>"), text[-40:])
        self.assertIn('<scene title="The Departure">', text)
        self.assertIn("</scene>", text)


class HelperIntegrationTests(_HelperFixtureBase):
    def test_full_template_with_multiple_helpers(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}You are a writer.{% endrole %}'
            '{% role "user" %}'
            "POV: {{ pov(scene).title }}\n"
            "{{ relevant_lore(scene) }}\n"
            "Story so far:\n{{ scenes_before(scene) }}"
            "{% endrole %}",
            context={"scene": scene_two},
            env=env,
        )
        self.assertEqual(len(out.messages), 2)
        user_text = out.messages[1].text
        self.assertIn("POV: Honor Harrington", user_text)
        self.assertIn("Manticore", user_text)
        self.assertIn("The Departure", user_text)


class EntryRefTests(_HelperFixtureBase):
    def setUp(self) -> None:
        super().setUp()
        # Link Honor's home_place → Manticore so we have a single-ref to chase.
        self._update_lore(
            self.honor["id"],
            entry_type="character",
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
            entry_type="character",
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
            entry_type="character",
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
        self.root = Path(self.temp_dir.name) / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Research Helper Tests")
        # Create a research note via the structure CRUD (the route the
        # frontend uses). Capture the leaf's note id from the returned tree.
        tree = self.service.create_research_node(
            CreateStructureNodeRequest(title="Lancashire mill towns", entry_type="note")
        )
        leaf = next(child for child in tree.root.children if child.type == "note")
        self.note_id = leaf.scene_id
        # Populate the note's body via save_research_note so EntryRef has
        # content to surface.
        from app.models import SaveResearchNoteRequest

        note = self.service.read_research_note(self.note_id)
        self.service.save_research_note(
            self.note_id,
            SaveResearchNoteRequest(
                title="Lancashire mill towns",
                body_markdown="Mills employed children from age 8.",
                base_revision=note.revision,
                entry_type="note",
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
            + '").body_markdown }}{% endrole %}',
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
        self.assertEqual(out.messages[0].text, "note")

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
