"""Decks (ADR-0097 §2, §4, §8; #2378): the `plot:deck` node and its CRUD, a card's
home deck through `place` / create, and the board projection's decks, containers
and per-card `deck`."""

from __future__ import annotations

from plot_fixtures import PlotTestCase
from pydantic import ValidationError

from app.models import (
    AttachCardRequest,
    CreateCardRequest,
    CreateDeckRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    PlaceCardRequest,
    PlaceTo,
    SaveDeckRequest,
    StoryPlacement,
)
from app.services.project.decks import DECK_FIELD
from app.services.project.errors import ProjectServiceError


class _DeckTestCase(PlotTestCase):
    def _deck(self, title: str, parent: str = "") -> str:
        return self.service.create_deck(CreateDeckRequest(title=title, plot_deck=parent)).id

    def _card(self, title: str, to: PlaceTo | None = None) -> str:
        return self.service.create_card(CreateCardRequest(title=title, to=to)).id

    def _story_order(self) -> list[str]:
        cards = self.service.list_cards().entries
        return [c.id for c in sorted(cards, key=lambda c: (c.story_rank is None, c.story_rank or 0, c.id))]

    def _home(self, card_id: str) -> object:
        return self.service.read_card(card_id).metadata.get(DECK_FIELD)

    def _save_parent(self, deck_id: str, parent: str) -> None:
        deck = self.service.read_deck(deck_id)
        metadata = {**deck.metadata, DECK_FIELD: parent}
        self.service.save_deck(
            deck_id, SaveDeckRequest(title=deck.title, body=deck.body, metadata=metadata, base_revision=deck.revision)
        )


class DeckCrudTests(_DeckTestCase):
    def test_round_trip_over_the_wire(self) -> None:
        created = self.client.post("/api/plot/decks", json={"title": "Heist"})
        self.assertEqual(created.status_code, 200, created.text)
        deck = created.json()
        self.assertEqual(deck["entry_type"], "plot:deck")
        saved = self.client.put(
            f"/api/plot/decks/{deck['id']}",
            json={"title": "The Heist", "body": "Plan and execution.", "base_revision": deck["revision"]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        fetched = self.client.get(f"/api/plot/decks/{deck['id']}").json()
        self.assertEqual((fetched["title"], fetched["body"].strip()), ("The Heist", "Plan and execution."))
        listed = self.client.get("/api/plot/decks").json()["entries"]
        self.assertEqual([d["id"] for d in listed], [deck["id"]])
        deleted = self.client.delete(f"/api/plot/decks/{deck['id']}")
        self.assertEqual((deleted.status_code, deleted.json()["entries"]), (200, []))
        self.assertEqual(self.client.get(f"/api/plot/decks/{deck['id']}").status_code, 404)

    def test_create_inside_a_parent_is_one_write(self) -> None:
        parent = self._deck("Parent")
        child = self.service.create_deck(CreateDeckRequest(title="Child", plot_deck=parent))
        self.assertEqual(child.metadata.get(DECK_FIELD), parent)

    def test_create_inside_something_that_is_not_a_deck_is_a_422(self) -> None:
        card = self._card("A card")
        for parent in (card, "plot_nothere0000"):
            with self.subTest(parent=parent), self.assertRaises(ProjectServiceError) as ctx:
                self.service.create_deck(CreateDeckRequest(title="Child", plot_deck=parent))
            self.assertEqual(ctx.exception.status_code, 422)

    def test_a_deck_endpoint_does_not_touch_a_card(self) -> None:
        card = self._card("A card")
        self.assertEqual(self.client.get(f"/api/plot/decks/{card}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/plot/decks/{card}").status_code, 404)
        self.assertEqual(self.service.read_card(card).id, card)

    def test_a_deck_cannot_sit_inside_itself(self) -> None:
        deck = self._deck("A")
        with self.assertRaises(ProjectServiceError) as ctx:
            self._save_parent(deck, deck)
        self.assertEqual((ctx.exception.status_code, str(ctx.exception)), (422, "A deck cannot sit inside itself."))

    def test_a_deck_cannot_sit_inside_its_descendant(self) -> None:
        a = self._deck("A")
        b = self._deck("B", a)
        c = self._deck("C", b)
        with self.assertRaises(ProjectServiceError) as ctx:
            self._save_parent(a, c)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIsNone(self.service.read_deck(a).metadata.get(DECK_FIELD))
        # A legal re-parent still works.
        self._save_parent(c, a)
        self.assertEqual(self.service.read_deck(c).metadata.get(DECK_FIELD), a)

    def test_the_cycle_refusal_reaches_the_wire(self) -> None:
        a = self._deck("A")
        deck = self.service.read_deck(a)
        response = self.client.put(
            f"/api/plot/decks/{a}",
            json={"title": "A", "metadata": {DECK_FIELD: a}, "base_revision": deck.revision},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_deleting_a_deck_deletes_only_the_deck(self) -> None:
        parent = self._deck("Parent")
        child = self._deck("Child", parent)
        card = self._card("In parent", PlaceTo(deck=parent))
        self.assertEqual(self._home(card), parent)
        self.service.delete_deck(parent)
        # The card and the child deck survive, freed of the reference.
        self.assertFalse(self._home(card))  # the purge blanks the reference
        self.assertFalse(self.service.read_deck(child).metadata.get(DECK_FIELD))
        self.assertEqual([d.id for d in self.service.list_decks().entries], [child])
        self.assertEqual(self.service.read_card(card).title, "In parent")

    def test_read_node_dispatches_a_deck(self) -> None:
        deck = self._deck("A deck")
        self.assertEqual(self.service.read_node(deck).id, deck)


class PlaceToTests(_DeckTestCase):
    def test_to_a_deck_then_loose(self) -> None:
        deck = self._deck("Deck")
        card = self._card("Card")
        placed = self.service.place_card(card, PlaceCardRequest(to=PlaceTo(deck=deck)))
        self.assertEqual(placed.metadata.get(DECK_FIELD), deck)
        loose = self.service.place_card(card, PlaceCardRequest(to=PlaceTo(loose=True)))
        self.assertNotIn(DECK_FIELD, loose.metadata)

    def test_to_alone_keeps_the_story_rank(self) -> None:
        deck = self._deck("Deck")
        a, b = self._card("A"), self._card("B")
        before = self.service.read_card(a).story_rank
        self.service.place_card(a, PlaceCardRequest(to=PlaceTo(deck=deck)))
        self.assertEqual(self.service.read_card(a).story_rank, before)
        self.assertEqual(self._story_order(), [a, b])

    def test_to_and_story_together(self) -> None:
        deck = self._deck("Deck")
        a, b, c = self._card("A"), self._card("B"), self._card("C")
        placed = self.service.place_card(
            a, PlaceCardRequest(to=PlaceTo(deck=deck), story=StoryPlacement(after_id=c))
        )
        self.assertEqual(placed.metadata.get(DECK_FIELD), deck)
        self.assertEqual(self._story_order(), [b, c, a])

    def test_a_written_card_refuses_any_to(self) -> None:
        deck = self._deck("Deck")
        scene = self.service.create_scene(CreateSceneRequest(title="Scene")).id
        card = self._card("Card")
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        for to in (PlaceTo(deck=deck), PlaceTo(loose=True)):
            with self.subTest(to=to), self.assertRaises(ProjectServiceError) as ctx:
                self.service.place_card(card, PlaceCardRequest(to=to))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("shows by its scene", str(ctx.exception))
        # Story time alone is still allowed.
        other = self._card("Other")
        self.service.place_card(card, PlaceCardRequest(story=StoryPlacement(after_id=other)))

    def test_an_unknown_deck_or_a_non_deck_is_a_422(self) -> None:
        card, other = self._card("Card"), self._card("Other")
        for target in ("plot_nothere0000", other):
            with self.subTest(target=target), self.assertRaises(ProjectServiceError) as ctx:
                self.service.place_card(card, PlaceCardRequest(to=PlaceTo(deck=target)))
            self.assertEqual(ctx.exception.status_code, 422)
        self.assertIsNone(self._home(card))

    def test_a_bad_story_anchor_leaves_the_membership_unwritten(self) -> None:
        deck = self._deck("Deck")
        card = self._card("Card")
        with self.assertRaises(ProjectServiceError):
            self.service.place_card(
                card, PlaceCardRequest(to=PlaceTo(deck=deck), story=StoryPlacement(after_id="plot_nothere0000"))
            )
        self.assertIsNone(self._home(card))

    def test_the_request_needs_to_or_story_and_exactly_one_place(self) -> None:
        with self.assertRaises(ValidationError):
            PlaceCardRequest()
        with self.assertRaises(ValidationError):
            PlaceTo()
        with self.assertRaises(ValidationError):
            PlaceTo(deck="x", loose=True)
        card = self._card("Card")
        response = self.client.post(f"/api/plot/cards/{card}/place", json={})
        self.assertEqual(response.status_code, 422, response.text)

    def test_the_route_places_to_a_deck(self) -> None:
        deck, card = self._deck("Deck"), self._card("Card")
        response = self.client.post(f"/api/plot/cards/{card}/place", json={"to": {"deck": deck}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["metadata"][DECK_FIELD], deck)
        response = self.client.post(f"/api/plot/cards/{card}/place", json={"to": {"loose": True}})
        self.assertNotIn(DECK_FIELD, response.json()["metadata"])


class CreateInAPlaceTests(_DeckTestCase):
    def test_a_card_created_in_a_deck_lands_after_the_decks_last_card(self) -> None:
        d1, d2 = self._deck("D1"), self._deck("D2")
        a = self._card("A", PlaceTo(deck=d1))
        b = self._card("B", PlaceTo(deck=d2))
        c = self._card("C", PlaceTo(deck=d1))
        loose = self._card("Loose")
        new = self._card("New", PlaceTo(deck=d1))
        self.assertEqual(self._story_order(), [a, c, new, b, loose])
        self.assertEqual(self._home(new), d1)

    def test_an_empty_deck_or_loose_lands_at_the_end(self) -> None:
        deck = self._deck("Deck")
        a = self._card("A")
        in_empty = self._card("In empty", PlaceTo(deck=deck))
        loose = self._card("Loose", PlaceTo(loose=True))
        self.assertEqual(self._story_order(), [a, in_empty, loose])
        self.assertEqual(self._home(in_empty), deck)
        self.assertIsNone(self._home(loose))

    def test_sub_decks_cards_do_not_count(self) -> None:
        parent = self._deck("Parent")
        child = self._deck("Child", parent)
        a = self._card("A", PlaceTo(deck=parent))
        in_child = self._card("In child", PlaceTo(deck=child))
        b = self._card("B", PlaceTo(deck=parent))
        self.assertEqual(self._story_order(), [a, b, in_child])

    def test_create_in_an_unknown_deck_is_a_422(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self._card("X", PlaceTo(deck="plot_nothere0000"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_an_undo_restore_keeps_its_rank(self) -> None:
        deck = self._deck("Deck")
        a = self._card("A", PlaceTo(deck=deck))
        b = self._card("B")
        restored = self.service.create_card(
            CreateCardRequest(title="R", id="plot_restore0001", story_rank=99, to=PlaceTo(deck=deck))
        )
        self.assertEqual(restored.story_rank, 99)
        self.assertEqual(self._story_order(), [a, b, restored.id])


class DeckProjectionTests(_DeckTestCase):
    def test_decks_order_parents_first_siblings_by_title_and_flag_movable(self) -> None:
        b = self._deck("b deck")
        a = self._deck("A deck")
        a_child = self._deck("Z child", a)
        a_first = self._deck("Y child", a)
        projection = self.service.read_plot_board_projection()
        self.assertEqual([d.id for d in projection.decks], [a, a_first, a_child, b])
        by_id = {d.id: d for d in projection.decks}
        self.assertEqual((by_id[a].parent, by_id[a_child].parent, by_id[b].parent), (None, a, None))
        self.assertTrue(all(d.movable for d in projection.decks))

    def test_a_deck_carries_its_synopsis(self) -> None:
        deck = self.service.create_deck(CreateDeckRequest(title="Deck"))
        self.service.save_deck(
            deck.id, SaveDeckRequest(title="Deck", body="What this is.", base_revision=deck.revision)
        )
        shown = self.service.read_plot_board_projection().decks[0]
        self.assertEqual(shown.synopsis.strip(), "What this is.")

    def test_a_card_projects_its_home_deck(self) -> None:
        deck = self._deck("Deck")
        homed, loose = self._card("Homed", PlaceTo(deck=deck)), self._card("Loose")
        cards = {c.id: c for c in self.service.read_plot_board_projection().cards}
        self.assertEqual((cards[homed].deck, cards[loose].deck), (deck, None))

    def test_a_dangling_deck_reference_is_top_level_and_a_cycle_is_never_dropped(self) -> None:
        a, b, c = self._deck("A"), self._deck("B"), self._deck("C")
        self._save_parent(b, a)
        # Hand-edit the files into a cycle (A in B in A) and a dangling parent (C).
        for deck_id, parent in ((a, b), (c, "plot_gone0000000")):
            entry = self.service.read_deck(deck_id)
            self.service._write_node_entry_file(
                self.service._path_for_node_id(deck_id, "plot"),
                deck_id,
                entry.title,
                entry.entry_type,
                {**entry.metadata, DECK_FIELD: parent},
                entry.body,
            )
        decks = {d.id: d for d in self.service.read_plot_board_projection().decks}
        self.assertEqual(set(decks), {a, b, c})
        self.assertEqual((decks[a].parent, decks[b].parent, decks[c].parent), (None, None, None))

    def test_every_container_is_projected_including_empty_ones(self) -> None:
        root = self.service.read_structure().root.id
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Empty act", entry_type="manuscript:container", parent_id=root)
        )
        containers = self.service.read_plot_board_projection().containers
        self.assertEqual([c.title for c in containers], ["Empty act"])
