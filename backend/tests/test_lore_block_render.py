"""XML-output structure tests for the node/lore context renderer (`lore_block.py`).

Split out of `test_ai_helpers.py` when the #1230 field-rendering tests pushed
that file past the 1500-line guard. Reuses its `_HelperFixtureBase` (one act,
two scenes, a few linked lore entries) — the same cross-test-module reuse the
suite already does elsewhere.
"""
from __future__ import annotations

from test_ai_helpers import _HelperFixtureBase

from app.models import SaveLoreEntryRequest
from app.services.ai.helpers import _relevant_lore, create_environment_for_project
from app.services.ai.templates import render_template


class XmlOutputStructureTests(_HelperFixtureBase):
    def _render_lore(self, scene_attr: str) -> str:
        scene = self.service.read_scene(getattr(self, scene_attr).scene_id)
        return _relevant_lore(self.service, scene)

    def test_lore_block_wraps_in_lore_tag(self) -> None:
        text = self._render_lore("scene_one_node")
        self.assertTrue(text.startswith("<lore>"), text[:40])
        self.assertTrue(text.rstrip().endswith("</lore>"), text[-40:])

    def test_lore_entry_uses_entry_type_as_tag(self) -> None:
        text = self._render_lore("scene_one_node")
        # Honor + Nimitz are characters. Each block leads with its own `id` (the
        # join key #1230 added) followed by the `name` attribute.
        self.assertIn(f'<character id="{self.honor["id"]}" name="Honor Harrington"', text)
        self.assertIn(f'<character id="{self.nimitz["id"]}" name="Nimitz"', text)
        # And properly closed
        self.assertIn("</character>", text)

    def test_aliases_appear_as_attribute(self) -> None:
        text = self._render_lore("scene_one_node")
        self.assertIn('aliases="The Salamander"', text)

    def test_no_aliases_attribute_when_empty(self) -> None:
        text = self._render_lore("scene_one_node")
        # Nimitz has no aliases set — the tag should still appear but without aliases=
        nimitz_open = text.index('<character id="' + self.nimitz["id"])
        nimitz_block = text[nimitz_open:nimitz_open + 120]
        self.assertNotIn("aliases=", nimitz_block)

    def test_every_block_carries_its_own_id(self) -> None:
        # #1230: every block advertises its id — the stable join key a reference
        # in another block correlates against.
        text = self._render_lore("scene_one_node")
        self.assertIn(f'<character id="{self.honor["id"]}"', text)
        self.assertIn(f'<character id="{self.nimitz["id"]}"', text)

    def test_entity_ref_field_renders_as_name_and_id(self) -> None:
        # A single entity_ref (home_place → Manticore) renders as a child element
        # carrying the target's legible name AND its id join key (#1230).
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={"aliases": ["The Salamander"], "home_place": self.manticore["id"]},
            body="Captain of the Fearless.",
        )
        text = self._render_lore("scene_one_node")
        self.assertIn(
            f'<home_place id="{self.manticore["id"]}">Manticore</home_place>', text
        )

    def test_entity_ref_list_renders_each_target_with_id(self) -> None:
        # related_entries (entity_ref_list) → a block of <entry id=...>Name</entry>.
        text = self._render_lore("scene_one_node")
        self.assertIn("<related_entries>", text)
        self.assertIn(f'<entry id="{self.nimitz["id"]}">Nimitz</entry>', text)

    def test_author_only_knob_is_not_rendered(self) -> None:
        # context_policy is ai_proposable:false — a caching/visibility knob about
        # the entry, not story content — so it never reaches the model even when
        # explicitly set (#1230's "which fields" rule, kept general not by-name).
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
            metadata={
                "aliases": ["The Salamander"],
                "related_entries": [self.nimitz["id"]],
                "context_policy": "always",
            },
            body="Captain of the Fearless.",
        )
        text = self._render_lore("scene_one_node")
        self.assertNotIn("context_policy", text)

    def test_body_is_xml_escaped(self) -> None:
        # Edit Honor's body to contain & (the XML-special character that prose
        # legitimately contains — the markdown validator blocks raw HTML so
        # we can't test angle brackets through the normal path).
        self._update_lore(
            self.honor["id"],
            entry_type="lore:character",
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
            entry_type="lore:character",
            metadata={"aliases": []},
            body="body",
        )
        existing = self.service.read_lore_entry(self.honor["id"])
        self.service.save_lore_entry(
            self.honor["id"],
            SaveLoreEntryRequest(
                title='Honor "The Salamander" Harrington',
                body="body",
                base_revision=existing.revision,
                entry_type="lore:character",
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

    def test_story_so_far_wraps_in_story_so_far(self) -> None:
        scene_two = self.service.read_scene(self.scene_two_node.scene_id)
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ story_so_far(scene) }}{% endrole %}',
            context={"scene": scene_two},
            env=env,
        )
        text = out.messages[0].text
        self.assertTrue(text.startswith("<story_so_far>"), text[:40])
        self.assertTrue(text.rstrip().endswith("</story_so_far>"), text[-40:])
        self.assertIn('<scene title="The Departure">', text)
        self.assertIn("</scene>", text)
