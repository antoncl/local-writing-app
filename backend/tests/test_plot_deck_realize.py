"""A deck realized into a manuscript container (ADR-0097 §3, §7; #2380, backend half):
realize / attach / detach, the container's text standing in for the deck's, and the
board projection's `realized_container` / `realize_level_name`."""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    AttachCardRequest,
    AttachDeckRequest,
    CreateCardRequest,
    CreateDeckRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    DeckTextRequest,
    DetachDeckRequest,
    PlaceCardRequest,
    PlaceTo,
    SaveDeckRequest,
)
from app.services.project.decks import DECK_FIELD, PLANNED_IN_FIELD, REALIZED_FIELD
from app.services.project.errors import ProjectServiceError


class _RealizeCase(PlotTestCase):
    def _deck(self, title: str = "Heist", body: str = "", parent: str = "") -> str:
        deck = self.service.create_deck(CreateDeckRequest(title=title, plot_deck=parent))
        if body:
            self.service.save_deck(
                deck.id, SaveDeckRequest(title=title, body=body, metadata=deck.metadata, base_revision=deck.revision)
            )
        return deck.id

    def _card(self, title: str, deck: str | None = None) -> str:
        return self.service.create_card(CreateCardRequest(title=title, to=PlaceTo(deck=deck) if deck else None)).id

    def _container(self, title: str = "Act One", summary: str = "") -> str:
        before = self._container_ids()
        self.service.create_structure_node(CreateStructureNodeRequest(title=title, entry_type="manuscript:container"))
        container_id = next(c for c in self._container_ids() if c not in before)
        if summary:
            self.service._set_scene_summary(container_id, summary)
        return container_id

    def _container_ids(self) -> list[str]:
        return [c.id for c in self.service.read_plot_board_projection().containers]

    def _summary(self, container_id: str) -> str:
        return str(self.service.read_scene(container_id).metadata.get("summary") or "")

    def _projected(self, deck_id: str):
        return next(d for d in self.service.read_plot_board_projection().decks if d.id == deck_id)

    def _realized(self, deck_id: str) -> object:
        return self.service.read_deck(deck_id).metadata.get(REALIZED_FIELD)

    def _status(self, call, *args) -> ProjectServiceError:
        with self.assertRaises(ProjectServiceError) as raised:
            call(*args)
        return raised.exception


class RealizeTests(_RealizeCase):
    def test_realizes_at_the_top_with_the_decks_text(self) -> None:
        deck = self._deck("Heist", "The crew robs the bank.")
        result = self.service.realize_deck(deck)
        container = result.container_id
        self.assertEqual(self._realized(deck), container)
        self.assertEqual(result.deck.metadata.get(REALIZED_FIELD), container)
        node = next(c for c in self.service.read_plot_board_projection().containers if c.id == container)
        self.assertEqual((node.title, node.parent, node.level_name), ("Heist", None, "Act"))
        self.assertEqual(self._summary(container), "The crew robs the bank.")

    def test_an_empty_body_leaves_the_summary_empty(self) -> None:
        result = self.service.realize_deck(self._deck("Heist"))
        self.assertEqual(self._summary(result.container_id), "")

    def test_realizes_under_a_realized_parent(self) -> None:
        parent = self._deck("Act deck")
        child = self._deck("Chapter deck", parent=parent)
        top = self.service.realize_deck(parent).container_id
        nested = self.service.realize_deck(child).container_id
        by_id = {c.id: c for c in self.service.read_plot_board_projection().containers}
        self.assertEqual((by_id[nested].parent, by_id[nested].level_name), (top, "Chapter"))

    def test_an_unrealized_parent_means_the_top_level(self) -> None:
        parent = self._deck("Act deck")
        child = self._deck("Chapter deck", parent=parent)
        nested = self.service.realize_deck(child).container_id
        by_id = {c.id: c for c in self.service.read_plot_board_projection().containers}
        self.assertEqual((by_id[nested].parent, by_id[nested].level_name), (None, "Act"))

    def test_plans_own_unwritten_unplanned_cards_in_story_order(self) -> None:
        deck = self._deck("Heist")
        first, second = self._card("First", deck), self._card("Second", deck)
        # Move the second ahead in story time: the plan follows story order.
        self.service.place_card(
            second, PlaceCardRequest(story={"before_id": first})  # type: ignore[arg-type]
        )
        result = self.service.realize_deck(deck)
        self.assertEqual(result.planned, [second, first])
        for card in (first, second):
            metadata = self.service.read_card(card).metadata
            self.assertEqual(metadata.get(PLANNED_IN_FIELD), result.container_id)
            self.assertFalse(metadata.get("planned_after"))
            self.assertEqual(metadata.get(DECK_FIELD), deck)

    def test_leaves_planned_written_and_other_cards_alone(self) -> None:
        deck = self._deck("Heist")
        chapter = self._container("Existing")
        planned = self._card("Planned", deck)
        self.service.place_card(planned, PlaceCardRequest(to=PlaceTo(planned_in=chapter)))
        written = self._card("Written", deck)
        scene = self.service.create_scene(CreateSceneRequest(title="Scene")).id
        self.service.attach_card(written, AttachCardRequest(scene_id=scene))
        elsewhere = self._card("Other deck", self._deck("Other"))
        loose = self._card("Loose")
        child_deck = self._deck("Child", parent=deck)
        result = self.service.realize_deck(deck)
        self.assertEqual(result.planned, [])
        self.assertEqual(self.service.read_card(planned).metadata.get(PLANNED_IN_FIELD), chapter)
        self.assertFalse(self.service.read_card(written).metadata.get(PLANNED_IN_FIELD))
        self.assertFalse(self.service.read_card(elsewhere).metadata.get(PLANNED_IN_FIELD))
        self.assertFalse(self.service.read_card(loose).metadata.get(PLANNED_IN_FIELD))
        self.assertFalse(self._realized(child_deck))
        self.assertEqual(self.service.read_deck(child_deck).metadata.get(DECK_FIELD), deck)

    def test_twice_is_409(self) -> None:
        deck = self._deck()
        self.service.realize_deck(deck)
        self.assertEqual(self._status(self.service.realize_deck, deck).status_code, 409)

    def test_refuses_a_level_the_list_does_not_have(self) -> None:
        act, chapter, deeper = self._deck("A"), self._deck("B"), self._deck("C")
        self.service.save_deck(chapter, self._parented(chapter, act))
        self.service.save_deck(deeper, self._parented(deeper, chapter))
        self.service.realize_deck(act)
        self.service.realize_deck(chapter)
        self.assertIsNone(self._projected(deeper).realize_level_name)
        refused = self._status(self.service.realize_deck, deeper)
        self.assertEqual(refused.status_code, 422)
        self.assertFalse(self._realized(deeper))

    def _parented(self, deck_id: str, parent: str) -> SaveDeckRequest:
        deck = self.service.read_deck(deck_id)
        return SaveDeckRequest(
            title=deck.title, body=deck.body, metadata={**deck.metadata, DECK_FIELD: parent}, base_revision=deck.revision
        )

    def test_over_the_wire(self) -> None:
        deck = self._deck("Heist", "Plan.")
        response = self.client.post(f"/api/plot/decks/{deck}/realize")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"deck", "container_id", "planned"})
        self.assertEqual(body["deck"]["metadata"][REALIZED_FIELD], body["container_id"])
        self.assertEqual(self.client.post(f"/api/plot/decks/{deck}/realize").status_code, 409)


class HeldContainerTests(_RealizeCase):
    def test_another_deck_holding_the_container_is_409_on_attach(self) -> None:
        holder, other = self._deck("Holder"), self._deck("Other")
        container = self.service.realize_deck(holder).container_id
        refused = self._status(self.service.attach_deck, other, AttachDeckRequest(container_id=container))
        self.assertEqual(refused.status_code, 409)
        self.assertFalse(self._realized(other))

    def test_attach_to_a_scene_or_unknown_node_is_422(self) -> None:
        deck = self._deck()
        scene = self.service.create_scene(CreateSceneRequest(title="Scene")).id
        for target in (scene, "nope"):
            refused = self._status(self.service.attach_deck, deck, AttachDeckRequest(container_id=target))
            self.assertEqual(refused.status_code, 422)


class DetachTests(_RealizeCase):
    def test_takes_the_containers_title_and_keeps_container_and_plans(self) -> None:
        deck = self._deck("Heist", "Plan.")
        card = self._card("Card", deck)
        container = self.service.realize_deck(deck).container_id
        self.service.set_deck_text(deck, DeckTextRequest(title="Renamed"))
        detached = self.service.detach_deck(deck, DetachDeckRequest())
        self.assertEqual(detached.title, "Renamed")
        self.assertFalse(detached.metadata.get(REALIZED_FIELD))
        self.assertIn(container, self._container_ids())
        self.assertEqual(self.service.read_card(card).metadata.get(PLANNED_IN_FIELD), container)

    def test_body_becomes_the_summary_when_the_deck_body_is_empty_or_equal(self) -> None:
        deck = self._deck("Heist")
        container = self.service.realize_deck(deck).container_id
        self.service._set_scene_summary(container, "Written in the manuscript.")
        self.assertEqual(self.service.detach_deck(deck, DetachDeckRequest()).body.strip(), "Written in the manuscript.")

    def test_an_empty_summary_keeps_the_decks_own_body(self) -> None:
        deck = self._deck("Heist", "Plan.")
        container = self.service.realize_deck(deck).container_id
        self.service._set_scene_summary(container, "")
        self.assertEqual(self.service.detach_deck(deck, DetachDeckRequest()).body.strip(), "Plan.")

    def test_different_texts_need_a_choice(self) -> None:
        deck = self._deck("Heist", "Plan.")
        container = self.service.realize_deck(deck).container_id
        self.service._set_scene_summary(container, "Rewritten.")
        refused = self._status(self.service.detach_deck, deck, DetachDeckRequest())
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(
            refused.detail, {"code": "text_choice_required", "scene_summary": "Rewritten.", "card_synopsis": "Plan."}
        )
        self.assertEqual(self._realized(deck), container)
        kept = self.service.detach_deck(deck, DetachDeckRequest(text="card"))
        self.assertEqual(kept.body.strip(), "Plan.")

    def test_choosing_the_containers_summary(self) -> None:
        deck = self._deck("Heist", "Plan.")
        container = self.service.realize_deck(deck).container_id
        self.service._set_scene_summary(container, "Rewritten.")
        taken = self.service.detach_deck(deck, DetachDeckRequest(text="scene"))
        self.assertEqual(taken.body.strip(), "Rewritten.")

    def test_not_realized_is_409(self) -> None:
        self.assertEqual(self._status(self.service.detach_deck, self._deck(), DetachDeckRequest()).status_code, 409)

    def test_over_the_wire(self) -> None:
        deck = self._deck("Heist")
        self.service.realize_deck(deck)
        response = self.client.post(f"/api/plot/decks/{deck}/detach", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["metadata"].get(REALIZED_FIELD))


class AttachTests(_RealizeCase):
    def test_relinks_and_seeds_an_empty_summary(self) -> None:
        container = self._container("Act One")
        deck = self._deck("Heist", "Plan.")
        attached = self.service.attach_deck(deck, AttachDeckRequest(container_id=container))
        self.assertEqual(attached.metadata.get(REALIZED_FIELD), container)
        self.assertEqual(self._summary(container), "Plan.")

    def test_is_the_undo_of_a_detach(self) -> None:
        deck = self._deck("Heist", "Plan.")
        container = self.service.realize_deck(deck).container_id
        self.service.detach_deck(deck, DetachDeckRequest())
        self.service.attach_deck(deck, AttachDeckRequest(container_id=container))
        self.assertEqual(self._realized(deck), container)

    def test_different_texts_need_a_choice(self) -> None:
        container = self._container("Act One", "Existing summary.")
        deck = self._deck("Heist", "Plan.")
        refused = self._status(self.service.attach_deck, deck, AttachDeckRequest(container_id=container))
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(
            refused.detail,
            {"code": "text_choice_required", "scene_summary": "Existing summary.", "card_synopsis": "Plan."},
        )
        self.service.attach_deck(deck, AttachDeckRequest(container_id=container, text="scene"))
        self.assertEqual(self._summary(container), "Existing summary.")

    def test_choosing_the_decks_synopsis_overwrites_the_summary(self) -> None:
        container = self._container("Act One", "Existing summary.")
        deck = self._deck("Heist", "Plan.")
        self.service.attach_deck(deck, AttachDeckRequest(container_id=container, text="card"))
        self.assertEqual(self._summary(container), "Plan.")

    def test_an_already_realized_deck_is_409(self) -> None:
        deck = self._deck()
        self.service.realize_deck(deck)
        refused = self._status(self.service.attach_deck, deck, AttachDeckRequest(container_id=self._container()))
        self.assertEqual(refused.status_code, 409)


class RealizedTextTests(_RealizeCase):
    def test_save_ignores_a_clients_realized_container(self) -> None:
        deck = self._deck("Heist")
        container = self._container("Elsewhere")
        current = self.service.read_deck(deck)
        saved = self.service.save_deck(
            deck,
            SaveDeckRequest(
                title="Heist", body="", metadata={REALIZED_FIELD: container}, base_revision=current.revision
            ),
        )
        self.assertFalse(saved.metadata.get(REALIZED_FIELD))

    def test_save_keeps_the_on_disk_container(self) -> None:
        deck = self._deck("Heist")
        container = self.service.realize_deck(deck).container_id
        current = self.service.read_deck(deck)
        saved = self.service.save_deck(
            deck, SaveDeckRequest(title="Heist", body=current.body, metadata={}, base_revision=current.revision)
        )
        self.assertEqual(saved.metadata.get(REALIZED_FIELD), container)

    def test_save_refuses_a_text_change_on_a_realized_deck(self) -> None:
        deck = self._deck("Heist", "Plan.")
        self.service.realize_deck(deck)
        current = self.service.read_deck(deck)
        for title, body in (("Changed", current.body), (current.title, "Changed.")):
            refused = self._status(
                self.service.save_deck,
                deck,
                SaveDeckRequest(title=title, body=body, metadata=current.metadata, base_revision=current.revision),
            )
            self.assertEqual(refused.status_code, 422)
            self.assertIn("realized as a Act", refused.message)

    def test_text_endpoint_writes_the_container_when_realized(self) -> None:
        deck = self._deck("Heist", "Plan.")
        container = self.service.realize_deck(deck).container_id
        own = self.service.read_deck(deck)
        self.service.set_deck_text(deck, DeckTextRequest(title="New title", synopsis="New summary."))
        self.assertEqual(self.service.read_scene(container).title, "New title")
        self.assertEqual(self._summary(container), "New summary.")
        after = self.service.read_deck(deck)
        self.assertEqual((after.title, after.body), (own.title, own.body))
        shown = self._projected(deck)
        self.assertEqual((shown.title, shown.synopsis), ("New title", "New summary."))

    def test_text_endpoint_writes_the_deck_when_unrealized(self) -> None:
        deck = self._deck("Heist", "Plan.")
        shown = self.service.set_deck_text(deck, DeckTextRequest(title="New title", synopsis="New plan."))
        self.assertEqual((shown.title, shown.body.strip()), ("New title", "New plan."))
        self.assertEqual(self._status(self.service.set_deck_text, deck, DeckTextRequest(title=" ")).status_code, 422)

    def test_text_over_the_wire(self) -> None:
        deck = self._deck("Heist")
        response = self.client.put(f"/api/plot/decks/{deck}/text", json={"title": "Wire"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], "Wire")


class DeleteAndProjectionTests(_RealizeCase):
    def test_deleting_a_realized_deck_keeps_the_container(self) -> None:
        deck = self._deck("Heist")
        container = self.service.realize_deck(deck).container_id
        self.service.delete_deck(deck)
        self.assertIn(container, self._container_ids())

    def test_projection_fields(self) -> None:
        deck = self._deck("Heist", "Plan.")
        child = self._deck("Chapter deck", parent=deck)
        before = self._projected(deck)
        self.assertEqual((before.realized_container, before.realize_level_name), (None, "Act"))
        self.assertEqual(self._projected(child).realize_level_name, "Act")
        container = self.service.realize_deck(deck).container_id
        shown = self._projected(deck)
        self.assertEqual((shown.realized_container, shown.title, shown.synopsis), (container, "Heist", "Plan."))
        self.assertEqual(self._projected(child).parent, deck)
        self.assertEqual(self._projected(child).realize_level_name, "Chapter")

    def test_a_deleted_container_heals_the_projection(self) -> None:
        deck = self._deck("Heist", "Plan.")
        container = self.service.realize_deck(deck).container_id
        self.service.delete_structure_node(container)
        shown = self._projected(deck)
        self.assertIsNone(shown.realized_container)
        self.assertEqual((shown.title, shown.synopsis.strip()), ("Heist", "Plan."))
