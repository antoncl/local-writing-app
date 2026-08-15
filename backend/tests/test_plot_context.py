"""Backend tests for the spoiler-gated plot context engine (ADR-0048 S8a; ADR-0053).

`read_plot_context(as_of=...)` assembles the board's plot state into one packet a
prompt reasons over, gated by manuscript reveal order: cards up to and including
the `as_of` anchor's reveal `sequence` are shown, later cards are withheld and only
counted. Plotlines (with their FULL beat rosters) are the writer's scaffolding and
are never gated. These prove the gate, the withheld-but-counted tally, the no-leak
filtering of causal edges, and the full-roster plotlines, through both the service
method and the HTTP preview endpoint.
"""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    CreateCardRequest,
    CreatePlotlineRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    SaveCardRequest,
    SavePlotlineRequest,
)

_THREE_ACT = "builtin-plot-three-act-story-arc"


class PlotContextTestCase(PlotTestCase):
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
        """An instantiated three-act plotline — 7 beats, each with a stable id."""
        return self.service.instantiate_plot_template(_THREE_ACT)


class WholeBoardTests(PlotContextTestCase):
    def test_empty_board_reads_as_whole_board(self) -> None:
        context = self.service.read_plot_context()
        self.assertEqual(context.completeness, "whole_board")
        self.assertEqual(context.omitted_cards, 0)
        self.assertEqual(context.cards, [])
        self.assertTrue(context.board_id.startswith("plot_"))

    def test_no_anchor_includes_every_card(self) -> None:
        chapter = self._chapter()
        for i in range(3):
            self._card(f"Card {i}", scene=self._scene(f"s{i}", chapter))
        context = self.service.read_plot_context()
        self.assertEqual(context.completeness, "whole_board")
        self.assertEqual(len(context.cards), 3)
        self.assertEqual(context.omitted_cards, 0)
        self.assertIsNone(context.as_of_sequence)

    def test_card_carries_synopsis_plotline_and_page_status(self) -> None:
        plotline = self.service.create_plotline(CreatePlotlineRequest(title="Romance"))
        self.service.save_plotline(plotline.id, SavePlotlineRequest(title="Romance", metadata={"color": "rose"}))
        chapter = self._chapter()
        scene = self._scene("Opening", chapter)
        card_id = self._card("They Meet", body="She spills his coffee.", plotline=plotline.id, scene=scene)

        context = self.service.read_plot_context()
        card = next(c for c in context.cards if c.id == card_id)
        self.assertEqual(card.synopsis, "She spills his coffee.\n")
        self.assertEqual(card.plotline_id, plotline.id)
        self.assertEqual(card.plotline_title, "Romance")
        self.assertEqual(card.scene_id, scene)
        self.assertEqual(card.page_status, "on_page")  # derived from the scene attachment
        colours = {p.title: p.color for p in context.plotlines}
        self.assertEqual(colours["Romance"], "rose")


class SpoilerGateTests(PlotContextTestCase):
    def _three_carded_cards(self) -> tuple[list[str], list[str]]:
        # Three cards on three consecutive scenes. Ranks are consecutive but not
        # 0-based — a fresh project's starter scene occupies an earlier rank — so
        # the gate assertions below read the real `sequence` rather than assume it.
        chapter = self._chapter()
        scenes = [self._scene(f"s{i}", chapter) for i in range(3)]
        cards = [self._card(f"Card {i}", scene=scenes[i]) for i in range(3)]
        return cards, scenes

    def _seq_of(self, card_id: str) -> int:
        card = next(c for c in self.service.read_plot_context().cards if c.id == card_id)
        assert card.sequence is not None
        return card.sequence

    def test_as_of_scene_hides_later_cards_and_counts_them(self) -> None:
        cards, scenes = self._three_carded_cards()
        context = self.service.read_plot_context(as_of=scenes[1])  # the middle card's scene
        self.assertEqual(context.completeness, "through_as_of")
        self.assertEqual(context.as_of_scene_id, scenes[1])
        self.assertEqual(context.as_of_sequence, self._seq_of(cards[1]))
        shown = {c.id for c in context.cards}
        self.assertEqual(shown, {cards[0], cards[1]})  # up to and including the anchor
        self.assertEqual(context.omitted_cards, 1)  # the later card is withheld

    def test_as_of_card_anchors_by_its_scene(self) -> None:
        cards, _scenes = self._three_carded_cards()
        context = self.service.read_plot_context(as_of=cards[0])  # anchors on its own scene
        self.assertEqual(context.as_of_sequence, self._seq_of(cards[0]))
        self.assertEqual({c.id for c in context.cards}, {cards[0]})
        self.assertEqual(context.omitted_cards, 2)

    def test_scene_less_card_is_always_admitted(self) -> None:
        cards, scenes = self._three_carded_cards()
        floating = self._card("Backstory")  # no scene → no reveal position
        context = self.service.read_plot_context(as_of=scenes[0])  # rank 0 gate
        shown = {c.id for c in context.cards}
        self.assertIn(floating, shown)  # off-page card is never a spoiler
        self.assertIn(cards[0], shown)
        self.assertNotIn(cards[1], shown)
        self.assertEqual(context.omitted_cards, 2)  # only the two later carded cards

    def test_an_unknown_anchor_falls_back_to_whole_board(self) -> None:
        self._three_carded_cards()
        context = self.service.read_plot_context(as_of="plot_does_not_exist")
        self.assertEqual(context.completeness, "whole_board")
        self.assertEqual(context.omitted_cards, 0)
        self.assertEqual(len(context.cards), 3)


class PlotlineRosterTests(PlotContextTestCase):
    def test_plotlines_carry_the_full_beat_roster_including_unfulfilled_beats(self) -> None:
        plotline = self._plotline()
        roster = plotline.metadata["instance_beats"]
        self.assertGreater(len(roster), 1)
        first_beat = roster[0]["id"]
        card_id = self._card(
            "Fulfils one beat",
            beat_links=[{"plotline": plotline.id, "beat_id": first_beat}],
        )

        context = self.service.read_plot_context()
        context_line = next(p for p in context.plotlines if p.id == plotline.id)
        # The whole roster is present — a beat no card fulfils is still shown (a gap).
        self.assertEqual(len(context_line.beats), len(roster))
        self.assertEqual(context_line.beats[0].beat_id, first_beat)
        self.assertTrue(context_line.beats[0].title)
        # The card names the one beat it fulfils, title-resolved against the plotline.
        card = next(c for c in context.cards if c.id == card_id)
        self.assertEqual([b.beat_id for b in card.beats], [first_beat])
        self.assertEqual(card.beats[0].plotline_id, plotline.id)
        self.assertEqual(card.beats[0].plotline_title, plotline.title)

    def test_plotline_source_name_is_the_template_it_was_rolled_from(self) -> None:
        plotline = self._plotline()
        context_line = next(p for p in self.service.read_plot_context().plotlines if p.id == plotline.id)
        self.assertEqual(context_line.source_template_name, plotline.metadata.get("source_template_name"))

    def test_plotline_carries_the_templates_structure_guidance(self) -> None:
        # S2: the template's ai_use_guidance + global_diagnostic_questions, snapshotted
        # at instantiate, surface in the context so the AI measures cards against the
        # structure's intent, not just per-beat one-liners.
        plotline = self._plotline()
        context_line = next(p for p in self.service.read_plot_context().plotlines if p.id == plotline.id)
        self.assertEqual(context_line.ai_guidance, plotline.metadata.get("source_ai_guidance"))
        self.assertTrue(context_line.ai_guidance)  # the three-act fixture actually has guidance
        self.assertEqual(context_line.diagnostic_questions, plotline.metadata.get("source_diagnostic_questions"))
        self.assertTrue(context_line.diagnostic_questions)
        self.assertEqual(context_line.weak_spots, plotline.metadata.get("source_weak_spots"))
        self.assertTrue(context_line.weak_spots)  # the three-act fixture ships weak spots

    def test_a_card_link_to_a_departed_beat_is_dropped(self) -> None:
        plotline = self._plotline()
        roster = plotline.metadata["instance_beats"]
        gone_beat = roster[0]["id"]
        card_id = self._card("Links a beat", beat_links=[{"plotline": plotline.id, "beat_id": gone_beat}])
        # Remove that beat from the plotline's roster — the card's stored link now
        # points at a beat that no longer exists.
        trimmed = [b for b in roster if b["id"] != gone_beat]
        self.service.save_plotline(
            plotline.id,
            SavePlotlineRequest(
                title=plotline.title, body="", metadata={**plotline.metadata, "instance_beats": trimmed}
            ),
        )
        context = self.service.read_plot_context()
        card = next(c for c in context.cards if c.id == card_id)
        self.assertEqual(card.beats, [])  # the link to the departed beat is dropped display-side
        context_line = next(p for p in context.plotlines if p.id == plotline.id)
        self.assertNotIn(gone_beat, [b.beat_id for b in context_line.beats])

    def test_plotlines_stay_present_when_the_gate_hides_all_their_cards(self) -> None:
        plotline = self._plotline()
        first_beat = plotline.metadata["instance_beats"][0]["id"]
        chapter = self._chapter()
        early, late = self._scene("early", chapter), self._scene("late", chapter)
        # The only card fulfilling the plotline sits on a later scene, so the gate
        # below withholds it — but the plotline is scaffolding and stays fully present.
        self._card("Fulfils", scene=late, beat_links=[{"plotline": plotline.id, "beat_id": first_beat}])
        context = self.service.read_plot_context(as_of=early)
        self.assertEqual(context.cards, [])  # the fulfilling card is withheld
        self.assertEqual(context.omitted_cards, 1)
        context_line = next(p for p in context.plotlines if p.id == plotline.id)
        self.assertEqual(len(context_line.beats), len(plotline.metadata["instance_beats"]))  # ungated


class CausalEdgeTests(PlotContextTestCase):
    def test_causal_out_is_present_on_the_whole_board(self) -> None:
        chapter = self._chapter()
        s0, s2 = self._scene("s0", chapter), self._scene("s2", chapter)
        target = self._card("Effect", scene=s2)
        source = self._card("Cause", scene=s0, causal_links=[{"target": target}])
        context = self.service.read_plot_context()
        card = next(c for c in context.cards if c.id == source)
        self.assertEqual(card.causal_out, [target])

    def test_a_withheld_target_never_leaks_through_a_causal_edge(self) -> None:
        chapter = self._chapter()
        s0, s1 = self._scene("s0", chapter), self._scene("s1", chapter)
        target = self._card("Effect", scene=s1)  # reads after s0
        source = self._card("Cause", scene=s0, causal_links=[{"target": target}])

        context = self.service.read_plot_context(as_of=s0)  # gate at the source's scene
        self.assertEqual(context.omitted_cards, 1)  # the target is withheld
        card = next(c for c in context.cards if c.id == source)
        self.assertEqual(card.causal_out, [])  # the edge to the hidden card is dropped


class ContextEndpointTests(PlotContextTestCase):
    def test_endpoint_returns_the_gated_context(self) -> None:
        chapter = self._chapter()
        scenes = [self._scene(f"s{i}", chapter) for i in range(3)]
        for i in range(3):
            self._card(f"Card {i}", scene=scenes[i])

        whole = self.client.get("/api/plot/board/context")
        self.assertEqual(whole.status_code, 200, whole.text)
        self.assertEqual(whole.json()["completeness"], "whole_board")
        self.assertEqual(len(whole.json()["cards"]), 3)

        gated = self.client.get("/api/plot/board/context", params={"as_of": scenes[0]})
        self.assertEqual(gated.status_code, 200, gated.text)
        body = gated.json()
        self.assertEqual(body["completeness"], "through_as_of")
        self.assertEqual(len(body["cards"]), 1)  # only the first card's scene reads by now
        self.assertEqual(body["as_of_sequence"], body["cards"][0]["sequence"])
        self.assertEqual(body["omitted_cards"], 2)
