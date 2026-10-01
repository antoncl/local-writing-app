"""A planned card has a position in a container and no scene (ADR-0097 §6, §8; #2379).

`place` plans an unwritten card in a manuscript container after a scene; Write as
scene slots the scene there and re-anchors the later planned cards; the board
projects the card into that container with a sort key.
"""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    AttachCardRequest,
    CreateCardRequest,
    CreateDeckRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    DetachCardRequest,
    PlaceCardRequest,
    PlaceTo,
    RealizeCardRequest,
    SaveCardRequest,
    StoryPlacement,
)
from app.services.project.errors import ProjectServiceError
from app.services.tree_structure import TreeStructureService


class _PlannedCase(PlotTestCase):
    def _container(self, title: str = "Act One") -> str:
        document = self.service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type="manuscript:container")
        )
        return next(n.id for n in document.root.children if n.title == title)

    def _scene(self, container: str, title: str = "Scene") -> str:
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=container)).id

    def _card(self, title: str = "Card", body: str = "") -> str:
        card = self.service.create_card(CreateCardRequest(title=title))
        if body:
            self.service.save_card(card.id, SaveCardRequest(title=title, body=body, base_revision=card.revision))
        return card.id

    def _plan(self, card_id: str, container: str, after: str | None = None):
        return self.service.place_card(
            card_id, PlaceCardRequest(to=PlaceTo(planned_in=container, planned_after=after))
        )

    def _children(self, container: str) -> list[str]:
        node = TreeStructureService.find_node(self.service.read_structure(), container)
        return [child.id for child in node.children]

    def _index(self, scene_id: str) -> int:
        """The scene's manuscript reading index (the starter project already holds a scene)."""
        return self.service._board_layout().scene_to_order[scene_id]

    def _projected(self, card_id: str):
        return next(c for c in self.service.read_plot_board_projection().cards if c.id == card_id)


class PlaceToPlannedTests(_PlannedCase):
    def test_place_plans_a_card_in_a_container_after_a_scene(self) -> None:
        act = self._container()
        scene = self._scene(act)
        card = self._card()
        placed = self._plan(card, act, scene)
        self.assertEqual(placed.metadata["planned_in"], act)
        self.assertEqual(placed.metadata["planned_after"], scene)
        self.assertFalse(placed.metadata.get("scene"))

    def test_a_card_created_in_a_container_is_planned_there(self) -> None:
        act = self._container()
        scene = self._scene(act)
        card = self.service.create_card(
            CreateCardRequest(title="New", to=PlaceTo(planned_in=act, planned_after=scene))
        )
        self.assertEqual(card.metadata["planned_in"], act)
        self.assertEqual(card.metadata["planned_after"], scene)
        with self.assertRaises(ProjectServiceError) as raised:
            self.service.create_card(CreateCardRequest(title="Bad", to=PlaceTo(planned_in=scene)))
        self.assertEqual(raised.exception.status_code, 422)

    def test_planning_first_leaves_planned_after_unset(self) -> None:
        act = self._container()
        card = self._card()
        placed = self._plan(card, act)
        self.assertEqual(placed.metadata["planned_in"], act)
        self.assertNotIn("planned_after", placed.metadata)

    def test_planning_keeps_the_home_deck(self) -> None:
        act = self._container()
        deck = self.service.create_deck(CreateDeckRequest(title="Deck")).id
        card = self._card()
        self.service.place_card(card, PlaceCardRequest(to=PlaceTo(deck=deck)))
        placed = self._plan(card, act)
        self.assertEqual(placed.metadata["plot_deck"], deck)
        self.assertEqual(placed.metadata["planned_in"], act)

    def test_a_planned_to_can_carry_story_time_too(self) -> None:
        act = self._container()
        first, second, third = self._card("A"), self._card("B"), self._card("C")
        self.service.place_card(
            third,
            PlaceCardRequest(
                to=PlaceTo(planned_in=act), story=StoryPlacement(after_id=first)
            ),
        )
        order = [c.id for c in sorted(self.service.read_plot_board_projection().cards, key=lambda c: c.story_order)]
        self.assertEqual(order, [first, third, second])

    def test_deck_or_loose_clears_the_planned_fields(self) -> None:
        act = self._container()
        scene = self._scene(act)
        deck = self.service.create_deck(CreateDeckRequest(title="Deck")).id
        card = self._card()
        self._plan(card, act, scene)
        in_deck = self.service.place_card(card, PlaceCardRequest(to=PlaceTo(deck=deck)))
        self.assertNotIn("planned_in", in_deck.metadata)
        self.assertNotIn("planned_after", in_deck.metadata)
        self.assertEqual(in_deck.metadata["plot_deck"], deck)
        self._plan(card, act, scene)
        loose = self.service.place_card(card, PlaceCardRequest(to=PlaceTo(loose=True)))
        self.assertNotIn("planned_in", loose.metadata)
        self.assertNotIn("plot_deck", loose.metadata)

    def test_a_written_card_refuses_a_planned_to(self) -> None:
        act = self._container()
        scene = self._scene(act)
        card = self._card()
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        with self.assertRaises(ProjectServiceError) as raised:
            self._plan(card, act, scene)
        self.assertEqual(raised.exception.status_code, 409)

    def test_a_target_that_is_not_a_container_is_422(self) -> None:
        act = self._container()
        scene = self._scene(act)
        card = self._card()
        for bad in (scene, "no-such-node"):
            with self.assertRaises(ProjectServiceError) as raised:
                self._plan(card, bad)
            self.assertEqual(raised.exception.status_code, 422)

    def test_an_anchor_that_is_not_a_scene_is_422(self) -> None:
        act = self._container()
        card = self._card()
        with self.assertRaises(ProjectServiceError) as raised:
            self._plan(card, act, act)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertNotIn("planned_in", self.service.read_card(card).metadata)

    def test_the_wire_rejects_planned_after_without_planned_in(self) -> None:
        card = self._card()
        response = self.client.post(
            f"/api/plot/cards/{card}/place", json={"to": {"loose": True, "planned_after": "x"}}
        )
        self.assertEqual(response.status_code, 422)


class PlannedFieldsAreEndpointOwnedTests(_PlannedCase):
    def test_save_card_ignores_the_clients_planned_fields(self) -> None:
        act = self._container()
        scene = self._scene(act)
        other = self._container("Act Two")
        card = self._card()
        self._plan(card, act, scene)
        current = self.service.read_card(card)
        saved = self.service.save_card(
            card,
            SaveCardRequest(
                title=current.title,
                body=current.body,
                base_revision=current.revision,
                metadata={**current.metadata, "planned_in": other, "planned_after": None},
            ),
        )
        self.assertEqual(saved.metadata["planned_in"], act)
        self.assertEqual(saved.metadata["planned_after"], scene)

    def test_save_card_cannot_plan_an_unplanned_card(self) -> None:
        act = self._container()
        card = self._card()
        current = self.service.read_card(card)
        saved = self.service.save_card(
            card,
            SaveCardRequest(
                title=current.title,
                body=current.body,
                base_revision=current.revision,
                metadata={"planned_in": act},
            ),
        )
        self.assertNotIn("planned_in", saved.metadata)

    def test_attach_clears_the_planned_fields(self) -> None:
        act = self._container()
        scene = self._scene(act, "S")
        card = self._card()
        self._plan(card, act, scene)
        attached = self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        self.assertNotIn("planned_in", attached.metadata)
        self.assertNotIn("planned_after", attached.metadata)
        detached = self.service.detach_card(card, DetachCardRequest())
        self.assertNotIn("planned_in", detached.metadata)

    def test_a_deleted_container_heals_the_ref_away(self) -> None:
        act = self._container()
        card = self._card()
        self._plan(card, act)
        self.service.delete_structure_node(act)
        card_after = self.service.read_card(card)
        self.assertFalse(card_after.metadata.get("planned_in"))
        projected = self._projected(card)
        self.assertIsNone(projected.planned_in)
        self.assertIsNone(projected.container)


class RealizePlannedTests(_PlannedCase):
    def test_the_scene_lands_right_after_the_anchor(self) -> None:
        act = self._container()
        s1, s2 = self._scene(act, "S1"), self._scene(act, "S2")
        card = self._card("Plan", "What happens.")
        self._plan(card, act, s1)
        result = self.service.realize_card(card, RealizeCardRequest())
        self.assertEqual(self._children(act), [s1, result.metadata["scene"], s2])
        self.assertEqual(result.reanchored, [])
        for key in ("planned_in", "planned_after"):
            self.assertNotIn(key, result.metadata)
        scene = self.service.read_scene(result.metadata["scene"])
        self.assertEqual(scene.title, "Plan")
        self.assertEqual(scene.metadata["summary"], "What happens.")

    def test_the_scene_lands_first_when_there_is_no_anchor(self) -> None:
        act = self._container()
        s1 = self._scene(act, "S1")
        card = self._card("Plan")
        self._plan(card, act)
        result = self.service.realize_card(card, RealizeCardRequest())
        self.assertEqual(self._children(act), [result.metadata["scene"], s1])

    def test_a_planned_card_ignores_parent_id(self) -> None:
        act, elsewhere = self._container(), self._container("Act Two")
        s1 = self._scene(act, "S1")
        card = self._card("Plan")
        self._plan(card, act, s1)
        result = self.service.realize_card(card, RealizeCardRequest(parent_id=elsewhere))
        self.assertIn(result.metadata["scene"], self._children(act))
        self.assertEqual(self._children(elsewhere), [])

    def test_an_unplanned_card_realizes_as_before(self) -> None:
        act = self._container()
        card = self._card("Plan")
        result = self.service.realize_card(card, RealizeCardRequest(parent_id=act))
        self.assertEqual(self._children(act), [result.metadata["scene"]])
        self.assertEqual(result.reanchored, [])

    def _two_planned_after(self):
        act = self._container()
        s = self._scene(act, "S")
        p1, p2 = self._card("P1"), self._card("P2")
        self._plan(p1, act, s)
        self._plan(p2, act, s)  # P1 was created first, so it is earlier in story time
        return act, s, p1, p2

    def test_writing_the_earlier_card_first_re_anchors_the_later_one(self) -> None:
        act, s, p1, p2 = self._two_planned_after()
        first = self.service.realize_card(p1, RealizeCardRequest())
        self.assertEqual(first.reanchored, [p2])
        self.assertEqual(self.service.read_card(p2).metadata["planned_after"], first.metadata["scene"])
        second = self.service.realize_card(p2, RealizeCardRequest())
        self.assertEqual(second.reanchored, [])
        self.assertEqual(
            self._children(act), [s, first.metadata["scene"], second.metadata["scene"]]
        )

    def test_writing_the_later_card_first_keeps_the_order(self) -> None:
        act, s, p1, p2 = self._two_planned_after()
        later = self.service.realize_card(p2, RealizeCardRequest())
        self.assertEqual(later.reanchored, [])  # P1 is earlier in story time
        self.assertEqual(self.service.read_card(p1).metadata["planned_after"], s)
        earlier = self.service.realize_card(p1, RealizeCardRequest())
        self.assertEqual(earlier.reanchored, [])
        self.assertEqual(
            self._children(act), [s, earlier.metadata["scene"], later.metadata["scene"]]
        )

    def test_cards_after_a_different_scene_are_not_re_anchored(self) -> None:
        act = self._container()
        s1, s2 = self._scene(act, "S1"), self._scene(act, "S2")
        p1, p2 = self._card("P1"), self._card("P2")
        self._plan(p1, act, s1)
        self._plan(p2, act, s2)
        result = self.service.realize_card(p1, RealizeCardRequest())
        self.assertEqual(result.reanchored, [])
        self.assertEqual(self.service.read_card(p2).metadata["planned_after"], s2)


class PlannedProjectionTests(_PlannedCase):
    def test_a_planned_card_shows_in_its_container_after_its_anchor(self) -> None:
        act = self._container()
        s1, s2 = self._scene(act, "S1"), self._scene(act, "S2")
        card = self._card()
        self._plan(card, act, s1)
        projected = self._projected(card)
        self.assertEqual(projected.container, act)
        self.assertEqual(projected.planned_in, act)
        self.assertEqual(projected.planned_after, s1)
        self.assertEqual(projected.container_order, self._index(s1) + 0.5)
        self.assertIsNone(projected.scene)
        writer = self._card("Writer")
        self.service.attach_card(writer, AttachCardRequest(scene_id=s2))
        self.assertGreater(self._projected(writer).container_order, projected.container_order)

    def test_a_written_card_orders_by_its_scenes_reading_index(self) -> None:
        act = self._container()
        s1, s2 = self._scene(act, "S1"), self._scene(act, "S2")
        card = self._card()
        self.service.attach_card(card, AttachCardRequest(scene_id=s2))
        projected = self._projected(card)
        self.assertEqual(projected.container, act)
        self.assertEqual(projected.container_order, self._index(s2))
        self.assertEqual(projected.container_order, self._index(s1) + 1)
        self.assertIsNone(projected.planned_in)

    def test_a_card_planned_first_sorts_before_the_first_scene(self) -> None:
        first = self._container("Act One")
        self._scene(first, "S0")
        act = self._container("Act Two")
        s1 = self._scene(act, "S1")
        card = self._card()
        self._plan(card, act)
        self.assertEqual(self._projected(card).container_order, self._index(s1) - 0.5)

    def test_planned_in_an_empty_container_sorts_at_its_position(self) -> None:
        first = self._container("Act One")
        s0 = self._scene(first, "S0")
        empty = self._container("Act Two")
        card = self._card()
        self._plan(card, empty)
        projected = self._projected(card)
        self.assertEqual(projected.container, empty)
        self.assertEqual(projected.container_order, self._index(s0) + 0.5)

    def test_an_anchor_that_left_the_container_shows_first(self) -> None:
        act, other = self._container(), self._container("Act Two")
        s1, s2 = self._scene(act, "S1"), self._scene(act, "S2")
        card = self._card()
        self._plan(card, act, s2)
        self.service.move_structure_node(s2, other, 0)
        projected = self._projected(card)
        self.assertEqual(projected.planned_after, s2)
        self.assertEqual(projected.container, act)
        self.assertEqual(projected.container_order, self._index(s1) - 0.5)

    def test_an_unwritten_unplanned_card_has_no_container_order(self) -> None:
        card = self._card()
        projected = self._projected(card)
        self.assertIsNone(projected.container_order)
        self.assertIsNone(projected.planned_in)
        self.assertIsNone(projected.planned_after)

    def test_a_deleted_anchor_heals_away_and_the_card_shows_first(self) -> None:
        act = self._container()
        s1 = self._scene(act, "S1")
        s2 = self._scene(act, "S2")
        card = self._card()
        self._plan(card, act, s1)
        self.service.delete_structure_node(s1)
        projected = self._projected(card)
        self.assertIsNone(projected.planned_after)
        self.assertEqual(projected.container, act)
        self.assertEqual(projected.container_order, self._index(s2) - 0.5)
