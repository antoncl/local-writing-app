"""`previous_scene(x)` / `next_scene(x)` (#2355): the scene beside a scene or a
plot card in reading order, and the one-scene lookahead it gives the
revise-plot-card prompt's gated board."""

from __future__ import annotations

from _builtins import builtin_prompt_id
from test_ai_plot_context import _PlotAiContextBase

_ADJACENT = '{% role "system" %}[{{ previous_scene(x) or "none" }}|{{ next_scene(x) or "none" }}]{% endrole %}'


class AdjacentSceneHelperTests(_PlotAiContextBase):
    def setUp(self) -> None:
        super().setUp()
        one, two = self._chapter("One"), self._chapter("Two")
        self.a = self._scene("A", one)
        self.b = self._scene("B", one)
        self.c = self._scene("C", two)

    def test_a_scene_sees_its_neighbours_across_a_chapter_boundary(self) -> None:
        self.assertIn("[A|C]", self._render(_ADJACENT, x=self.b))
        self.assertIn("[B|none]", self._render(_ADJACENT, x=self.c))  # the last scene
        # The first scene (the fixture project seeds one before A) has no previous.
        first = self._render('{% role "system" %}{{ previous_scene(x).id }}{% endrole %}', x=self.a).strip()
        self.assertIn("[none|A]", self._render(_ADJACENT, x=first))

    def test_a_card_stands_for_its_attached_scene(self) -> None:
        card = self._card("Turn", scene=self.b)
        self.assertIn("[A|C]", self._render(_ADJACENT, x=card))

    def test_an_unattached_card_or_unknown_id_has_no_neighbours(self) -> None:
        card = self._card("Floating")
        self.assertIn("[none|none]", self._render(_ADJACENT, x=card))
        self.assertIn("[none|none]", self._render(_ADJACENT, x="scene_nope"))

    def test_the_result_is_a_node_a_template_can_read(self) -> None:
        out = self._render('{% role "system" %}{{ next_scene(x).title }}{% endrole %}', x=self.a)
        self.assertIn("B", out)


class RevisePlotCardLookaheadTests(_PlotAiContextBase):
    def _prompt_body(self) -> str:
        return self.service.read_prompt_entry(builtin_prompt_id(self.service, "Revise plot card")).body

    def test_the_prompt_sees_the_next_scenes_card_but_not_beyond(self) -> None:
        chapter = self._chapter()
        s0, s1, s2 = (self._scene(t, chapter) for t in ("s0", "s1", "s2"))
        card = self._card("The turn", body="He decides to leave.", scene=s0)
        self._card("Aftermath", body="NEXT_CARD fallout.", scene=s1)
        self._card("Much later", body="SECRET_FUTURE payoff.", scene=s2)
        out = self._render(self._prompt_body(), inputs={"entry": card})
        self.assertIn("NEXT_CARD", out)  # one scene of lookahead
        self.assertNotIn("SECRET_FUTURE", out)  # still gated past it
        self.assertIn("cards_withheld_ahead", out)

    def test_a_card_on_the_last_scene_falls_back_to_its_own_anchor(self) -> None:
        chapter = self._chapter()
        s0, s1 = self._scene("s0", chapter), self._scene("s1", chapter)
        self._card("Before", body="EARLIER_CARD setup.", scene=s0)
        card = self._card("The end", body="It ends.", scene=s1)
        out = self._render(self._prompt_body(), inputs={"entry": card})
        self.assertIn("EARLIER_CARD", out)
        self.assertIn('completeness="through_as_of"', out)  # gated, not the whole board
