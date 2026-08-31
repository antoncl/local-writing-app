"""The plot-card brainstorm's context surface (ADR-0048 S8b).

Two layers: the `plot_context` Jinja helper + its formatter (the spoiler-gated
board block a prompt drops in), and the `revise-plot-card` builtin prompt that
uses it (a `plot:card` brainstorm — the ADR-0046 loop on a card).
These prove the block renders + gates, the prompt ships and routes as an
`extract_to_node` + `commit` brainstorm (ADR-0054 §2 / ADR-0065), and a returned
patch validates for a card.
"""

from __future__ import annotations

from _builtins import builtin_prompt_id
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
_PROMPT_TITLE = "Revise plot card"


class _PlotAiContextBase(PlotTestCase):
    def _chapter(self, title: str = "Chapter") -> str:
        root = self.service.read_structure().root.id
        self.service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type="manuscript:chapter", parent_id=root)
        )
        return next(
            c.id
            for c in self.service.read_structure().root.children
            if c.type == "manuscript:chapter" and c.title == title
        )

    def _scene(self, title: str, chapter_id: str) -> str:
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=chapter_id)).id

    def _card(self, title: str, *, body: str = "", **metadata: object) -> str:
        card = self.service.create_card(CreateCardRequest(title=title))
        self.service.save_card(card.id, SaveCardRequest(title=title, body=body, metadata=dict(metadata)))
        return card.id

    def _plotline(self):
        return self.service.instantiate_plot_template(_THREE_ACT)

    def _render(self, template: str, **context: object) -> str:
        env = create_environment_for_project(self.service)
        return render_template(template, context=context, env=env).messages[0].text


class PlotContextHelperTests(_PlotAiContextBase):
    def test_the_block_carries_plotlines_cards_and_synopsis(self) -> None:
        plotline = self._plotline()
        first_beat = plotline.metadata["instance_beats"][0]["id"]
        chapter = self._chapter()
        scene = self._scene("Opening", chapter)
        self._card(
            "They Meet",
            body="She spills his coffee.",
            scene=scene,
            beat_links=[{"plotline": plotline.id, "beat_id": first_beat}],
        )
        out = self._render('{% role "system" %}{{ plot_context() }}{% endrole %}')
        self.assertIn("<plot_context", out)
        self.assertIn('completeness="whole_board"', out)
        self.assertIn(plotline.title, out)  # the plotline appears with its roster
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
            SavePlotlineRequest,
        )

        # An ad-hoc plotline with a beat carrying GUIDANCE (shipped template beats
        # carry only `function`), so the guidance-as-element branch is exercised.
        structure = self.service.create_plotline(CreatePlotlineRequest(title="Custom"))
        self.service.save_plotline(
            structure.id,
            SavePlotlineRequest(
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
        # The beatless "Romance" plotline is a self-closed element (ad-hoc / no beats),
        # still present so the AI sees the thread even before it is beaten out.
        self.assertIn('<plotline title="Romance" />', out)

    def test_the_block_carries_a_plotlines_structure_guidance(self) -> None:
        # S2: an instantiated plotline renders the template's structural guidance —
        # how to use the lens (`<use_guidance>`) and the questions to ask
        # (`<diagnostic_questions>`) — so the model measures cards against the
        # structure's intent, not just per-beat one-liners.
        plotline = self._plotline()  # three-act ships ai_use_guidance + questions + weak spots
        out = self._render('{% role "system" %}{{ plot_context() }}{% endrole %}')
        self.assertIn("<use_guidance>", out)
        self.assertIn(plotline.metadata["source_ai_guidance"], out)  # the actual snapshot text
        self.assertIn("<diagnostic_questions>", out)
        self.assertEqual(
            out.count("<question>"), len(plotline.metadata["source_diagnostic_questions"])
        )
        self.assertIn("<weak_spots>", out)
        self.assertEqual(out.count("<spot>"), len(plotline.metadata["source_weak_spots"]))

    def test_a_plotline_with_guidance_but_no_beats_still_opens(self) -> None:
        # The self-close guard is "no guidance AND no beats", not "no beats": a plotline
        # carrying structure guidance but not yet beaten out must still emit its
        # <use_guidance>, not collapse to a self-closed tag that silently drops it.
        from app.models import CreatePlotlineRequest, SavePlotlineRequest

        line = self.service.create_plotline(CreatePlotlineRequest(title="Guided"))
        self.service.save_plotline(
            line.id,
            SavePlotlineRequest(title="Guided", body="", metadata={"source_ai_guidance": "LENS_TEXT"}),
        )
        out = self._render('{% role "system" %}{{ plot_context() }}{% endrole %}')
        self.assertIn("<use_guidance>LENS_TEXT</use_guidance>", out)
        self.assertNotIn('<plotline title="Guided" />', out)  # opened, not self-closed


class RevisePlotCardPromptTests(_PlotAiContextBase):
    def test_the_prompt_ships_in_the_library_as_a_commit_brainstorm(self) -> None:
        prompt_id = builtin_prompt_id(self.service, _PROMPT_TITLE)
        entries = {e.id: e for e in self.service.list_prompt_entries().entries}
        self.assertIn(prompt_id, entries)
        # The plot-card brainstorm is a `prompt:general` carrying an instance
        # `context_strategy` (#954, ADR-0065 S3), not its own sub-type: its commit
        # disposition is identical to `revise-entry`/`revise-plotline`, and its
        # plot-card target/body are per-instance (front matter). Same move as
        # `impersonate`.
        self.assertEqual(entries[prompt_id].entry_type, "prompt:general")
        output = self.service.read_prompt_entry(prompt_id).context_strategy.output
        # ADR-0054 §2 / ADR-0065: the brainstorm is the `extract_to_node` handler + a
        # `commit`, not a distinct disposition.
        self.assertEqual(output.handler, "extract_to_node")
        self.assertIsNotNone(output.commit)

    def test_the_prompt_body_renders_the_gated_context_for_its_card(self) -> None:
        chapter = self._chapter()
        s0, s1 = self._scene("s0", chapter), self._scene("s1", chapter)
        card = self._card("The turn", body="He decides to leave.", scene=s0)
        self._card("Aftermath", body="SECRET_FUTURE fallout.", scene=s1)
        body = self.service.read_prompt_entry(builtin_prompt_id(self.service, _PROMPT_TITLE)).body
        out = self._render(body, inputs={"entry": card})
        self.assertIn("The turn", out)  # the card under revision
        self.assertIn("<plot_context", out)  # the board block is injected
        self.assertNotIn("SECRET_FUTURE", out)  # gated at this card's reveal position

    def test_a_returned_patch_validates_for_a_card(self) -> None:
        card = self._card("Draft", body="Old synopsis.")
        raw = '{"body": "A sharper synopsis.", "fields": {}}'
        patch = self.service.validate_ai_entry_patch(card, raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.body, "A sharper synopsis.")

    def test_the_brainstorm_can_populate_follow_ups(self) -> None:
        # follow_ups (S8c) is a plain, non-hidden list field, so it is proposable —
        # a commit that sets it validates rather than being dropped, which is how the
        # brainstorm adds follow-ups through the same entry-patch it already commits.
        card = self._card("Draft")
        raw = '{"body": "", "fields": {"follow_ups": ["tighten the ending", "name the inn"]}}'
        patch = self.service.validate_ai_entry_patch(card, raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(patch.fields.get("follow_ups"), ["tighten the ending", "name the inn"])
        self.assertNotIn("follow_ups", patch.dropped)
