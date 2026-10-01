"""One card per scene and story time (ADR-0097 §1, §4, §5; #2375).

A card's `story_rank` is a top-level front-matter key the backend owns: a save
carries it forward, `place` is the only writer, the revision ignores it, and a
snapshot restore keeps the current value. A scene belongs to at most one card.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain
from plot_fixtures import PlotTestCase
from pydantic import ValidationError

from app.models import (
    CreateCardRequest,
    CreateSceneRequest,
    PlaceCardRequest,
    SaveCardRequest,
    StoryPlacement,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.placement import Sibling, content_without_placement
from app.services.project.story_time import (
    drop_card_scene_in_text,
    next_story_rank,
    set_story_rank_in_text,
    story_time_order,
)
from app.services.project_service import ProjectService


def _after(card_id: str) -> PlaceCardRequest:
    return PlaceCardRequest(story=StoryPlacement(after_id=card_id))


def _before(card_id: str) -> PlaceCardRequest:
    return PlaceCardRequest(story=StoryPlacement(before_id=card_id))


class _StoryTestCase(PlotTestCase):
    def _card(self, title: str) -> str:
        return self.service.create_card(CreateCardRequest(title=title)).id

    def _scene(self, title: str = "Scene") -> str:
        return self.service.create_scene(CreateSceneRequest(title=title)).id

    def _attach(self, card_id: str, scene_id: str) -> None:
        card = self.service.read_card(card_id)
        self.service.save_card(
            card_id,
            SaveCardRequest(title=card.title, body=card.body, metadata={**card.metadata, "scene": scene_id}),
        )

    def _path(self, card_id: str) -> Path:
        return self.service._path_for_node_id(card_id, "plot")

    def _story_order(self) -> list[str]:
        cards = self.service.list_cards().entries
        return [card.id for card in sorted(cards, key=lambda card: (card.story_rank is None, card.story_rank or 0, card.id))]


class OneCardPerSceneTests(_StoryTestCase):
    def test_saving_a_held_scene_onto_another_card_is_a_409(self) -> None:
        scene = self._scene()
        first, second = self._card("A"), self._card("B")
        self._attach(first, scene)
        with self.assertRaises(ProjectServiceError) as ctx:
            self._attach(second, scene)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn(scene, str(ctx.exception))
        self.assertIn("A", str(ctx.exception))
        self.assertIn("detach it there first", str(ctx.exception))
        self.assertFalse(self.service.read_card(second).metadata.get("scene"))

    def test_the_409_reaches_the_wire(self) -> None:
        scene = self._scene()
        first, second = self._card("A"), self._card("B")
        self._attach(first, scene)
        response = self.client.put(
            f"/api/plot/cards/{second}", json={"title": "B", "body": "", "metadata": {"scene": scene}}
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_saving_a_card_whose_scene_is_unchanged_never_409s_even_with_a_duplicate_on_disk(self) -> None:
        scene = self._scene()
        first, second = self._card("A"), self._card("B")
        self._attach(first, scene)
        self.plant_duplicate_scene(second, scene)  # the pre-v15 state
        card = self.service.read_card(second)
        saved = self.service.save_card(
            second,
            SaveCardRequest(title="B renamed", body="plan", metadata=card.metadata, base_revision=card.revision),
        )
        self.assertEqual(saved.metadata["scene"], scene)

    def test_changing_a_card_to_a_free_scene_and_clearing_it_is_fine(self) -> None:
        one, two = self._scene("One"), self._scene("Two")
        card = self._card("A")
        self._attach(card, one)
        self._attach(card, two)
        self.service.save_card(card, SaveCardRequest(title="A", metadata={}))
        self.assertFalse(self.service.read_card(card).metadata.get("scene"))

    def test_create_with_a_supplied_id_and_a_held_scene_is_a_409(self) -> None:
        scene = self._scene()
        self._attach(self._card("A"), scene)
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service._create_plot_folder_node(
                title="Restored",
                requested_entry_type="",
                default_entry_type="plot:card",
                noun="card",
                seed_metadata={"scene": scene},
                node_id="plot_restored01",
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_a_restored_card_with_a_free_scene_is_created(self) -> None:
        scene = self._scene()
        new_id = self.service._create_plot_folder_node(
            title="Restored",
            requested_entry_type="",
            default_entry_type="plot:card",
            noun="card",
            seed_metadata={"scene": scene},
            node_id="plot_restored02",
        )
        self.assertEqual(self.service.read_card(new_id).metadata["scene"], scene)


class StoryRankTests(_StoryTestCase):
    def test_new_cards_land_at_the_end_of_story_time(self) -> None:
        a, b, c = self._card("A"), self._card("B"), self._card("C")
        self.assertEqual([self.service.read_card(x).story_rank for x in (a, b, c)], [1, 2, 3])
        self.assertEqual(self._story_order(), [a, b, c])

    def test_create_with_an_id_honours_the_supplied_rank_and_without_one_ignores_it(self) -> None:
        self._card("A")
        restored = self.service.create_card(CreateCardRequest(title="R", id="plot_restore0001", story_rank=7.5))
        self.assertEqual(restored.story_rank, 7.5)
        fresh = self.service.create_card(CreateCardRequest(title="F", story_rank=99))
        self.assertEqual(fresh.story_rank, 8.5)  # one past the highest own rank

    def test_the_rank_is_not_metadata_and_is_on_the_listing(self) -> None:
        card = self.service.read_card(self._card("A"))
        self.assertNotIn("story_rank", card.metadata)
        listed = self.service.list_cards().entries[0]
        self.assertEqual(listed.story_rank, 1)
        self.assertNotIn("story_rank", listed.metadata)

    def test_a_save_keeps_the_disk_rank(self) -> None:
        a, _ = self._card("A"), self._card("B")
        card = self.service.read_card(a)
        self.service.save_card(
            a, SaveCardRequest(title="A2", body="text", metadata=card.metadata, base_revision=card.revision)
        )
        self.assertIn("story_rank: 1\n", self._path(a).read_text(encoding="utf-8"))
        self.assertEqual(self.service.read_card(a).story_rank, 1)

    def test_a_save_cannot_set_the_rank_through_metadata(self) -> None:
        a = self._card("A")
        # It is no schema field, so the save refuses it and the rank stays.
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_card(a, SaveCardRequest(title="A", metadata={"story_rank": 40}))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.service.read_card(a).story_rank, 1)

    def test_a_rank_write_does_not_change_the_revision(self) -> None:
        a, b = self._card("A"), self._card("B")
        opened = self.service.read_card(a)
        self.service.place_card(a, _after(b))  # writes A's own file
        self.assertEqual(self.service.read_card(a).story_rank, 3)
        self.assertEqual(self.service.read_card(a).revision, opened.revision)
        saved = self.service.save_card(
            a, SaveCardRequest(title="A", body="edited", metadata=opened.metadata, base_revision=opened.revision)
        )
        self.assertEqual(saved.story_rank, 3)  # and the save kept it

    def test_the_revision_hash_ignores_the_story_rank_line(self) -> None:
        with_rank = b"---\nid: x\nstory_rank: 3\nmetadata: {}\n---\n\nbody\n"
        without = b"---\nid: x\nmetadata: {}\n---\n\nbody\n"
        self.assertEqual(content_without_placement(with_rank), without)
        # Only the front-matter block: a body line that looks like it stays.
        self.assertIn(b"story_rank: 3", content_without_placement(b"---\nid: x\n---\n\nstory_rank: 3\n"))

    def test_seed_from_manuscript_ranks_in_manuscript_order(self) -> None:
        first = self._scene("First")
        second = self._scene("Second")
        seeded = {c.metadata.get("scene"): c for c in self.service.seed_cards_from_manuscript().entries}
        ranks = [seeded[scene].story_rank for scene in (first, second)]
        self.assertEqual(ranks, sorted(ranks))
        self.assertIsNotNone(ranks[0])
        self.assertEqual(len({c.story_rank for c in seeded.values()}), len(seeded))


class PlaceCardTests(_StoryTestCase):
    def test_place_after_a_neighbour(self) -> None:
        a, b, c = self._card("A"), self._card("B"), self._card("C")
        placed = self.service.place_card(a, _after(b))
        self.assertEqual(self._story_order(), [b, a, c])
        self.assertEqual(placed.id, a)
        self.assertEqual(placed.story_rank, 2.5)

    def test_place_before_a_neighbour(self) -> None:
        a, b, c = self._card("A"), self._card("B"), self._card("C")
        self.service.place_card(c, _before(b))
        self.assertEqual(self._story_order(), [a, c, b])

    def test_place_at_the_front_with_before_id_of_the_first_card(self) -> None:
        a, b, c = self._card("A"), self._card("B"), self._card("C")
        self.service.place_card(c, _before(a))
        self.assertEqual(self._story_order(), [c, a, b])
        self.assertEqual(self.service.read_card(c).story_rank, 0)

    def test_place_to_where_it_already_is_writes_nothing(self) -> None:
        a, b, _ = self._card("A"), self._card("B"), self._card("C")
        before = self._path(a).read_bytes()
        self.service.place_card(a, _before(b))
        self.assertEqual(self._path(a).read_bytes(), before)

    def test_a_rank_write_edits_only_the_rank_line(self) -> None:
        a, b = self._card("A"), self._card("B")
        self.service.save_card(a, SaveCardRequest(title="A", body="Some  body\n\nmore\n", metadata={}))
        old = self._path(a).read_text(encoding="utf-8")
        self.service.place_card(a, _after(b))
        self.assertEqual(self._path(a).read_text(encoding="utf-8"), old.replace("story_rank: 1\n", "story_rank: 3\n"))

    def test_renumbers_when_no_rank_fits(self) -> None:
        a, b, c = self._card("A"), self._card("B"), self._card("C")
        self.service._write_story_rank(self._path(a), 1)
        self.service._write_story_rank(self._path(b), Decimal("1.000001"))
        self.service._write_story_rank(self._path(c), 2)
        self.service.place_card(c, _after(a))  # no decimal fits between 1 and 1.000001
        self.assertEqual(self._story_order(), [a, c, b])
        ranks = [self.service.read_card(x).story_rank for x in (a, c, b)]
        self.assertEqual(len(set(ranks)), 3)
        self.assertEqual(ranks, sorted(ranks))

    def test_a_card_with_no_rank_is_ranked_by_a_place(self) -> None:
        a, b = self._card("A"), self._card("B")
        self.service._write_story_rank(self._path(a), None)
        self.assertIsNone(self.service.read_card(a).story_rank)
        self.service.place_card(a, _before(b))
        self.assertIsNotNone(self.service.read_card(a).story_rank)
        self.assertEqual(self._story_order(), [a, b])

    def test_anchoring_on_itself_or_an_unknown_card_is_a_422(self) -> None:
        a = self._card("A")
        for request in (_after(a), _before("plot_nothere0000")):
            with self.subTest(request=request), self.assertRaises(ProjectServiceError) as ctx:
                self.service.place_card(a, request)
            self.assertEqual(ctx.exception.status_code, 422)

    def test_the_request_needs_exactly_one_neighbour(self) -> None:
        with self.assertRaises(ValidationError):
            StoryPlacement()
        with self.assertRaises(ValidationError):
            StoryPlacement(after_id="a", before_id="b")
        a, b = self._card("A"), self._card("B")
        for story in ({}, {"after_id": b, "before_id": b}):
            response = self.client.post(f"/api/plot/cards/{a}/place", json={"story": story})
            self.assertEqual(response.status_code, 422, response.text)

    def test_the_route_places_and_returns_the_card(self) -> None:
        a, b, c = self._card("A"), self._card("B"), self._card("C")
        response = self.client.post(f"/api/plot/cards/{a}/place", json={"story": {"after_id": c}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], a)
        self.assertEqual(response.json()["story_rank"], 4)
        self.assertEqual(self._story_order(), [b, c, a])

    def test_an_unknown_card_is_a_404(self) -> None:
        a = self._card("A")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.place_card("plot_nothere0000", _after(a))
        self.assertEqual(ctx.exception.status_code, 404)


class LayeredStoryTimeTests(unittest.TestCase):
    """Story time ranks the cards the open layer owns; an inherited card is never
    written and never an anchor (ADR-0097 §5, *Layers*)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        config_dir = Path(self.temp_dir.name).resolve() / "config"
        config_dir.mkdir()
        patcher = patch(
            "app.services.machine_settings.config_path", return_value=config_dir / "config.yaml"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        declare_full_chain(self.service, self.root, self.base)
        (self.series / "plot").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.series / "plot" / "plot_series_card.md", "plot_series_card", "Series Beat", "plot:card", {}, "",
            extra={"story_rank": 1},
        )
        self.own = self.service.create_card(CreateCardRequest(title="Own")).id

    def test_an_inherited_card_cannot_be_moved(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.place_card("plot_series_card", _after(self.own))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_an_inherited_card_cannot_be_an_anchor(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.place_card(self.own, _after("plot_series_card"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_a_new_card_is_ranked_among_the_own_cards_only(self) -> None:
        # The inherited card holds rank 1 in its own layer; this layer's first card is 1 too.
        self.assertEqual(self.service.read_card(self.own).story_rank, 1)
        second = self.service.create_card(CreateCardRequest(title="Own 2"))
        self.assertEqual(second.story_rank, 2)
        self.assertEqual(self.service.read_card("plot_series_card").story_rank, 1)


class SnapshotRestoreTests(_StoryTestCase):
    def _snapshot(self, card_id: str) -> str:
        response = self.client.post(f"/api/nodes/{card_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def _restore(self, card_id: str, snapshot_id: str) -> None:
        response = self.client.post(f"/api/nodes/{card_id}/snapshots/{snapshot_id}/restore")
        self.assertEqual(response.status_code, 200, response.text)

    def test_a_restore_keeps_the_current_story_rank(self) -> None:
        a, b = self._card("A"), self._card("B")
        snapshot = self._snapshot(a)  # taken at rank 1
        self.service.place_card(a, _after(b))  # now 3
        self.service.save_card(a, SaveCardRequest(title="A edited", metadata={}))
        self._restore(a, snapshot)
        card = self.service.read_card(a)
        self.assertEqual(card.title, "A")  # the text went back
        self.assertEqual(card.story_rank, 3)  # the place in story time did not

    def test_a_restore_drops_a_scene_another_card_now_holds(self) -> None:
        scene = self._scene()
        a, b = self._card("A"), self._card("B")
        self._attach(a, scene)
        snapshot = self._snapshot(a)
        self.service.save_card(a, SaveCardRequest(title="A", metadata={}))  # detach
        self._attach(b, scene)  # B takes the scene
        with self.assertLogs("app.services.project.card_story_time", level="WARNING") as logs:
            self._restore(a, snapshot)
        self.assertIn(scene, logs.output[0])
        self.assertFalse(self.service.read_card(a).metadata.get("scene"))
        self.assertEqual(self.service.read_card(b).metadata["scene"], scene)

    def test_a_restore_keeps_a_scene_nobody_else_holds(self) -> None:
        scene = self._scene()
        a = self._card("A")
        self._attach(a, scene)
        snapshot = self._snapshot(a)
        self.service.save_card(a, SaveCardRequest(title="A", metadata={}))
        self._restore(a, snapshot)
        self.assertEqual(self.service.read_card(a).metadata["scene"], scene)


class StoryTimePureTests(unittest.TestCase):
    def test_next_rank_is_one_past_the_highest_or_one(self) -> None:
        self.assertEqual(next_story_rank([]), 1)
        self.assertEqual(next_story_rank([None, None]), 1)
        self.assertEqual(next_story_rank([1, 4.5, None]), Decimal("5.5"))

    def test_order_is_own_first_then_inherited_nearest_layer_first(self) -> None:
        own = [Sibling("o2", 2), Sibling("o1", 1), Sibling("o_unranked", None)]
        inherited = [
            (Sibling("far2", 2), 1),
            (Sibling("near1", 1), 3),
            (Sibling("far1", 1), 1),
            (Sibling("mid1", 1), 2),
            (Sibling("near_tie_b", 5), 3),
            (Sibling("near_tie_a", 5), 3),
        ]
        self.assertEqual(
            story_time_order(own, inherited),
            ["o1", "o2", "o_unranked", "near1", "near_tie_a", "near_tie_b", "mid1", "far1", "far2"],
        )

    def test_set_story_rank_replaces_appends_and_removes_keeping_other_bytes(self) -> None:
        text = "---\nid: x\nentry_type: plot:card\nmetadata: {}\n---\n\nBody  here\n"
        added = set_story_rank_in_text(text, 2)
        self.assertEqual(added, "---\nid: x\nentry_type: plot:card\nmetadata: {}\nstory_rank: 2\n---\n\nBody  here\n")
        self.assertEqual(set_story_rank_in_text(added, Decimal("2.5")).count("story_rank"), 1)
        self.assertIn("story_rank: 2.5\n", set_story_rank_in_text(added, Decimal("2.5")))
        self.assertEqual(set_story_rank_in_text(added, 3.0), added.replace("rank: 2", "rank: 3"))
        self.assertEqual(set_story_rank_in_text(added, None), text)

    def test_set_story_rank_keeps_crlf(self) -> None:
        text = "---\r\nid: x\r\n---\r\n\r\nBody\r\n"
        self.assertEqual(set_story_rank_in_text(text, 1), "---\r\nid: x\r\nstory_rank: 1\r\n---\r\n\r\nBody\r\n")

    def test_drop_card_scene(self) -> None:
        text = "---\nid: x\nentry_type: plot:card\nmetadata:\n  scene: scene_1\n  plotline: pl\n---\n\nBody\n"
        dropped, scene = drop_card_scene_in_text(text)
        self.assertEqual(scene, "scene_1")
        self.assertNotIn("scene", dropped.split("---")[1].replace("entry_type", ""))
        self.assertIn("plotline: pl", dropped)
        self.assertTrue(dropped.endswith("---\n\nBody\n"))
        self.assertEqual(drop_card_scene_in_text(dropped), (dropped, None))


if __name__ == "__main__":
    unittest.main()
