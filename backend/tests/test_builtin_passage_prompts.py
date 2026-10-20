"""#2565: the built-in prompts that rewrite a selected passage in place —
Expand, Describe and Rephrase — see the prose around the passage and the lore
it names, through the shared "Passage context" snippet, and Expand takes a
length.

Rendered through the preview path (the send path's assembly) against a scene,
so the snippet's `use()` picks land where a real run would put them.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _builtins import builtin_prompt_id
from project_fixtures import open_test_project

REWRITE_TITLES = ("Expand", "Describe", "Rephrase")
MARKER = "<!-- mutate:set=ms_1;id=a1 -->"


class PassagePromptTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Passage Tests")
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Opening", entry_type="manuscript:scene")
        )
        self.scene_id = next(c.scene_id for c in structure.root.children if c.title == "Opening")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _prompt(self, title: str):
        return self.service.read_prompt_entry(builtin_prompt_id(self.service, title))

    def _preview(
        self,
        title: str,
        selection: str,
        text_before: str = "",
        text_after: str = "",
        inputs: dict | None = None,
    ):
        from app.services.ai.preview import PreviewRequest, build_preview

        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self._prompt(title).body,
                target_scene_id=self.scene_id,
                session_id=None,
                inputs=inputs or {},
                selection=selection,
                text_before=text_before,
                text_after=text_after,
                commit=False,
            ),
        )
        return rendered, "\n".join(m.text for m in rendered.messages)

    def _lore(self, title: str, entry_type: str = "lore:note"):
        from app.models import CreateLoreEntryRequest

        return self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type=entry_type, body=f"About {title}.")
        )

    # ── Expand's length and direction ────────────────────────────────────────

    def test_expand_offers_a_length_choice_and_a_direction(self) -> None:
        inputs = {i.name: i for i in self._prompt("Expand").inputs}
        self.assertEqual(inputs["amount"].type, "select")
        self.assertEqual([o.value for o in inputs["amount"].options], ["1.5", "2", "3"])
        self.assertEqual(inputs["amount"].default, "2")
        self.assertEqual(inputs["note"].type, "long_text")

    def test_expand_aims_at_a_multiple_of_the_passage_length(self) -> None:
        passage = "The rain fell on the deck."  # 6 words
        _, text = self._preview("Expand", passage)
        self.assertIn("It is 6 words; rewrite it at about 12 words.", text)  # default: double
        _, text = self._preview("Expand", passage, inputs={"amount": "3"})
        self.assertIn("rewrite it at about 18 words.", text)
        _, text = self._preview("Expand", passage, inputs={"amount": "1.5"})
        self.assertIn("rewrite it at about 9 words.", text)

    def test_expand_rounds_a_long_target_to_ten_words(self) -> None:
        passage = " ".join(f"w{i}" for i in range(57))  # 57 × 2 = 114
        _, text = self._preview("Expand", passage)
        self.assertIn("It is 57 words; rewrite it at about 110 words.", text)

    def test_expand_shows_the_direction_only_when_given(self) -> None:
        _, text = self._preview("Expand", "The rain fell.", inputs={"note": "Make it colder."})
        self.assertIn("## Direction\nMake it colder.", text)
        _, text = self._preview("Expand", "The rain fell.")
        self.assertNotIn("## Direction", text)

    # ── The passage in its place ─────────────────────────────────────────────

    def test_rewrites_show_the_prose_around_the_passage_as_context(self) -> None:
        for title in REWRITE_TITLES:
            with self.subTest(title):
                _, text = self._preview(
                    title,
                    "The rain fell on the deck.",
                    text_before=f"She crossed the bridge{MARKER} at dusk.",
                    text_after="The admiral was waiting.",
                )
                before = text.index("## The text before the passage")
                after = text.index("## The text after the passage")
                passage = text.index("## The passage")
                self.assertLess(before, after)
                self.assertLess(after, passage)
                self.assertIn("She crossed the bridge at dusk.", text)
                self.assertIn("The admiral was waiting.", text)
                self.assertNotIn("mutate:", text)  # markers are not story text
                self.assertTrue(text.rstrip().endswith("The rain fell on the deck."), title)

    def test_rewrites_without_text_around_have_no_context_sections(self) -> None:
        for title in REWRITE_TITLES:
            with self.subTest(title):
                _, text = self._preview(title, "The rain fell on the deck.")
                self.assertNotIn("The text before the passage", text)
                self.assertNotIn("The text after the passage", text)
                self.assertIn("## The passage", text)

    def test_rewrites_keep_only_the_tail_of_a_long_lead_in(self) -> None:
        before = " ".join(f"w{i}" for i in range(1000))
        _, text = self._preview("Rephrase", "The rain fell.", text_before=before)
        self.assertIn("w999", text)
        self.assertIn("w600", text)
        self.assertNotIn("w599 ", text)

    # ── Lore ─────────────────────────────────────────────────────────────────

    def test_rewrites_place_the_lore_the_passage_names(self) -> None:
        ravenmoor = self._lore("Ravenmoor")
        elsewhere = self._lore("Elsewhere")
        for title in REWRITE_TITLES:
            with self.subTest(title):
                rendered, _ = self._preview(title, "Ravenmoor was cold.")
                self.assertIn(ravenmoor.id, rendered.used_node_ids)
                self.assertNotIn(elsewhere.id, rendered.used_node_ids)

    def test_rewrites_place_the_point_of_view_character(self) -> None:
        from app.models import SaveSceneRequest

        honor = self._lore("Honor", entry_type="lore:character")
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"pov": honor.id},
            ),
        )
        for title in REWRITE_TITLES:
            with self.subTest(title):
                rendered, _ = self._preview(title, "The rain fell.")  # names no one
                self.assertIn(honor.id, rendered.used_node_ids)


if __name__ == "__main__":
    unittest.main()
