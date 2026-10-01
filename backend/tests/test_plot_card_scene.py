"""A written card shows its scene (ADR-0097 §1, §3, §4; #2376, backend half).

While a card has a scene its displayed title and synopsis are the scene's; its own
text is frozen; `scene` is owned by attach / detach / realize, never a card save.
"""

from __future__ import annotations

from plot_fixtures import PlotTestCase

from app.models import (
    AttachCardRequest,
    CardTextRequest,
    CreateCardRequest,
    CreatePlotlineRequest,
    CreateSceneRequest,
    DetachCardRequest,
    RealizeCardRequest,
    ReplaceHitRef,
    ReplaceRequest,
    SaveCardRequest,
    SearchRequest,
)
from app.services.project.card_text import displayed_card_text
from app.services.project.errors import ProjectServiceError


class _CardSceneCase(PlotTestCase):
    def _scene(self, title: str = "Scene", summary: str = "") -> str:
        scene_id = self.service.create_scene(CreateSceneRequest(title=title)).id
        if summary:
            self.service._set_scene_summary(scene_id, summary)
        return scene_id

    def _card(self, title: str = "Card", body: str = "") -> str:
        card = self.service.create_card(CreateCardRequest(title=title))
        if body:
            self.service.save_card(card.id, SaveCardRequest(title=title, body=body, base_revision=card.revision))
        return card.id

    def _summary(self, scene_id: str) -> str:
        return str(self.service.read_scene(scene_id).metadata.get("summary") or "")

    def _projected(self, card_id: str):
        return next(c for c in self.service.read_plot_board_projection().cards if c.id == card_id)

    def _context_card(self, card_id: str):
        return next(c for c in self.service.read_plot_context().cards if c.id == card_id)

    def _card_bytes(self, card_id: str) -> bytes:
        return self.service._path_for_node_id(card_id, "plot").read_bytes()

    def _written(self, title: str = "Card", body: str = "Plan.", scene_title: str = "Scene", summary: str = "Plan.") -> tuple[str, str]:
        """A card attached to a scene whose summary already equals its body."""
        scene = self._scene(scene_title, summary)
        card = self._card(title, body)
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        return card, scene


class DisplayedTextTests(_CardSceneCase):
    def test_the_pure_reader(self) -> None:
        text = {"s": ("Scene title", "Scene summary")}
        self.assertEqual(displayed_card_text("T", "B", "s", text), ("Scene title", "Scene summary"))
        self.assertEqual(displayed_card_text("T", "B", None, text), ("T", "B"))
        self.assertEqual(displayed_card_text("T", "B", "gone", text), ("T", "B"))
        self.assertEqual(displayed_card_text("T", "B", "s", {"s": ("S", "")}), ("S", ""))

    def test_the_projection_shows_the_scenes_text_for_a_written_card(self) -> None:
        card, scene = self._written("Card title", "Card plan.", "Scene title", "Card plan.")
        self.service._set_scene_summary(scene, "Fresh summary.")
        shown = self._projected(card)
        self.assertEqual((shown.title, shown.synopsis), ("Scene title", "Fresh summary."))
        # The card node keeps its own text.
        own = self.service.read_card(card)
        self.assertEqual((own.title, own.body.strip()), ("Card title", "Card plan."))

    def test_the_projection_shows_the_cards_own_text_when_unwritten(self) -> None:
        card = self._card("Plan only", "Just a plan.")
        shown = self._projected(card)
        self.assertEqual((shown.title, shown.synopsis.strip()), ("Plan only", "Just a plan."))

    def test_an_empty_summary_shows_empty_not_the_card_body(self) -> None:
        card, scene = self._written("Card title", "Card plan.", "Scene title", "Card plan.")
        self.service._set_scene_summary(scene, "")
        self.assertEqual(self._projected(card).synopsis, "")
        self.assertEqual(self.service.read_card(card).body.strip(), "Card plan.")

    def test_the_plot_context_shows_the_scenes_text(self) -> None:
        card, scene = self._written("Card title", "Card plan.", "Scene title", "Card plan.")
        self.service._set_scene_summary(scene, "Fresh summary.")
        shown = self._context_card(card)
        self.assertEqual((shown.title, shown.synopsis), ("Scene title", "Fresh summary."))
        self.service._set_scene_summary(scene, "")
        self.assertEqual(self._context_card(card).synopsis, "")

    def test_the_plot_context_shows_the_cards_own_text_when_unwritten(self) -> None:
        card = self._card("Plan only", "Just a plan.")
        shown = self._context_card(card)
        self.assertEqual((shown.title, shown.synopsis.strip()), ("Plan only", "Just a plan."))


class SaveCardFrozenTests(_CardSceneCase):
    def _save(self, card_id: str, **changes):
        card = self.service.read_card(card_id)
        fields = {"title": card.title, "body": card.body, "metadata": card.metadata, "base_revision": card.revision}
        return self.service.save_card(card_id, SaveCardRequest(**{**fields, **changes}))

    def test_a_title_change_on_a_written_card_is_a_422(self) -> None:
        card, _ = self._written()
        with self.assertRaises(ProjectServiceError) as ctx:
            self._save(card, title="Renamed")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("edit its synopsis in the scene", ctx.exception.message)

    def test_a_body_change_on_a_written_card_is_a_422(self) -> None:
        card, _ = self._written()
        with self.assertRaises(ProjectServiceError) as ctx:
            self._save(card, body="Something else.")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_a_422_reaches_the_wire(self) -> None:
        card, _ = self._written()
        response = self.client.put(f"/api/plot/cards/{card}", json={"title": "Renamed", "body": "Plan.", "metadata": {}})
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_plotline_change_with_unchanged_text_is_accepted(self) -> None:
        card, scene = self._written()
        plotline = self.service.create_plotline(CreatePlotlineRequest(title="Romance"))
        current = self.service.read_card(card)
        saved = self._save(card, metadata={**current.metadata, "plotline": plotline.id}, body=current.body + "\n")
        self.assertEqual(saved.metadata["plotline"], plotline.id)
        self.assertEqual(saved.metadata["scene"], scene)

    def test_the_clients_scene_is_ignored_both_ways(self) -> None:
        other = self._scene("Other")
        free = self._card("Free")
        saved = self.service.save_card(free, SaveCardRequest(title="Free", metadata={"scene": other}))
        self.assertFalse(saved.metadata.get("scene"))  # attach-via-save is a no-op
        card, scene = self._written()
        current = self.service.read_card(card)
        saved = self.service.save_card(
            card, SaveCardRequest(title=current.title, body=current.body, metadata={}, base_revision=current.revision)
        )
        self.assertEqual(saved.metadata["scene"], scene)  # clear-via-save is a no-op

    def test_an_unwritten_card_still_saves_its_text(self) -> None:
        card = self._card("Plan", "Body.")
        saved = self._save(card, title="Plan 2", body="Body 2.")
        self.assertEqual((saved.title, saved.body.strip()), ("Plan 2", "Body 2."))


class AttachTests(_CardSceneCase):
    def test_an_empty_summary_is_seeded_from_the_card_body(self) -> None:
        scene = self._scene("Scene")
        card = self._card("Card", "The plan.")
        attached = self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        self.assertEqual(attached.metadata["scene"], scene)
        self.assertEqual(self._summary(scene), "The plan.")
        self.assertEqual(attached.body.strip(), "The plan.")

    def test_an_empty_summary_and_empty_body_changes_nothing(self) -> None:
        scene = self._scene("Scene")
        card = self._card("Card")
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        self.assertEqual(self._summary(scene), "")

    def test_equal_texts_need_no_choice(self) -> None:
        scene = self._scene("Scene", "Same.")
        card = self._card("Card", "Same.\n")
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        self.assertEqual(self._summary(scene), "Same.")

    def test_differing_texts_409_with_both_texts(self) -> None:
        scene = self._scene("Scene", "From the scene.")
        card = self._card("Card", "From the card.")
        response = self.client.post(f"/api/plot/cards/{card}/attach", json={"scene_id": scene})
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "text_choice_required")
        self.assertEqual(detail["scene_summary"], "From the scene.")
        self.assertEqual(detail["card_synopsis"], "From the card.")
        self.assertIn("message", detail)
        self.assertFalse(self.service.read_card(card).metadata.get("scene"))  # nothing written

    def test_choosing_the_scene_keeps_its_summary(self) -> None:
        scene = self._scene("Scene", "From the scene.")
        card = self._card("Card", "From the card.")
        attached = self.service.attach_card(card, AttachCardRequest(scene_id=scene, text="scene"))
        self.assertEqual(attached.metadata["scene"], scene)
        self.assertEqual(self._summary(scene), "From the scene.")

    def test_choosing_the_card_overwrites_the_summary(self) -> None:
        scene = self._scene("Scene", "From the scene.")
        card = self._card("Card", "From the card.")
        self.service.attach_card(card, AttachCardRequest(scene_id=scene, text="card"))
        self.assertEqual(self._summary(scene), "From the card.")

    def test_a_held_scene_is_a_409(self) -> None:
        card, scene = self._written()
        other = self._card("Other")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.attach_card(other, AttachCardRequest(scene_id=scene))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_a_written_card_cannot_attach_again(self) -> None:
        card, _ = self._written()
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.attach_card(card, AttachCardRequest(scene_id=self._scene("Two")))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("detach it first", ctx.exception.message)

    def test_an_unknown_or_non_scene_id_is_a_422(self) -> None:
        card = self._card("Card")
        container = self.service.read_structure().root.id
        for bad in ("manuscript_nope", container):
            with self.assertRaises(ProjectServiceError) as ctx:
                self.service.attach_card(card, AttachCardRequest(scene_id=bad))
            self.assertEqual(ctx.exception.status_code, 422, bad)


class DetachTests(_CardSceneCase):
    def test_an_equal_body_takes_the_summary_and_the_title_comes_back(self) -> None:
        card, scene = self._written("Card title", "Plan.", "Scene title", "Plan.")
        detached = self.service.detach_card(card, DetachCardRequest())
        self.assertFalse(detached.metadata.get("scene"))
        self.assertNotIn("page_status", detached.metadata)
        self.assertEqual((detached.title, detached.body.strip()), ("Scene title", "Plan."))
        self.assertEqual(self._summary(scene), "Plan.")  # the scene file is untouched

    def test_an_empty_body_takes_the_summary(self) -> None:
        scene = self._scene("Scene title", "Summary.")
        card = self._card("Card title")
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        detached = self.service.detach_card(card, DetachCardRequest())
        self.assertEqual((detached.title, detached.body.strip()), ("Scene title", "Summary."))

    def test_differing_texts_409_then_each_choice(self) -> None:
        scene = self._scene("Scene title", "Plan.")
        card = self._card("Card title", "Plan.")
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        self.service._set_scene_summary(scene, "Rewritten in the scene.")
        response = self.client.post(f"/api/plot/cards/{card}/detach", json={})
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "text_choice_required")
        self.assertEqual(detail["scene_summary"], "Rewritten in the scene.")
        self.assertEqual(detail["card_synopsis"], "Plan.")
        self.assertTrue(self.service.read_card(card).metadata.get("scene"))  # nothing written
        kept = self.service.detach_card(card, DetachCardRequest(text="card"))
        self.assertEqual((kept.title, kept.body.strip()), ("Scene title", "Plan."))

    def test_choosing_the_scene_takes_the_summary(self) -> None:
        scene = self._scene("Scene title", "Plan.")
        card = self._card("Card title", "Plan.")
        self.service.attach_card(card, AttachCardRequest(scene_id=scene))
        self.service._set_scene_summary(scene, "Rewritten in the scene.")
        taken = self.service.detach_card(card, DetachCardRequest(text="scene"))
        self.assertEqual(taken.body.strip(), "Rewritten in the scene.")

    def test_an_unwritten_card_409s(self) -> None:
        card = self._card("Card", "Plan.")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.detach_card(card, DetachCardRequest())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("no scene", ctx.exception.message)


class CardTextEndpointTests(_CardSceneCase):
    def test_a_written_card_edits_the_scene_and_leaves_the_card_file_alone(self) -> None:
        card, scene = self._written("Card title", "Plan.", "Scene title", "Plan.")
        before = self._card_bytes(card)
        shown = self.client.put(
            f"/api/plot/cards/{card}/text", json={"title": "Scene renamed", "synopsis": "New summary."}
        )
        self.assertEqual(shown.status_code, 200, shown.text)
        self.assertEqual(self.service.read_scene(scene).title, "Scene renamed")
        self.assertEqual(self._summary(scene), "New summary.")
        self.assertEqual(self._card_bytes(card), before)
        projected = self._projected(card)
        self.assertEqual((projected.title, projected.synopsis), ("Scene renamed", "New summary."))

    def test_an_absent_field_is_left_alone(self) -> None:
        card, scene = self._written("Card title", "Plan.", "Scene title", "Plan.")
        self.service.set_card_text(card, CardTextRequest(synopsis="Only this."))
        self.assertEqual(self.service.read_scene(scene).title, "Scene title")
        self.assertEqual(self._summary(scene), "Only this.")

    def test_an_unwritten_card_edits_itself(self) -> None:
        card = self._card("Plan", "Body.")
        result = self.service.set_card_text(card, CardTextRequest(title="Plan 2", synopsis="Body 2."))
        self.assertEqual((result.title, result.body.strip()), ("Plan 2", "Body 2."))

    def test_an_empty_title_is_a_422(self) -> None:
        card = self._card("Plan")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.set_card_text(card, CardTextRequest(title="  "))
        self.assertEqual(ctx.exception.status_code, 422)


class RealizeSeedsTheSummaryTests(_CardSceneCase):
    def test_realize_makes_the_card_body_the_scene_summary(self) -> None:
        card = self._card("Plan", "She leaves.")
        realized = self.service.realize_card(card, RealizeCardRequest())
        scene = realized.metadata["scene"]
        self.assertEqual(self._summary(scene), "She leaves.")
        shown = self._projected(card)
        self.assertEqual(shown.synopsis.strip(), "She leaves.")

    def test_realize_of_a_bodiless_card_leaves_the_summary_empty(self) -> None:
        card = self._card("Plan")
        scene = self.service.realize_card(card, RealizeCardRequest()).metadata["scene"]
        self.assertEqual(self._summary(scene), "")


class ReplaceSkipsAWrittenCardTests(_CardSceneCase):
    def _hit(self, card_id: str, text: str) -> ReplaceHitRef:
        hits = self.service.search(SearchRequest(query=text)).hits
        hit = next(h for h in hits if h.file_id == card_id and h.field == "body")
        return ReplaceHitRef(
            file_id=hit.file_id, field=hit.field, start=hit.start, end=hit.end, text=hit.text, revision=hit.revision
        )

    def test_a_written_cards_body_is_not_replaced(self) -> None:
        card, _ = self._written("Card", "The lantern burns.", "Scene", "The lantern burns.")
        before = self._card_bytes(card)
        response = self.service.replace(ReplaceRequest(hits=[self._hit(card, "lantern")], replacement="candle"))
        self.assertEqual(response.replaced_nodes, 0)
        self.assertEqual([(o.status, o.reason) for o in response.outcomes], [("not_replaceable", "written")])
        self.assertEqual(self._card_bytes(card), before)

    def test_an_unwritten_cards_body_is_still_replaced(self) -> None:
        card = self._card("Card", "The lantern burns.")
        response = self.service.replace(ReplaceRequest(hits=[self._hit(card, "lantern")], replacement="candle"))
        self.assertEqual(response.replaced_nodes, 1)
        self.assertEqual(self.service.read_card(card).body.strip(), "The candle burns.")
