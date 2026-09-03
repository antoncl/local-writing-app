"""Character-arc subtype tests (ADR-0080 slices 1 & 3).

A character arc is a distinct plot subtype — the plotline's SIBLING under a
shared abstract `plot:thread` beat-holder base, not an `is_a` plotline. These
cover the backend foundation: the type/ancestry + field membership (incl. the
shared `color` field hoisted to `plot:thread`, Amendment 1 §1), subtype
selection at instantiate (§7), the generalized `beat_links` healer accepting an
arc holder (§3), the card primary-plotline type exclusion (§4), the board
projection now resolving arc beat_links + emitting a distinct `arcs` band
(§5, closing the slice-1 deferral), and the character-arc HTTP routes (§6).
Split out of test_plot.py to keep that file under the 1500-line guard; reuses
the shared `PlotTestCase` fixture.
"""
from __future__ import annotations

import unittest

from plot_fixtures import PlotTestCase

from app.models import (
    CreateCardRequest,
    CreateCharacterArcRequest,
    CreateLoreEntryRequest,
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
        # `color` is now inherited from the shared `plot:thread` base (Amendment 1
        # §1), same as a plotline — both `plot:thread` subtypes resolve it.
        for field_id in ("instance_beats", "source_template_id", "character", "color"):
            self.assertIn(field_id, arc.fields)
        self.assertNotIn("genre", arc.fields)

    def test_plotline_field_membership(self) -> None:
        schema = self.service.read_metadata_schema()
        plotline = schema.entry_types["plot:plotline"]
        for field_id in ("color", "genre", "instance_beats"):
            self.assertIn(field_id, plotline.fields)
        self.assertNotIn("character", plotline.fields)

    def test_both_thread_subtypes_resolve_color_plotline_keeps_genre_arc_does_not(self) -> None:
        # Amendment 1 §1: hoisting `color` to `plot:thread` gives BOTH concrete
        # subtypes a colour (parent ∪ own field inheritance), while each subtype's
        # own field stays exclusive to it.
        schema = self.service.read_metadata_schema()
        plotline = schema.entry_types["plot:plotline"]
        arc = schema.entry_types["plot:character_arc"]
        self.assertIn("color", plotline.fields)
        self.assertIn("color", arc.fields)
        self.assertIn("genre", plotline.fields)
        self.assertNotIn("genre", arc.fields)


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


class CharacterArcBoardProjectionTests(PlotTestCase):
    """ADR-0080 §5 / Amendment 1: the slice-1 deferral is now CLOSED — the board
    projection resolves a card's arc beat_link the same way it resolves a plotline
    one, tagging it as a change-beat, and the arc itself projects onto its own
    `arcs` band (never merged into `plotlines`)."""

    def _bind_character(self, arc, name: str = "Mira Voss"):
        character = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=name, entry_type="lore:character")
        )
        bound = self.service.save_character_arc(
            arc.id,
            SaveCharacterArcRequest(
                title=arc.title, body="", metadata={**arc.metadata, "character": character.id}
            ),
        )
        return character, bound

    def test_board_projection_resolves_an_arc_beat_link(self) -> None:
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        character, arc = self._bind_character(arc)
        beat_id = arc.metadata["instance_beats"][0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title, body="", metadata={"beat_links": [{"plotline": arc.id, "beat_id": beat_id}]}
            ),
        )
        # The link is real in storage (unchanged from slice 1)...
        self.assertEqual(len(self.service.read_card(card.id).metadata["beat_links"]), 1)

        projection = self.service.read_plot_board_projection()

        # The arc is its OWN band — never merged into the plotline rail.
        self.assertNotIn(arc.id, {line.id for line in projection.plotlines})
        projected_arc = next(a for a in projection.arcs if a.id == arc.id)
        self.assertEqual(projected_arc.title, arc.title)
        self.assertEqual(projected_arc.character_id, character.id)
        self.assertEqual(projected_arc.character_name, "Mira Voss")
        self.assertEqual(projected_arc.character_initial, "M")
        arc_beat = next(b for b in projected_arc.beats if b.beat_id == beat_id)
        self.assertEqual(arc_beat.use_count, 1)

        # The card's beat_link resolves to ONE badge, tagged as a change-beat and
        # wearing the bound character's identity.
        projected_card = next(c for c in projection.cards if c.id == card.id)
        self.assertEqual(len(projected_card.beats), 1)
        resolved = projected_card.beats[0]
        self.assertEqual(resolved.beat_id, beat_id)
        self.assertEqual(resolved.holder_kind, "plot:character_arc")
        self.assertEqual(resolved.character_id, character.id)
        self.assertEqual(resolved.character_name, "Mira Voss")
        self.assertEqual(resolved.character_initial, "M")

    def test_unbound_arc_beat_resolves_with_no_character(self) -> None:
        # An arc with no `character` bound yet still projects its beat, just with
        # no character identity to wear (ADR §Open: binding may happen later).
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        beat_id = arc.metadata["instance_beats"][0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title, body="", metadata={"beat_links": [{"plotline": arc.id, "beat_id": beat_id}]}
            ),
        )
        projection = self.service.read_plot_board_projection()
        projected_card = next(c for c in projection.cards if c.id == card.id)
        resolved = projected_card.beats[0]
        self.assertEqual(resolved.holder_kind, "plot:character_arc")
        self.assertIsNone(resolved.character_id)
        self.assertIsNone(resolved.character_name)
        self.assertIsNone(resolved.character_initial)


class BoardProjectionMixedThreadTests(PlotTestCase):
    """ADR-0080 §5: a card can link beats from BOTH a plotline (event-beat) and a
    character arc (change-beat); the projection resolves and tags each distinctly.
    Also mirrors the storage-heal use-count/removal tests, now asserting the
    PROJECTION reflects the change, not just storage."""

    def test_card_with_plotline_and_arc_beats_resolves_both_distinctly(self) -> None:
        plotline = self.service.instantiate_plot_template("builtin-plot-three-act-story-arc")
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        character = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Elin Ward", entry_type="lore:character")
        )
        arc = self.service.save_character_arc(
            arc.id,
            SaveCharacterArcRequest(
                title=arc.title, body="", metadata={**arc.metadata, "character": character.id}
            ),
        )
        plotline_beat_id = plotline.metadata["instance_beats"][0]["id"]
        arc_beat_id = arc.metadata["instance_beats"][0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Pivot"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title,
                body="",
                metadata={
                    "beat_links": [
                        {"plotline": plotline.id, "beat_id": plotline_beat_id},
                        {"plotline": arc.id, "beat_id": arc_beat_id},
                    ]
                },
            ),
        )

        projection = self.service.read_plot_board_projection()
        projected_card = next(c for c in projection.cards if c.id == card.id)
        self.assertEqual(len(projected_card.beats), 2)
        by_holder = {b.holder_kind: b for b in projected_card.beats}
        self.assertEqual(by_holder["plot:plotline"].beat_id, plotline_beat_id)
        self.assertIsNone(by_holder["plot:plotline"].character_id)
        self.assertEqual(by_holder["plot:character_arc"].beat_id, arc_beat_id)
        self.assertEqual(by_holder["plot:character_arc"].character_name, "Elin Ward")

    def test_arc_beat_and_its_card_link_leave_the_projection_when_beat_leaves_roster(self) -> None:
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        beats = arc.metadata["instance_beats"]
        beat_id = beats[0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title, body="", metadata={"beat_links": [{"plotline": arc.id, "beat_id": beat_id}]}
            ),
        )
        before = self.service.read_plot_board_projection()
        projected_arc = next(a for a in before.arcs if a.id == arc.id)
        self.assertEqual(next(b.use_count for b in projected_arc.beats if b.beat_id == beat_id), 1)

        trimmed = [b for b in beats if b["id"] != beat_id]
        self.service.save_character_arc(
            arc.id,
            SaveCharacterArcRequest(title=arc.title, body="", metadata={**arc.metadata, "instance_beats": trimmed}),
        )
        after = self.service.read_plot_board_projection()
        projected_arc_after = next(a for a in after.arcs if a.id == arc.id)
        self.assertEqual([b.beat_id for b in projected_arc_after.beats], [b["id"] for b in trimmed])
        projected_card_after = next(c for c in after.cards if c.id == card.id)
        self.assertEqual(projected_card_after.beats, [])

    def test_arc_beat_link_leaves_the_card_projection_when_arc_deleted(self) -> None:
        arc = self.service.instantiate_plot_template(_CHARACTER_ARC_TEMPLATE)
        beat_id = arc.metadata["instance_beats"][0]["id"]
        card = self.service.create_card(CreateCardRequest(title="Turning Point"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title=card.title, body="", metadata={"beat_links": [{"plotline": arc.id, "beat_id": beat_id}]}
            ),
        )
        self.service.delete_character_arc(arc.id)
        projection = self.service.read_plot_board_projection()
        self.assertFalse(any(a.id == arc.id for a in projection.arcs))
        projected_card = next(c for c in projection.cards if c.id == card.id)
        self.assertEqual(projected_card.beats, [])


class CharacterArcHttpTests(PlotTestCase):
    """ADR-0080 §6: character-arc CRUD over HTTP — the routes this slice adds,
    mirroring `PlotlineHttpTests` one-for-one (same shared `_*_plot_folder_node`
    machinery, different entry_type/noun)."""

    def _create(self, title: str = "Her Arc") -> dict:
        response = self.client.post("/api/plot/character-arcs", json={"title": title})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_read_list_round_trip(self) -> None:
        created = self._create("The Redemption")
        self.assertTrue(created["id"].startswith("plot_"))
        self.assertEqual(created["entry_type"], "plot:character_arc")

        got = self.client.get(f"/api/plot/character-arcs/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["title"], "The Redemption")

        listing = self.client.get("/api/plot/character-arcs")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn(created["id"], [e["id"] for e in listing.json()["entries"]])

    def test_save_round_trips_character_and_color(self) -> None:
        character = self.client.post(
            "/api/lore", json={"title": "Nera Kovic", "entry_type": "lore:character"}
        ).json()
        created = self._create()
        saved = self.client.put(
            f"/api/plot/character-arcs/{created['id']}",
            json={
                "title": "Renamed",
                "body": "A quiet redemption.",
                "metadata": {"color": "rose", "character": character["id"]},
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        got = self.client.get(f"/api/plot/character-arcs/{created['id']}").json()
        self.assertEqual(got["title"], "Renamed")
        self.assertEqual(got["metadata"]["color"], "rose")
        self.assertEqual(got["metadata"]["character"], character["id"])

    def test_delete_removes_from_list_and_404s(self) -> None:
        created = self._create()
        deleted = self.client.delete(f"/api/plot/character-arcs/{created['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertNotIn(created["id"], [e["id"] for e in deleted.json()["entries"]])
        self.assertEqual(self.client.get(f"/api/plot/character-arcs/{created['id']}").status_code, 404)

    def test_missing_arc_404s(self) -> None:
        self.assertEqual(self.client.get("/api/plot/character-arcs/plot_nope").status_code, 404)

    def test_character_arcs_route_never_shadows_plotlines(self) -> None:
        arc = self._create("An Arc")
        plotline = self.client.post("/api/plot/plotlines", json={"title": "A Thread"}).json()
        arc_ids = [e["id"] for e in self.client.get("/api/plot/character-arcs").json()["entries"]]
        plotline_ids = [e["id"] for e in self.client.get("/api/plot/plotlines").json()["entries"]]
        self.assertIn(arc["id"], arc_ids)
        self.assertNotIn(plotline["id"], arc_ids)
        self.assertIn(plotline["id"], plotline_ids)
        self.assertNotIn(arc["id"], plotline_ids)


if __name__ == "__main__":
    unittest.main()
