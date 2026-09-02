"""Character-arc subtype tests (ADR-0080 slice 1).

A character arc is a distinct plot subtype — the plotline's SIBLING under a
shared abstract `plot:thread` beat-holder base, not an `is_a` plotline. These
cover the backend foundation: the type/ancestry + field membership, subtype
selection at instantiate (§7), the generalized `beat_links` healer accepting an
arc holder (§3), the card primary-plotline type exclusion (§4), and the
slice-1 board-projection deferral (an arc beat_link round-trips in storage but
is not yet rendered). Split out of test_plot.py to keep that file under the
1500-line guard; reuses the shared `PlotTestCase` fixture.
"""
from __future__ import annotations

import unittest

from plot_fixtures import PlotTestCase

from app.models import (
    CreateCardRequest,
    CreateCharacterArcRequest,
    SaveCardRequest,
    SaveCharacterArcRequest,
)
from app.services.project.errors import ProjectServiceError

_CHARACTER_ARC_TEMPLATE = "builtin-plot-positive-character-change-arc"


class CharacterArcTypeAncestryTests(PlotTestCase):
    """ADR-0080 §1: plot:character_arc is the plotline's SIBLING under the shared
    plot:thread beat-holder base — not an `is_a` plotline. Both concrete types
    inherit the beat/lineage fields from plot:thread (parent ∪ own)."""

    def test_character_arc_is_a_thread_not_a_plotline(self) -> None:
        arc_ancestry = self.service.entry_type_ancestry("plot:character_arc")
        self.assertIn("plot:thread", arc_ancestry)
        self.assertIn("plot:base", arc_ancestry)
        self.assertNotIn("plot:plotline", arc_ancestry)

    def test_plotline_is_a_thread(self) -> None:
        plotline_ancestry = self.service.entry_type_ancestry("plot:plotline")
        self.assertIn("plot:thread", plotline_ancestry)
        self.assertIn("plot:base", plotline_ancestry)

    def test_character_arc_field_membership(self) -> None:
        schema = self.service.read_metadata_schema()
        arc = schema.entry_types["plot:character_arc"]
        for field_id in ("instance_beats", "source_template_id", "character"):
            self.assertIn(field_id, arc.fields)
        self.assertNotIn("color", arc.fields)
        self.assertNotIn("genre", arc.fields)

    def test_plotline_field_membership(self) -> None:
        schema = self.service.read_metadata_schema()
        plotline = schema.entry_types["plot:plotline"]
        for field_id in ("color", "genre", "instance_beats"):
            self.assertIn(field_id, plotline.fields)
        self.assertNotIn("character", plotline.fields)


class CharacterArcInstantiationTests(PlotTestCase):
    """ADR-0080 §7: instantiate_plot_template selects the concrete subtype from
    the source template's `family` — a character_arc-family template spawns a
    plot:character_arc; any other family keeps spawning a plot:plotline."""

    def test_instantiate_character_arc_family_spawns_arc(self) -> None:
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        self.assertEqual(arc.entry_type, "plot:character_arc")
        # read_character_arc succeeds — the new node really is an arc.
        self.assertEqual(self.service.read_character_arc(arc.id).id, arc.id)
        self.assertTrue(arc.metadata.get("instance_beats"))
        self.assertNotIn("genre", arc.metadata)

    def test_instantiate_non_arc_family_spawns_plotline_unchanged(self) -> None:
        plotline = self.service.instantiate_plot_template("builtin-plot-three-act-story-arc")
        self.assertEqual(plotline.entry_type, "plot:plotline")
        self.assertIn("genre", plotline.metadata)
        self.assertEqual(self.service.read_plotline(plotline.id).id, plotline.id)

    def test_instantiating_an_arc_does_not_reclassify_other_plotlines(self) -> None:
        plotline = self.service.instantiate_plot_template("builtin-plot-three-act-story-arc")
        self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        self.assertEqual(self.service.read_plotline(plotline.id).entry_type, "plot:plotline")

    def test_instantiate_arc_over_http_serializes_as_arc(self) -> None:
        # The primary "create an arc" journey the slice-2 frontend hits: the
        # widened `PlotlineEntry | CharacterArcEntry` response_model must put the
        # arc's own entry_type on the wire (ADR-0080 §7), not coerce it to a
        # plotline. The plotline branch is already wire-covered in
        # test_plot_card_links.py; this covers the arc branch.
        response = self.client.post(f"/api/plot/templates/{_CHARACTER_ARC_TEMPLATE}/instantiate")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["entry_type"], "plot:character_arc")
        self.assertTrue(body["metadata"].get("instance_beats"))
        self.assertNotIn("genre", body["metadata"])
        # The node really is an arc (read via the service — no arc HTTP route yet).
        self.assertEqual(self.service.read_character_arc(body["id"]).id, body["id"])


class CharacterArcBeatLinkTests(PlotTestCase):
    """ADR-0080 §3: the card beat-link healer accepts any `plot:thread` holder —
    a plotline OR a character arc. Mirrors the plotline beat-link heal tests in
    test_plot_card_links.py one-for-one, swapping the holder to an arc."""

    def _arc(self):
        return self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)

    def test_card_beat_link_accepts_arc_holder(self) -> None:
        arc = self._arc()
        beat_id = arc.metadata["instance_beats"][0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title, body="", metadata={"beat_links": [{"plotline": arc.id, "beat_id": beat_id}]}
            ),
        )
        links = self.service.read_card(card.id).metadata["beat_links"]
        self.assertEqual(links, [{"plotline": arc.id, "beat_id": beat_id}])

    def test_card_beat_link_to_arc_drops_on_arc_delete(self) -> None:
        arc = self._arc()
        beat_id = arc.metadata["instance_beats"][0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title, body="", metadata={"beat_links": [{"plotline": arc.id, "beat_id": beat_id}]}
            ),
        )
        self.assertEqual(len(self.service.read_card(card.id).metadata["beat_links"]), 1)
        self.service.delete_character_arc(arc.id)
        self.assertNotIn("beat_links", self.service.read_card(card.id).metadata)

    def test_card_beat_link_to_arc_drops_when_beat_leaves_roster(self) -> None:
        arc = self._arc()
        beats = arc.metadata["instance_beats"]
        doomed = beats[-1]["id"]
        survivor = beats[0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title,
                body="",
                metadata={
                    "beat_links": [
                        {"plotline": arc.id, "beat_id": survivor},
                        {"plotline": arc.id, "beat_id": doomed},
                    ]
                },
            ),
        )
        trimmed = beats[:-1]
        self.service.save_character_arc(
            arc.id,
            SaveCharacterArcRequest(title=arc.title, body="", metadata={**arc.metadata, "instance_beats": trimmed}),
        )
        links = self.service.read_card(card.id).metadata["beat_links"]
        self.assertEqual(links, [{"plotline": arc.id, "beat_id": survivor}])


class CardPrimaryPlotlineExcludesArcTests(PlotTestCase):
    """ADR-0080 §4: a card's primary `plotline` picker targets `plot:plotline`
    exactly, so a character arc is excluded by TYPE — no new code needed, since
    the entity_ref validator/healer already enforce the picker's entry_type
    whitelist. Mirrors test_read_side_healing_blanks_a_dangling_reference (a
    live node of the WRONG type, not a ghost id) plus the save-time reject
    mirroring test_save_rejects_a_reference_to_a_nonexistent_node."""

    def test_card_primary_plotline_rejects_arc_by_type_on_read(self) -> None:
        arc = self.service.create_character_arc(CreateCharacterArcRequest(title="Her Arc"))
        card = self.service.create_card(CreateCardRequest(title="Card"))
        path = self.service._path_for_node_id(card.id, "plot")
        self.service._write_node_entry_file(path, card.id, "Card", "plot:card", {"plotline": arc.id}, "")
        self.assertEqual(self.service.read_card(card.id).metadata.get("plotline"), "")

    def test_card_primary_plotline_save_rejects_arc_id(self) -> None:
        arc = self.service.create_character_arc(CreateCharacterArcRequest(title="Her Arc"))
        card = self.service.create_card(CreateCardRequest(title="Card"))
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_card(card.id, SaveCardRequest(title="Card", metadata={"plotline": arc.id}))
        self.assertEqual(ctx.exception.status_code, 422)


class CharacterArcBoardProjectionDeferralTests(PlotTestCase):
    """ADR-0080 slice-1 deferral: the board projection is NOT yet widened to arcs
    (that lands with the presentation slice, §5/§6). Until then a card's beat_link
    to an arc must SURVIVE healing — storage is correct — while the projection
    tolerates it: it must not crash, must not list the arc among its plotlines, and
    simply omits the not-yet-rendered arc beat from the card. Proves the deferral
    window is safe rather than merely reasoned, and pins the intermediate state
    slices 2-3 will change."""

    def test_board_projection_tolerates_an_arc_beat_link(self) -> None:
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        beat_id = arc.metadata["instance_beats"][0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title, body="", metadata={"beat_links": [{"plotline": arc.id, "beat_id": beat_id}]}
            ),
        )
        # The link is real in storage (healer kept it)...
        self.assertEqual(len(self.service.read_card(card.id).metadata["beat_links"]), 1)
        # ...but the projection does not yet know arcs: no crash, arc absent from
        # the plotline rail, and the arc beat not projected onto the card.
        projection = self.service.read_plot_board_projection()
        self.assertNotIn(arc.id, {line.id for line in projection.plotlines})
        projected_card = next(c for c in projection.cards if c.id == card.id)
        self.assertEqual(projected_card.beats, [])


if __name__ == "__main__":
    unittest.main()
