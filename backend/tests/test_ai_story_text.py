"""#2427: a body rendered for a model is story text — the app's HTML-comment
markers never reach it — while the roleplay helpers still decode the RAW body."""

from __future__ import annotations

from test_ai_helpers import _HelperFixtureBase

from app.services.ai.entry_ref import EntryRef
from app.services.ai.helpers import (
    _character_turns,
    _roleplay_beats,
    create_environment_for_project,
)
from app.services.ai.lore_block import _format_lore_block
from app.services.ai.templates import render_template

_HONOR_INTERNAL = "c2VjcmV0"  # url-encoded payload of a beat's private interiority
_MARKED = (
    "Dawn <!-- mutate:set=mutation_set_1;id=a1 -->broke.\n\n"
    f"<!-- character:id=ID;internal={_HONOR_INTERNAL} -->She spoke.<!-- /character -->\n\n"
    "<!-- embedded-todo:id=t1 -->Anchored<!-- /embedded-todo --> end."
)


class StoryTextTests(_HelperFixtureBase):
    def _save_marked_scene(self) -> str:
        scene_id = self.scene_one_node.scene_id
        self._update_scene(
            scene_id,
            title="The Departure",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [self.honor["id"]]},
            body=_MARKED.replace("ID", self.honor["id"]),
        )
        return scene_id

    def _render(self, template: str, **context: object) -> str:
        env = create_environment_for_project(self.service)
        return render_template(template, context=context, env=env).messages[0].text

    def _assert_story_text(self, text: str) -> None:
        self.assertNotIn("<!--", text)
        self.assertNotIn("internal=", text)
        self.assertNotIn(_HONOR_INTERNAL, text)
        self.assertIn("Dawn broke.", text)
        self.assertIn("She spoke.", text)
        self.assertIn("Anchored end.", text)

    def test_scene_body_is_story_text(self) -> None:
        scene_id = self._save_marked_scene()
        scene = EntryRef(self.service, None, scene_id)
        out = self._render('{% role "user" %}{{ scene.body }}{% endrole %}', scene=scene)
        self._assert_story_text(out)

    def test_entry_ref_body_is_story_text_for_lore_too(self) -> None:
        self._update_lore(
            self.manticore["id"],
            entry_type="lore:location",
            metadata={"aliases": []},
            body="A <!-- hidden -->star system.",
        )
        out = self._render(
            '{% role "user" %}{{ entry("' + self.manticore["id"] + '").body }}{% endrole %}'
        )
        self.assertEqual(out.strip(), "A star system.")

    def test_full_text_is_story_text(self) -> None:
        self._save_marked_scene()
        out = self._render(
            '{% role "user" %}{% for s in full_text() %}{{ s.body }}{% endfor %}{% endrole %}'
        )
        self._assert_story_text(out)

    def test_lore_block_body_is_story_text(self) -> None:
        self._update_lore(
            self.manticore["id"],
            entry_type="lore:location",
            metadata={"aliases": []},
            body="A <!-- mutate:id=z -->star system.",
        )
        block = _format_lore_block(self.service, [self.manticore["id"]])
        self.assertIn("A star system.", block)
        self.assertNotIn("<!--", block)

    def test_roleplay_helpers_decode_the_raw_body_of_an_entry_ref(self) -> None:
        # Regression guard: `.body` is now stripped, so the helpers must read the
        # raw body of an EntryRef or every beat is lost.
        scene_id = self._save_marked_scene()
        ref = EntryRef(self.service, None, scene_id)

        beats = _roleplay_beats(self.service, ref)
        self.assertIn("[Honor Harrington] She spoke.", beats)
        self.assertIn("[Honor Harrington — interiority]", beats)
        self.assertIn("[Narration] Dawn broke.", beats)
        self.assertNotIn("<!--", beats)

        turns = _character_turns(self.service, None, ref, self.honor["id"])
        self.assertIn("She spoke.", turns)
        self.assertIn("[[interiority]]", turns)  # the focus character's own, decoded
        self.assertIn("Dawn broke.", turns)
        self.assertNotIn("<!--", turns)
        self.assertNotIn("internal=", turns)

    def test_roleplay_beats_without_character_markers_is_story_text(self) -> None:
        self.assertEqual(
            _roleplay_beats(self.service, {"body": "Plain <!-- mutate:x -->text."}),
            "Plain text.",
        )
