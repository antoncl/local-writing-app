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


if __name__ == "__main__":
    unittest.main()
