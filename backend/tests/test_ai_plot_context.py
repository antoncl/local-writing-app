"""The plot-card brainstorm's context surface (ADR-0048 S8b).

Two layers: the `plot_context` Jinja helper + its formatter (the spoiler-gated
board block a prompt drops in), and the `revise-plot-card` builtin prompt that
uses it (a `plot:card` entry_patch brainstorm — the ADR-0046 loop on a card).
These prove the block renders + gates, the prompt ships and routes as `entry_patch`,
and a returned patch validates for a card.
"""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    CreateCardRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    SaveCardRequest,
)
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.templates import render_template

_THREE_ACT = "builtin-plot-three-act-story-arc"
_PROMPT_ID = "builtin-revise-plot-card"


class _PlotAiContextBase(PlotTestCase):
    def _chapter(self, title: str = "Chapter") -> str:
        root = self.service.read_structure().root.id
        self.service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type="scene:chapter", parent_id=root)
        )
        return next(
            c.id
            for c in self.service.read_structure().root.children
            if c.type == "scene:chapter" and c.title == title
        )

    def _scene(self, title: str, chapter_id: str) -> str:
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=chapter_id)).id

    def _card(self, title: str, *, body: str = "", **metadata: object) -> str:
        card = self.service.create_card(CreateCardRequest(title=title))
        self.service.save_card(card.id, SaveCardRequest(title=title, body=body, metadata=dict(metadata)))
        return card.id

    def _arc(self):
        return self.service.instantiate_plot_template(_THREE_ACT)

    def _render(self, template: str, **context: object) -> str:
        env = create_environment_for_project(self.service)
        return render_template(template, context=context, env=env).messages[0].text


class PlotContextHelperTests(_PlotAiContextBase):
    def test_the_block_carries_arcs_cards_and_synopsis(self) -> None:
        arc = self._arc()
        first_beat = arc.metadata["instance_beats"][0]["id"]
        chapter = self._chapter()
        scene = self._scene("Opening", chapter)
        self._card(
            "They Meet",
            body="She spills his coffee.",
            scene=scene,
            beat_links=[{"instance": arc.id, "beat_id": first_beat}],
        )
        out = self._render('{% role "system" %}{{ plot_context() }}{% endrole %}')
        self.assertIn("<plot_context", out)
        self.assertIn('completeness="whole_board"', out)
        self.assertIn(arc.title, out)  # the arc appears with its roster
        self.assertIn("They Meet", out)
        self.assertIn("She spills his coffee.", out)  # the synopsis is the reasoning stand-in
        self.assertIn("<fulfils", out)  # the card names the beat it fulfils

    def test_it_gates_on_as_of_and_does_not_leak_a_later_card(self) -> None:
        chapter = self._chapter()
        s0, s1 = self._scene("s0", chapter), self._scene("s1", chapter)
        early = self._card("Early", body="An early scene.", scene=s0)
        self._card("Later", body="SECRET_FUTURE payoff.", scene=s1)
        out = self._render(
            '{% role "system" %}{{ plot_context(as_of=anchor) }}{% endrole %}', anchor=early
        )
        self.assertIn('completeness="through_as_of"', out)
        self.assertIn("cards_withheld_ahead", out)
        self.assertIn("Early", out)
        self.assertNotIn("SECRET_FUTURE", out)  # the future card is withheld, not leaked

    def test_an_unknown_anchor_degrades_to_whole_board(self) -> None:
        out = self._render(
            '{% role "system" %}{{ plot_context(as_of="plot_nope") }}{% endrole %}'
        )
        self.assertIn('completeness="whole_board"', out)  # no crash, no gate

    def test_the_block_renders_plotline_causal_and_beat_guidance(self) -> None:
        from app.models import (
            CreatePlotlineRequest,
            CreateTemplateInstanceRequest,
            SaveTemplateInstanceRequest,
        )

        # An ad-hoc arc with a beat carrying GUIDANCE (shipped template beats carry
        # only `function`), so the guidance-as-element branch is exercised.
        arc = self.service.create_template_instance(CreateTemplateInstanceRequest(title="Custom"))
        self.service.save_template_instance(
            arc.id,
            SaveTemplateInstanceRequest(
                title="Custom",
                body="",
                metadata={"instance_beats": [{"title": "Spark", "function": "ignite", "guidance": "GUIDANCE_TEXT"}]},
            ),
        )
        plotline = self.service.create_plotline(CreatePlotlineRequest(title="Romance"))
        chapter = self._chapter()
        s0, s1 = self._scene("s0", chapter), self._scene("s1", chapter)
        effect = self._card("Effect", scene=s1)
        self._card("Cause", scene=s0, plotline=plotline.id, causal_links=[{"target": effect}])
        out = self._render('{% role "system" %}{{ plot_context() }}{% endrole %}')
        self.assertIn('plotline="Romance"', out)  # the card carries its plotline title
        self.assertIn('<leads_to card="Effect"', out)  # the causal edge, title-resolved
        self.assertIn("GUIDANCE_TEXT", out)  # beat guidance renders as element text
        self.assertIn("</beat>", out)  # a beat with guidance is an element, not self-closing


class RevisePlotCardPromptTests(_PlotAiContextBase):
    def test_the_prompt_ships_in_the_library_as_an_entry_patch_brainstorm(self) -> None:
        entries = {e.id: e for e in self.service.list_prompt_entries().entries}
        self.assertIn(_PROMPT_ID, entries)
        self.assertEqual(entries[_PROMPT_ID].entry_type, "prompt:revise:plot_card")
        schema = self.service.read_metadata_schema()
        output = schema.entry_types["prompt:revise:plot_card"].prompt.context_strategy.output
        kind = output["kind"] if isinstance(output, dict) else output.kind
        self.assertEqual(kind, "entry_patch")

    def test_the_prompt_body_renders_the_gated_context_for_its_card(self) -> None:
        chapter = self._chapter()
        s0, s1 = self._scene("s0", chapter), self._scene("s1", chapter)
        card = self._card("The turn", body="He decides to leave.", scene=s0)
        self._card("Aftermath", body="SECRET_FUTURE fallout.", scene=s1)
        body = self.service.read_prompt_entry(_PROMPT_ID).body
        out = self._render(body, input={"entry": card})
        self.assertIn("The turn", out)  # the card under revision
        self.assertIn("<plot_context", out)  # the board block is injected
        self.assertNotIn("SECRET_FUTURE", out)  # gated at this card's reveal position

    def test_a_returned_patch_validates_for_a_card(self) -> None:
        card = self._card("Draft", body="Old synopsis.")
        raw = '{"body": "A sharper synopsis.", "fields": {}}'
        patch = self.service.validate_ai_entry_patch(card, raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "A sharper synopsis.")
