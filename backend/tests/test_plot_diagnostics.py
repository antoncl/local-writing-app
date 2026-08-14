"""Backend tests for cross-dimension plot diagnostics (ADR-0048 S7 — the payoff).

The board holds three layers at once — reveal order (a card's scene position), beat
sequence (a plotline's ordered roster + card→beat links), and authored causality (the
"leads to" edges). A *disagreement between two layers* is a plot problem, and
`compute_plot_diagnostics` derives them from the projection deterministically, riding
along on `read_plot_board_projection().diagnostics`.

These prove the three detections AND their anti-nag rules: off-page / unwritten cards
are legitimate, so an off-page setup never "inverts", and a merely-unwritten beat tail
is never a gap. A plotline is a plot-template instance (ADR-0053 §1); its beats carry
stable ids (Slice 3a) that the card→beat links target.
"""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    CreateCardRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    SaveCardRequest,
)

_THREE_ACT = "builtin-plot-three-act-story-arc"


class _DiagnosticsTestCase(PlotTestCase):
    """Builds boards whose layers can be made to (dis)agree: scenes in a single
    chapter give consecutive reveal ranks, and cards attach to them + link beats +
    draw causal edges. Reads findings straight off the projection."""

    def setUp(self) -> None:
        super().setUp()
        root = self.service.read_structure().root.id
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter", entry_type="scene:chapter", parent_id=root)
        )
        self.chapter = next(
            c.id for c in self.service.read_structure().root.children if c.type == "scene:chapter"
        )

    def _scene(self, title: str) -> str:
        # Scenes under one chapter read in creation order — consecutive reveal ranks.
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=self.chapter)).id

    def _card(
        self,
        title: str,
        *,
        scene: str | None = None,
        beats: list[tuple[str, str]] | None = None,
        causal: list[str] | None = None,
    ) -> str:
        card = self.service.create_card(CreateCardRequest(title=title))
        metadata: dict = {}
        if scene:
            metadata["scene"] = scene
        if beats:
            metadata["beat_links"] = [{"plotline": pl, "beat_id": bid} for pl, bid in beats]
        if causal:
            metadata["causal_links"] = [{"target": t} for t in causal]
        self.service.save_card(card.id, SaveCardRequest(title=title, body="", metadata=metadata))
        return card.id

    def _plotline(self):
        return self.service.instantiate_plot_template(_THREE_ACT)

    def _diagnostics(self):
        return self.service.read_plot_board_projection().diagnostics

    def _of_kind(self, kind: str):
        return [d for d in self._diagnostics() if d.kind == kind]


class CausalInversionTests(_DiagnosticsTestCase):
    """A card *leads to* a card revealed earlier — the payoff is read before its setup."""

    def test_a_payoff_revealed_before_its_setup_is_flagged(self) -> None:
        early, late = self._scene("early"), self._scene("late")
        payoff = self._card("Payoff", scene=early)
        setup = self._card("Setup", scene=late, causal=[payoff])
        findings = self._of_kind("causal_inversion")
        self.assertEqual(len(findings), 1)
        found = findings[0]
        self.assertEqual((found.edge.source, found.edge.target), (setup, payoff))
        self.assertEqual({c.id for c in found.cards}, {setup, payoff})
        self.assertIn("sets up", found.message)

    def test_a_causal_edge_in_reading_order_is_clean(self) -> None:
        early, late = self._scene("early"), self._scene("late")
        payoff = self._card("Payoff", scene=late)
        self._card("Setup", scene=early, causal=[payoff])
        self.assertEqual(self._of_kind("causal_inversion"), [])

    def test_an_off_page_setup_never_inverts(self) -> None:
        # A setup with no scene is backstory told-late — it holds no reveal position,
        # so there is no order to contradict. Never nag it into a scene.
        payoff = self._card("Payoff", scene=self._scene("early"))
        self._card("Setup", causal=[payoff])
        self.assertEqual(self._of_kind("causal_inversion"), [])

    def test_an_off_page_payoff_never_inverts(self) -> None:
        setup_scene = self._scene("late")
        payoff = self._card("Payoff")  # off-page — no reveal position
        self._card("Setup", scene=setup_scene, causal=[payoff])
        self.assertEqual(self._of_kind("causal_inversion"), [])

    def test_cards_on_the_same_scene_do_not_invert(self) -> None:
        # n cards per scene share a reveal rank — simultaneous, not out of sequence.
        scene = self._scene("s")
        payoff = self._card("Payoff", scene=scene)
        self._card("Setup", scene=scene, causal=[payoff])
        self.assertEqual(self._of_kind("causal_inversion"), [])


class BeatInversionTests(_DiagnosticsTestCase):
    """Within one plotline, a later beat is *fully* revealed before an earlier begins."""

    def test_a_later_beat_revealed_first_is_flagged(self) -> None:
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        early, late = self._scene("early"), self._scene("late")
        self._card("later beat", scene=early, beats=[(plotline.id, beats[1]["id"])])
        self._card("earlier beat", scene=late, beats=[(plotline.id, beats[0]["id"])])
        findings = self._of_kind("beat_inversion")
        self.assertEqual(len(findings), 1)
        found = findings[0]
        self.assertEqual(found.plotline_id, plotline.id)
        self.assertEqual(set(found.beat_ids), {beats[0]["id"], beats[1]["id"]})

    def test_beats_in_reading_order_are_clean(self) -> None:
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        early, late = self._scene("early"), self._scene("late")
        self._card("b0", scene=early, beats=[(plotline.id, beats[0]["id"])])
        self._card("b1", scene=late, beats=[(plotline.id, beats[1]["id"])])
        self.assertEqual(self._of_kind("beat_inversion"), [])

    def test_braided_beats_do_not_flag(self) -> None:
        # beat0 spans the first and third scenes; beat1 sits between them. The spans
        # overlap — interleaving, not a strict inversion — so it must stay quiet.
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        s1, s2, s3 = self._scene("s1"), self._scene("s2"), self._scene("s3")
        self._card("b0 early", scene=s1, beats=[(plotline.id, beats[0]["id"])])
        self._card("b1 mid", scene=s2, beats=[(plotline.id, beats[1]["id"])])
        self._card("b0 late", scene=s3, beats=[(plotline.id, beats[0]["id"])])
        self.assertEqual(self._of_kind("beat_inversion"), [])

    def test_an_off_page_beat_card_does_not_invert(self) -> None:
        # A beat fulfilled only off-page holds no reveal span, so nothing to invert.
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        late = self._scene("late")
        self._card("later beat off-page", beats=[(plotline.id, beats[1]["id"])])
        self._card("earlier beat", scene=late, beats=[(plotline.id, beats[0]["id"])])
        self.assertEqual(self._of_kind("beat_inversion"), [])


class BeatGapTests(_DiagnosticsTestCase):
    """An interior beat no card fulfils, with a fulfilled beat still after it."""

    def test_an_interior_unfilled_beat_is_a_gap(self) -> None:
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        s1, s2 = self._scene("s1"), self._scene("s2")
        self._card("fills b0", scene=s1, beats=[(plotline.id, beats[0]["id"])])
        self._card("fills b2", scene=s2, beats=[(plotline.id, beats[2]["id"])])
        gaps = self._of_kind("beat_gap")
        # Only beat1 is interior-and-unfilled; beats 3..6 trail the last fulfilled one.
        self.assertEqual([g.beat_ids for g in gaps], [[beats[1]["id"]]])
        self.assertEqual(gaps[0].plotline_id, plotline.id)
        self.assertEqual(gaps[0].cards, [])

    def test_a_trailing_unwritten_beat_is_not_a_gap(self) -> None:
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        self._card("fills b0", scene=self._scene("s1"), beats=[(plotline.id, beats[0]["id"])])
        self.assertEqual(self._of_kind("beat_gap"), [])

    def test_a_plotline_with_no_cards_has_no_gaps(self) -> None:
        self._plotline()
        self.assertEqual(self._of_kind("beat_gap"), [])

    def test_a_beat_fulfilled_off_page_is_not_a_gap(self) -> None:
        # use_count counts any linked card, on-page or not — an off-page card still
        # fulfils its beat, so the interior beat it holds is no hole.
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        s1, s2 = self._scene("s1"), self._scene("s2")
        self._card("b0", scene=s1, beats=[(plotline.id, beats[0]["id"])])
        self._card("b2", scene=s2, beats=[(plotline.id, beats[2]["id"])])
        self._card("b1 off-page", beats=[(plotline.id, beats[1]["id"])])
        self.assertEqual(self._of_kind("beat_gap"), [])


class CoherentBoardTests(_DiagnosticsTestCase):
    def test_a_coherent_board_reports_no_findings(self) -> None:
        # Beats in order, a causal edge in order, no interior gaps — the layers agree.
        plotline = self._plotline()
        beats = plotline.metadata["instance_beats"]
        early, late = self._scene("early"), self._scene("late")
        payoff = self._card("B", scene=late, beats=[(plotline.id, beats[1]["id"])])
        self._card("A", scene=early, beats=[(plotline.id, beats[0]["id"])], causal=[payoff])
        self.assertEqual(self._diagnostics(), [])
