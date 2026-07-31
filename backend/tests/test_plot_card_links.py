"""Backend tests for card→beat links + the page-status marker (ADR-0048 S7 Slice 3b).

A `plot:card` can name which beats it fulfils — a `beat_links` list, each item a
*(template-instance id, beat id)* pair — and declares whether its beat is realized
in prose (`page_status` = on_page / off_page / unwritten). Both are plot-local:
the link members are plain text (v1 bars refs from list-item shapes), so plot.py
heals dangling links itself, on card save AND read, the same two-path symmetry the
`scene` ref has. `on_page` is derived from the scene attachment, not authored.

These prove the healing and the derivation end-to-end through the HTTP surface,
building on the stable beat ids of Slice 3a (#779).
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

    def _instance(self) -> dict:
        """An instantiated three-act instance — 7 beats, each with a stable id."""
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
        instance = self._instance()
        beat_id = instance["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(card, {"beat_links": [{"instance": instance["id"], "beat_id": beat_id}]})
        links = self._read_card(card)["metadata"]["beat_links"]
        self.assertEqual(links, [{"instance": instance["id"], "beat_id": beat_id}])

    def test_a_card_can_link_several_beats_across_instances(self) -> None:
        # The headline of 3b (Anton): multiple beats per card. Two beats of one
        # instance plus a beat of a second prove the list + the composite key.
        a = self._instance()
        b = self._instance()
        a_beats = a["metadata"]["instance_beats"]
        b_beats = b["metadata"]["instance_beats"]
        wanted = [
            {"instance": a["id"], "beat_id": a_beats[0]["id"]},
            {"instance": a["id"], "beat_id": a_beats[3]["id"]},
            {"instance": b["id"], "beat_id": b_beats[1]["id"]},
        ]
        card = self._new_card()
        self._save_card(card, {"beat_links": wanted})
        self.assertEqual(self._read_card(card)["metadata"]["beat_links"], wanted)

    def test_a_link_to_a_deleted_instance_is_dropped_on_read(self) -> None:
        # The read-side heal: the link is fine at save time, then the instance is
        # deleted out from under it. Because the link is text (not an entity_ref),
        # the delete's reference purge never touches it — plot.py's read heal must.
        instance = self._instance()
        beat_id = instance["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(card, {"beat_links": [{"instance": instance["id"], "beat_id": beat_id}]})
        self.assertEqual(len(self._read_card(card)["metadata"]["beat_links"]), 1)
        deleted = self.client.delete(f"/api/plot/instances/{instance['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        # Instance gone → the link resolves to nothing → dropped, and an all-dropped
        # list heals to sparse (key absent), not an empty [].
        self.assertNotIn("beat_links", self._read_card(card)["metadata"])

    def test_a_link_to_a_removed_beat_is_dropped_on_read(self) -> None:
        # The instance survives but the specific beat leaves its roster — the other
        # half of the healing the map says 3b owns.
        instance = self._instance()
        beats = instance["metadata"]["instance_beats"]
        doomed = beats[-1]["id"]
        survivor = beats[0]["id"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"instance": instance["id"], "beat_id": survivor},
                    {"instance": instance["id"], "beat_id": doomed},
                ]
            },
        )
        # Drop the last beat from the instance's roster and save the instance.
        trimmed = beats[:-1]
        saved = self.client.put(
            f"/api/plot/instances/{instance['id']}",
            json={"title": instance["title"], "body": "", "metadata": {**instance["metadata"], "instance_beats": trimmed}},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        links = self._read_card(card)["metadata"]["beat_links"]
        self.assertEqual(links, [{"instance": instance["id"], "beat_id": survivor}])

    def test_save_drops_a_dangling_link_without_422(self) -> None:
        # The save-side heal (independent of read): a link to a ghost instance must
        # not 422 the save (the members are text — nothing to validate against) and
        # must not reach disk; a valid sibling link is kept.
        instance = self._instance()
        beat_id = instance["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"instance": "plot_ghost", "beat_id": "beat_deadbeef"},
                    {"instance": instance["id"], "beat_id": beat_id},
                ]
            },
        )
        self.assertEqual(
            self._read_card(card)["metadata"]["beat_links"],
            [{"instance": instance["id"], "beat_id": beat_id}],
        )

    def test_an_incomplete_link_is_dropped(self) -> None:
        # Half a pair points nowhere — a blank instance or a blank beat_id is dropped.
        instance = self._instance()
        beat_id = instance["metadata"]["instance_beats"][0]["id"]
        card = self._new_card()
        self._save_card(
            card,
            {
                "beat_links": [
                    {"instance": instance["id"], "beat_id": ""},
                    {"instance": "", "beat_id": beat_id},
                ]
            },
        )
        self.assertNotIn("beat_links", self._read_card(card)["metadata"])


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
