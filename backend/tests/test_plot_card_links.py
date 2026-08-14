"""Backend tests for card→beat links + the page-status marker (ADR-0048 S7 Slice 3b; ADR-0053).

A `plot:card` can name which beats it fulfils — a `beat_links` list, each item a
*(plotline id, beat id)* pair — and declares whether its beat is realized in prose
(`page_status` = on_page / off_page / unwritten). Both are plot-local: the link
members are plain text (v1 bars refs from list-item shapes), so plot.py heals
dangling links itself, on card save AND read, the same two-path symmetry the `scene`
ref has. `on_page` is derived from the scene attachment, not authored.

These prove the healing and the derivation end-to-end through the HTTP surface,
building on the stable beat ids of Slice 3a (#779). A plotline is a plot-template
instance (ADR-0053 §1), so a card's beats link to plotlines.
"""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    CreateSceneRequest,
    CreateStructureNodeRequest,
)

_THREE_ACT = "builtin-plot-three-act-story-arc"


class _CardLinkTestCase(PlotTestCase):
    def _new_card(self, title: str = "Card") -> str:
        created = self.client.post("/api/plot/cards", json={"title": title})
        self.assertEqual(created.status_code, 200, created.text)
        return created.json()["id"]

    def _save_card(self, card_id: str, metadata: dict, *, title: str = "Card", body: str = "") -> dict:
        saved = self.client.put(
            f"/api/plot/cards/{card_id}",
            json={"title": title, "body": body, "metadata": metadata},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        return saved.json()

    def _read_card(self, card_id: str) -> dict:
        got = self.client.get(f"/api/plot/cards/{card_id}")
        self.assertEqual(got.status_code, 200, got.text)
        return got.json()

    def _plotline(self) -> dict:
        """An instantiated three-act plotline — 7 beats, each with a stable id."""
        response = self.client.post(f"/api/plot/templates/{_THREE_ACT}/instantiate")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _scene(self, title: str = "A Scene") -> str:
        structure = self.service.read_structure()
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter", entry_type="scene:chapter", parent_id=structure.root.id)
        )
        chapter_id = next(
            c.id for c in self.service.read_structure().root.children if c.type == "scene:chapter"
        )
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=chapter_id)).id


class CardBeatLinkTests(_CardLinkTestCase):
    def test_a_link_to_a_live_beat_round_trips(self) -> None:
        plotline = self._plotline()
        beat_id = plotline["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(card, {"beat_links": [{"plotline": plotline["id"], "beat_id": beat_id}]})
        links = self._read_card(card)["metadata"]["beat_links"]
        self.assertEqual(links, [{"plotline": plotline["id"], "beat_id": beat_id}])

    def test_a_card_can_link_several_beats_across_plotlines(self) -> None:
        # The headline of 3b (Anton): multiple beats per card, across plotlines. Two
        # beats of one plotline plus a beat of a second prove the list + the composite
        # key (ADR-0053 §4: a card fulfils beats from several plotlines).
        a = self._plotline()
        b = self._plotline()
        a_beats = a["metadata"]["instance_beats"]
        b_beats = b["metadata"]["instance_beats"]
        wanted = [
            {"plotline": a["id"], "beat_id": a_beats[0]["id"]},
            {"plotline": a["id"], "beat_id": a_beats[3]["id"]},
            {"plotline": b["id"], "beat_id": b_beats[1]["id"]},
        ]
        card = self._new_card()
        self._save_card(card, {"beat_links": wanted})
        self.assertEqual(self._read_card(card)["metadata"]["beat_links"], wanted)

    def test_a_link_to_a_deleted_plotline_is_dropped_on_read(self) -> None:
        # The read-side heal: the link is fine at save time, then the plotline is
        # deleted out from under it. Because the link is text (not an entity_ref),
        # the delete's reference purge never touches it — plot.py's read heal must.
        plotline = self._plotline()
        beat_id = plotline["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(card, {"beat_links": [{"plotline": plotline["id"], "beat_id": beat_id}]})
        self.assertEqual(len(self._read_card(card)["metadata"]["beat_links"]), 1)
        deleted = self.client.delete(f"/api/plot/plotlines/{plotline['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        # Plotline gone → the link resolves to nothing → dropped, and an all-dropped
        # list heals to sparse (key absent), not an empty [].
        self.assertNotIn("beat_links", self._read_card(card)["metadata"])

    def test_a_link_to_a_removed_beat_is_dropped_on_read(self) -> None:
        # The plotline survives but the specific beat leaves its roster — the other
        # half of the healing the map says 3b owns.
        plotline = self._plotline()
        beats = plotline["metadata"]["instance_beats"]
        doomed = beats[-1]["id"]
        survivor = beats[0]["id"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"plotline": plotline["id"], "beat_id": survivor},
                    {"plotline": plotline["id"], "beat_id": doomed},
                ]
            },
        )
        # Drop the last beat from the plotline's roster and save the plotline.
        trimmed = beats[:-1]
        saved = self.client.put(
            f"/api/plot/plotlines/{plotline['id']}",
            json={"title": plotline["title"], "body": "", "metadata": {**plotline["metadata"], "instance_beats": trimmed}},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        links = self._read_card(card)["metadata"]["beat_links"]
        self.assertEqual(links, [{"plotline": plotline["id"], "beat_id": survivor}])

    def test_save_drops_a_dangling_link_without_422(self) -> None:
        # The save-side heal (independent of read): a link to a ghost plotline must
        # not 422 the save (the members are text — nothing to validate against) and
        # must not reach disk; a valid sibling link is kept.
        plotline = self._plotline()
        beat_id = plotline["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"plotline": "plot_ghost", "beat_id": "beat_deadbeef"},
                    {"plotline": plotline["id"], "beat_id": beat_id},
                ]
            },
        )
        self.assertEqual(
            self._read_card(card)["metadata"]["beat_links"],
            [{"plotline": plotline["id"], "beat_id": beat_id}],
        )

    def test_an_incomplete_link_is_dropped(self) -> None:
        # Half a pair points nowhere — a blank plotline or a blank beat_id is dropped.
        plotline = self._plotline()
        beat_id = plotline["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"plotline": plotline["id"], "beat_id": ""},
                    {"plotline": "", "beat_id": beat_id},
                ]
            },
        )
        self.assertNotIn("beat_links", self._read_card(card)["metadata"])

    def test_duplicate_links_are_collapsed(self) -> None:
        # A card fulfils a beat once — a repeated (plotline, beat_id) pair is deduped
        # so the stored list stays canonical for the edge/diagnostic consumers later.
        plotline = self._plotline()
        beat_id = plotline["metadata"]["instance_beats"][0]["id"]
        link = {"plotline": plotline["id"], "beat_id": beat_id}
        card = self._new_card()
        self._save_card(card, {"beat_links": [link, dict(link)]})
        self.assertEqual(self._read_card(card)["metadata"]["beat_links"], [link])


class CardPageStatusTests(_CardLinkTestCase):
    def test_a_scene_link_derives_on_page(self) -> None:
        scene_id = self._scene()
        card = self._new_card()
        self._save_card(card, {"scene": scene_id})
        self.assertEqual(self._read_card(card)["metadata"]["page_status"], "on_page")

    def test_a_scene_overrides_an_authored_off_page(self) -> None:
        # on_page is DERIVED — a card with a scene is on the page, whatever the
        # writer typed. The scene wins.
        scene_id = self._scene()
        card = self._new_card()
        self._save_card(card, {"scene": scene_id, "page_status": "off_page"})
        self.assertEqual(self._read_card(card)["metadata"]["page_status"], "on_page")

    def test_off_page_is_preserved_without_a_scene(self) -> None:
        card = self._new_card()
        self._save_card(card, {"page_status": "off_page"})
        self.assertEqual(self._read_card(card)["metadata"]["page_status"], "off_page")

    def test_unwritten_is_the_sparse_default(self) -> None:
        # A scene-less card with no authored status stays blank on disk — which
        # reads as `unwritten`. No value is materialized (sparse-spec).
        card = self._new_card()
        self._save_card(card, {})
        self.assertNotIn("page_status", self._read_card(card)["metadata"])

    def test_removing_the_scene_clears_a_stale_on_page(self) -> None:
        # Attach a scene (→ on_page), then re-save with the scene gone but the stale
        # on_page still in the payload — the derivation clears it back to blank.
        scene_id = self._scene()
        card = self._new_card()
        self._save_card(card, {"scene": scene_id})
        self.assertEqual(self._read_card(card)["metadata"]["page_status"], "on_page")
        self._save_card(card, {"page_status": "on_page"})  # scene removed from the payload
        self.assertNotIn("page_status", self._read_card(card)["metadata"])

    def test_deleting_the_scene_clears_on_page_on_read(self) -> None:
        # The purge path, not a re-save: delete_scene blanks the card's scene ref but
        # never re-derives page_status, so the on-disk `on_page` goes stale until the
        # read-side heal clears it. Proves the derivation's two-path symmetry against a
        # real scene delete (the scene ref's own purge-on-delete + heal-on-read).
        scene_id = self._scene()
        card = self._new_card()
        self._save_card(card, {"scene": scene_id})
        self.assertEqual(self._read_card(card)["metadata"]["page_status"], "on_page")
        self.service.delete_scene(scene_id)
        metadata = self._read_card(card)["metadata"]
        self.assertFalse(metadata.get("scene"))  # ref purged
        self.assertNotIn("page_status", metadata)  # stale on_page healed away on read


class CardBeatBadgeProjectionTests(_CardLinkTestCase):
    """The board projection (ADR-0048 S7 Slice 5b; ADR-0053) resolves a card's beat
    links into titled badges and carries the derived page_status — display over the
    stored id pairs, so the frontend renders labels + the marker without its own join."""

    def _projected_card(self, card_id: str) -> dict:
        projection = self.client.get("/api/plot/board/projection")
        self.assertEqual(projection.status_code, 200, projection.text)
        return next(c for c in projection.json()["cards"] if c["id"] == card_id)

    def test_a_linked_beat_projects_as_a_titled_badge(self) -> None:
        plotline = self._plotline()
        beat = plotline["metadata"]["instance_beats"][0]
        card = self._new_card()
        self._save_card(card, {"beat_links": [{"plotline": plotline["id"], "beat_id": beat["id"]}]})
        beats = self._projected_card(card)["beats"]
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0]["beat_id"], beat["id"])
        self.assertEqual(beats[0]["title"], beat["title"])
        self.assertEqual(beats[0]["plotline_id"], plotline["id"])
        self.assertEqual(beats[0]["plotline_title"], plotline["title"])
        # A plotline with no colour resolves a null badge colour (the neutral chip).
        self.assertIsNone(beats[0]["plotline_color"])
        # The badge carries the beat's 1-based roster position (#941).
        self.assertEqual(beats[0]["number"], 1)

    def test_a_badge_carries_its_1based_roster_number(self) -> None:
        # The badge shows the beat's position in its plotline's roster (#941) so two
        # same-titled beats are tellable apart. b[2] is beat 3, b[0] is beat 1 — the
        # number follows the roster, not the (reversed) stored link order.
        plotline = self._plotline()
        b = plotline["metadata"]["instance_beats"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"plotline": plotline["id"], "beat_id": b[2]["id"]},
                    {"plotline": plotline["id"], "beat_id": b[0]["id"]},
                ]
            },
        )
        numbers = [beat["number"] for beat in self._projected_card(card)["beats"]]
        self.assertEqual(numbers, [3, 1])

    def test_a_beat_badge_carries_its_plotlines_colour(self) -> None:
        # The board tints a card's beat badges by their owning plotline's colour so
        # same-named beats of different plotlines are told apart (usability pass).
        plotline = self._plotline()
        beat = plotline["metadata"]["instance_beats"][0]
        self.assertEqual(
            self.client.put(
                f"/api/plot/plotlines/{plotline['id']}",
                json={"title": plotline["title"], "body": "", "metadata": {**plotline["metadata"], "color": "rose"}},
            ).status_code,
            200,
        )
        card = self._new_card()
        self._save_card(card, {"beat_links": [{"plotline": plotline["id"], "beat_id": beat["id"]}]})
        self.assertEqual(self._projected_card(card)["beats"][0]["plotline_color"], "rose")

    def test_badges_follow_the_stored_link_order(self) -> None:
        plotline = self._plotline()
        b = plotline["metadata"]["instance_beats"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"plotline": plotline["id"], "beat_id": b[2]["id"]},
                    {"plotline": plotline["id"], "beat_id": b[0]["id"]},
                ]
            },
        )
        titles = [beat["title"] for beat in self._projected_card(card)["beats"]]
        self.assertEqual(titles, [b[2]["title"], b[0]["title"]])

    def test_a_badge_is_dropped_when_its_plotline_is_deleted(self) -> None:
        # Deleting the plotline never rewrites the card (a link heals only on the
        # card's own read/save, and beat_links is plain text so the ref purge skips
        # it), so the projection drops the badge display-side against the live catalog.
        plotline = self._plotline()
        beat = plotline["metadata"]["instance_beats"][0]
        card = self._new_card()
        self._save_card(card, {"beat_links": [{"plotline": plotline["id"], "beat_id": beat["id"]}]})
        self.assertEqual(self.client.delete(f"/api/plot/plotlines/{plotline['id']}").status_code, 200)
        self.assertEqual(self._projected_card(card)["beats"], [])

    def test_an_unlinked_card_projects_no_badges(self) -> None:
        card = self._new_card()
        self._save_card(card, {})
        self.assertEqual(self._projected_card(card)["beats"], [])

    def test_projection_derives_on_page_from_the_scene(self) -> None:
        scene_id = self._scene()
        card = self._new_card()
        self._save_card(card, {"scene": scene_id})
        self.assertEqual(self._projected_card(card)["page_status"], "on_page")

    def test_projection_carries_an_authored_off_page(self) -> None:
        card = self._new_card()
        self._save_card(card, {"page_status": "off_page"})
        self.assertEqual(self._projected_card(card)["page_status"], "off_page")

    def test_projection_page_status_is_null_when_unwritten(self) -> None:
        card = self._new_card()
        self._save_card(card, {})
        self.assertIsNone(self._projected_card(card)["page_status"])

    def test_projection_clears_a_stale_on_page_after_the_scene_is_deleted(self) -> None:
        # delete_scene purges the scene ref but never re-derives page_status; the
        # projection derives from the CURRENT scene, so a since-detached card reads
        # unwritten (null), never a stale on_page.
        scene_id = self._scene()
        card = self._new_card()
        self._save_card(card, {"scene": scene_id})
        self.service.delete_scene(scene_id)
        projected = self._projected_card(card)
        self.assertIsNone(projected["scene"])
        self.assertIsNone(projected["page_status"])


class CardFollowUpsTests(_CardLinkTestCase):
    """The follow-up list (ADR-0048 S8c): a flat text `list` the writer hand-edits
    — loose "still to do on this card" notes, the light remains of the quarry's
    claims/evidence apparatus. Deleting an item is the "done" gesture, so there is
    no per-item state; these pin that the list round-trips and re-saves shorter."""

    def test_follow_ups_round_trips_as_a_flat_text_list(self) -> None:
        card = self._new_card()
        self._save_card(card, {"follow_ups": ["name the tavern", "check the timeline"]})
        self.assertEqual(
            self._read_card(card)["metadata"]["follow_ups"],
            ["name the tavern", "check the timeline"],
        )

    def test_deleting_an_item_is_the_done_gesture(self) -> None:
        card = self._new_card()
        self._save_card(card, {"follow_ups": ["a", "b", "c"]})
        # Marking one "done" = re-saving the shorter list (no per-item flag).
        self._save_card(card, {"follow_ups": ["a", "c"]})
        self.assertEqual(self._read_card(card)["metadata"]["follow_ups"], ["a", "c"])
