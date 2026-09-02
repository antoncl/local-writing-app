"""Backend tests for the `plot` kind (ADR-0048 S4a + S4b + S5a + S7 Slice 2; ADR-0053).

Node types under the kind: plotlines (`plot:plotline`, a flat layered entry that IS
a plot-template instance — beats + colour + lineage), cards (`plot:card`), the board
(`plot:board`, a per-project layout singleton), and templates (`plot:template`, S4b —
the ADR-0049 Library's second tenant). These prove the wiring end-to-end through
FastAPI plus the registration facts (family, schema, folder, whitelist, Library
membership) and the design invariants — a plotline is indexed and reference-bearing,
the board is a directly-addressed singleton kept out of the node index, templates ship
read-only from the Library and clone into the project on demand, and instantiating a
template snapshots its beats into an editable, book-local plotline whose lineage
survives the source template being deleted (`test_plot_beats.py`).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain
from plot_fixtures import PlotTestCase
from project_fixtures import open_test_project

from app.models import (
    CreateCardRequest,
    CreatePlotlineRequest,
    CreatePlotTemplateRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    EntryTypeDefinition,
    PlotTemplateSpec,
    RealizeCardRequest,
    SaveCardRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
    UpsertMetadataEntryTypeRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.references import (
    LIBRARY_LAYER_FAMILIES,
    NODE_FAMILIES,
    REFERENCE_BEARING_KINDS,
)
from app.services.project_service import ProjectService
from app.services.tree_structure import TreeStructureService


class PlotlineHttpTests(PlotTestCase):
    def _create(self, title: str = "A Subplot") -> dict:
        response = self.client.post("/api/plot/plotlines", json={"title": title})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_read_list_round_trip(self) -> None:
        created = self._create("The Sister's Arc")
        self.assertTrue(created["id"].startswith("plot_"))
        self.assertEqual(created["entry_type"], "plot:plotline")

        got = self.client.get(f"/api/plot/plotlines/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["title"], "The Sister's Arc")

        listing = self.client.get("/api/plot/plotlines")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn(created["id"], [e["id"] for e in listing.json()["entries"]])

    def test_save_round_trips_title_body_and_color(self) -> None:
        created = self._create()
        saved = self.client.put(
            f"/api/plot/plotlines/{created['id']}",
            json={"title": "Renamed", "body": "A quiet redemption.", "metadata": {"color": "rose"}},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        got = self.client.get(f"/api/plot/plotlines/{created['id']}").json()
        self.assertEqual(got["title"], "Renamed")
        # Bodies are stored `rstrip() + "\n"`, the same convention as lore/scene.
        self.assertEqual(got["body"], "A quiet redemption.\n")
        self.assertEqual(got["metadata"]["color"], "rose")

    def test_stale_base_revision_conflicts(self) -> None:
        created = self._create()
        conflict = self.client.put(
            f"/api/plot/plotlines/{created['id']}",
            json={"title": "X", "body": "", "base_revision": "stale"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_delete_removes_from_list_and_404s(self) -> None:
        created = self._create()
        deleted = self.client.delete(f"/api/plot/plotlines/{created['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertNotIn(created["id"], [e["id"] for e in deleted.json()["entries"]])
        self.assertEqual(self.client.get(f"/api/plot/plotlines/{created['id']}").status_code, 404)

    def test_missing_plotline_404s(self) -> None:
        self.assertEqual(self.client.get("/api/plot/plotlines/plot_nope").status_code, 404)

    def test_create_rejects_plot_board_entry_type(self) -> None:
        # plot:board is a singleton at plot-board.md — it must never be written
        # into the plot/ folder via the plotline path (where it would be indexed).
        response = self.client.post("/api/plot/plotlines", json={"title": "X", "entry_type": "plot:board"})
        self.assertEqual(response.status_code, 422, response.text)

    def test_save_rejects_plot_board_entry_type(self) -> None:
        created = self._create()
        response = self.client.put(
            f"/api/plot/plotlines/{created['id']}",
            json={"title": "X", "body": "", "entry_type": "plot:board"},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_create_with_supplied_id_restores_that_id(self) -> None:
        # Undo-of-delete / redo-of-create (ADR-0053 §7) recreates a plotline
        # under its original id so other cards' beat_links reconnect.
        response = self.client.post(
            "/api/plot/plotlines", json={"title": "Restored", "id": "plot_restored01"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], "plot_restored01")

    def test_create_with_colliding_id_409s(self) -> None:
        created = self._create()
        collision = self.client.post(
            "/api/plot/plotlines", json={"title": "Clash", "id": created["id"]}
        )
        self.assertEqual(collision.status_code, 409, collision.text)


class CardHttpTests(PlotTestCase):
    """Cards (ADR-0048 §1 / S5a) — the plotline's structural twin, so the CRUD
    surface mirrors it: create / read / list / save / delete, book-local, with the
    board singleton refused on the plot/ folder path."""

    def _create(self, title: str = "A Card") -> dict:
        response = self.client.post("/api/plot/cards", json={"title": title})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_read_list_round_trip(self) -> None:
        created = self._create("The Confession")
        self.assertTrue(created["id"].startswith("plot_"))
        self.assertEqual(created["entry_type"], "plot:card")

        got = self.client.get(f"/api/plot/cards/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["title"], "The Confession")

        listing = self.client.get("/api/plot/cards")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn(created["id"], [e["id"] for e in listing.json()["entries"]])

    def test_cards_and_plotlines_do_not_leak_into_each_others_lists(self) -> None:
        # Both are `plot`-kind nodes in the same plot/ folder; the lists filter on
        # exact entry_type, so a card never shows among plotlines and vice versa.
        card = self._create("A Card")
        plotline = self.client.post("/api/plot/plotlines", json={"title": "A Thread"}).json()
        card_ids = [e["id"] for e in self.client.get("/api/plot/cards").json()["entries"]]
        plotline_ids = [e["id"] for e in self.client.get("/api/plot/plotlines").json()["entries"]]
        self.assertIn(card["id"], card_ids)
        self.assertNotIn(plotline["id"], card_ids)
        self.assertIn(plotline["id"], plotline_ids)
        self.assertNotIn(card["id"], plotline_ids)

    def test_save_round_trips_title_synopsis_body_and_refs(self) -> None:
        plotline = self.client.post("/api/plot/plotlines", json={"title": "Sister arc"}).json()
        created = self._create()
        saved = self.client.put(
            f"/api/plot/cards/{created['id']}",
            json={
                "title": "Renamed",
                "body": "She admits the lie.",
                "metadata": {"plotline": plotline["id"]},
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        got = self.client.get(f"/api/plot/cards/{created['id']}").json()
        self.assertEqual(got["title"], "Renamed")
        # Synopsis is the body, stored `rstrip() + "\n"` like every prose node.
        self.assertEqual(got["body"], "She admits the lie.\n")
        self.assertEqual(got["metadata"]["plotline"], plotline["id"])

    def test_stale_base_revision_conflicts(self) -> None:
        created = self._create()
        conflict = self.client.put(
            f"/api/plot/cards/{created['id']}",
            json={"title": "X", "body": "", "base_revision": "stale"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_delete_removes_from_list_and_404s(self) -> None:
        created = self._create()
        deleted = self.client.delete(f"/api/plot/cards/{created['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertNotIn(created["id"], [e["id"] for e in deleted.json()["entries"]])
        self.assertEqual(self.client.get(f"/api/plot/cards/{created['id']}").status_code, 404)

    def test_missing_card_404s_with_the_card_noun(self) -> None:
        # The 404 names the card, not "Plotline" (the shared resolver's fixed
        # label the plot readers used to fall through to — S5a review).
        response = self.client.get("/api/plot/cards/plot_nope")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Card", response.json()["detail"])
        self.assertNotIn("Plotline", response.json()["detail"])

    def test_create_rejects_plot_board_entry_type(self) -> None:
        response = self.client.post("/api/plot/cards", json={"title": "X", "entry_type": "plot:board"})
        self.assertEqual(response.status_code, 422, response.text)

    def test_save_rejects_plot_board_entry_type(self) -> None:
        created = self._create()
        response = self.client.put(
            f"/api/plot/cards/{created['id']}",
            json={"title": "X", "body": "", "entry_type": "plot:board"},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_create_with_supplied_id_restores_that_id(self) -> None:
        # Undo-of-delete recreates a card under its original id so 0..n other
        # cards' causal_links pointing at it reconnect (ADR-0053 §7).
        response = self.client.post("/api/plot/cards", json={"title": "Back", "id": "plot_card_back1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], "plot_card_back1")

    def test_create_with_colliding_id_409s(self) -> None:
        created = self._create()
        collision = self.client.post("/api/plot/cards", json={"title": "Clash", "id": created["id"]})
        self.assertEqual(collision.status_code, 409, collision.text)


class CardReferenceTests(PlotTestCase):
    """Cards are ordinary nodes, so the reference graph works for free (ADR-0048
    §1): a card's `plotline` / `scene` references round-trip, and a deleted target
    visibly stops resolving — purged when the delete purges referrers (plotline),
    healed on read when it does not (scene)."""

    def _make_scene(self, title: str = "Arrival") -> str:
        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter", entry_type="manuscript:chapter", parent_id=structure.root.id)
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "manuscript:chapter")
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=chapter_id)).id

    def _raw_metadata_on_disk(self, node_id: str) -> dict:
        # Read the card's front matter straight from disk, bypassing read_card's
        # read-side healing — so a purge assertion proves the write-back happened,
        # not that the reader would have blanked a dangling ref anyway.
        path = self.service._path_for_node_id(node_id, "plot")
        front_matter = self.service._read_front_matter_only(path, strict=True)
        return front_matter.get("metadata") or {}

    def test_plotline_reference_is_purged_from_disk_when_the_plotline_is_deleted(self) -> None:
        plotline = self.service.create_plotline(CreatePlotlineRequest(title="Thread"))
        card = self.service.create_card(CreateCardRequest(title="Card"))
        self.service.save_card(card.id, SaveCardRequest(title="Card", metadata={"plotline": plotline.id}))
        self.assertEqual(self._raw_metadata_on_disk(card.id).get("plotline"), plotline.id)

        self.service.delete_plotline(plotline.id)  # delete purges referrers (#345)
        # Assert the purge rewrote the card FILE (blank the single-ref to ""), not
        # via read_card — whose read-side healing would blank a dangling ref even
        # if the purge had done nothing, masking a broken purge.
        self.assertEqual(self._raw_metadata_on_disk(card.id).get("plotline"), "")

    def test_scene_reference_is_purged_from_disk_when_the_scene_is_deleted(self) -> None:
        scene_id = self._make_scene()
        card = self.service.create_card(CreateCardRequest(title="Card"))
        self.service.save_card(card.id, SaveCardRequest(title="Card", metadata={"scene": scene_id}))
        self.assertEqual(self._raw_metadata_on_disk(card.id).get("scene"), scene_id)

        self.service.delete_scene(scene_id)  # delete_scene purges referrers too
        # Same as the plotline case: this exercises the PURGE (delete_scene rewrites
        # the card file), NOT read-side healing — the read-heal branch is covered
        # directly by test_read_side_healing_blanks_a_dangling_reference below.
        self.assertEqual(self._raw_metadata_on_disk(card.id).get("scene"), "")

    def test_read_side_healing_blanks_a_dangling_reference(self) -> None:
        # The genuine read-heal path, isolated from purge: a card FILE carrying a
        # reference whose target never existed (save_card would 422 it, but an
        # ancestor-project purge that rewrote the ancestor and not this book's card
        # can leave one). read_card must blank it to "", not 422 and not the dead id.
        card = self.service.create_card(CreateCardRequest(title="Card"))
        path = self.service._path_for_node_id(card.id, "plot")
        self.service._write_node_entry_file(path, card.id, "Card", "plot:card", {"plotline": "plot_ghost"}, "")
        self.assertEqual(self.service.read_card(card.id).metadata.get("plotline"), "")

    def test_save_rejects_a_reference_to_a_nonexistent_node(self) -> None:
        # The card's reason to exist is its references, so save must reject a ghost
        # target rather than persist a dangling ref (which the reader would heal).
        card = self.service.create_card(CreateCardRequest(title="Card"))
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_card(card.id, SaveCardRequest(title="Card", metadata={"plotline": "plot_ghost"}))
        self.assertEqual(ctx.exception.status_code, 422)


class CardCausalLinkTests(PlotTestCase):
    """Authored card→card causal links (ADR-0048 S7 Slice 6b): the "leads to" edges a
    writer draws. Stored as plain-text target ids in `causal_links` (v1 bars refs from
    list-item shapes), so integrity is plot-local — `_heal_causal_links` drops, on card
    save AND read, any target that is gone, is a non-card, is the card itself, or
    duplicates another; an all-dangling list heals to sparse, never `[]`. The board's
    causal edge layer draws one directed edge per surviving target."""

    def _raw_causal_on_disk(self, node_id: str) -> object:
        # The card's stored `causal_links` straight from disk (bypassing read-side
        # healing) — a heal assertion here proves the save write-back happened.
        path = self.service._path_for_node_id(node_id, "plot")
        front_matter = self.service._read_front_matter_only(path, strict=True)
        return (front_matter.get("metadata") or {}).get("causal_links")

    def _projected_causal(self, card_id: str) -> list[str]:
        projection = self.service.read_plot_board_projection()
        return next(c for c in projection.cards if c.id == card_id).causal_links

    def _save_causal(self, card_id: str, title: str, targets: list[str]) -> None:
        self.service.save_card(
            card_id,
            SaveCardRequest(title=title, metadata={"causal_links": [{"target": t} for t in targets]}),
        )

    def test_a_link_to_a_live_card_round_trips(self) -> None:
        a = self.service.create_card(CreateCardRequest(title="A"))
        b = self.service.create_card(CreateCardRequest(title="B"))
        self._save_causal(a.id, "A", [b.id])
        self.assertEqual(self._raw_causal_on_disk(a.id), [{"target": b.id}])
        self.assertEqual(self._projected_causal(a.id), [b.id])

    def test_a_self_link_is_dropped(self) -> None:
        a = self.service.create_card(CreateCardRequest(title="A"))
        self._save_causal(a.id, "A", [a.id])
        self.assertIsNone(self._raw_causal_on_disk(a.id))  # healed to sparse, not [{target: self}]
        self.assertEqual(self._projected_causal(a.id), [])

    def test_duplicate_targets_are_deduped(self) -> None:
        a = self.service.create_card(CreateCardRequest(title="A"))
        b = self.service.create_card(CreateCardRequest(title="B"))
        self._save_causal(a.id, "A", [b.id, b.id])
        self.assertEqual(self._raw_causal_on_disk(a.id), [{"target": b.id}])

    def test_a_non_card_target_is_dropped(self) -> None:
        # A plotline is a live node but not a card, so it is no valid edge endpoint.
        a = self.service.create_card(CreateCardRequest(title="A"))
        plotline = self.service.create_plotline(CreatePlotlineRequest(title="Thread"))
        self._save_causal(a.id, "A", [plotline.id])
        self.assertIsNone(self._raw_causal_on_disk(a.id))

    def test_read_side_healing_drops_a_gone_target(self) -> None:
        # `causal_links` are plain text, so deleting the target card does NOT purge the
        # referrer (the ref machinery never reaches item shapes) — the reader heals it.
        a = self.service.create_card(CreateCardRequest(title="A"))
        b = self.service.create_card(CreateCardRequest(title="B"))
        self._save_causal(a.id, "A", [b.id])
        self.service.delete_card(b.id)
        self.assertIsNone(self.service.read_card(a.id).metadata.get("causal_links"))
        self.assertEqual(self._projected_causal(a.id), [])

    def test_an_all_dangling_list_heals_to_sparse(self) -> None:
        # A card FILE whose only causal target never existed (an ancestor-project purge
        # can leave one): read heals to sparse (key removed), never a bare `[]`.
        a = self.service.create_card(CreateCardRequest(title="A"))
        path = self.service._path_for_node_id(a.id, "plot")
        self.service._write_node_entry_file(
            path, a.id, "A", "plot:card", {"causal_links": [{"target": "plot_ghost"}]}, ""
        )
        self.assertIsNone(self.service.read_card(a.id).metadata.get("causal_links"))

    def test_projection_keeps_only_live_targets(self) -> None:
        a = self.service.create_card(CreateCardRequest(title="A"))
        b = self.service.create_card(CreateCardRequest(title="B"))
        c = self.service.create_card(CreateCardRequest(title="C"))
        self._save_causal(a.id, "A", [b.id, c.id])
        self.assertEqual(set(self._projected_causal(a.id)), {b.id, c.id})
        self.service.delete_card(c.id)
        self.assertEqual(self._projected_causal(a.id), [b.id])


class CardOperationTests(PlotTestCase):
    """The card operations (ADR-0048 §1 / §S5). *realize* mints a scene from a
    card and attaches it; *seed-from-manuscript* is the bulk inverse — one
    attached card per existing scene; *attach* is a plain card save the board's
    picker will drive, so it has no endpoint here. Plus the settled cardinality
    invariants: 0..n cards per scene, 0..1 scene per card, attachment is by id
    (survives a scene move), and a deleted scene dangles visibly."""

    def _chapter(self, title: str = "Chapter") -> str:
        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type="manuscript:chapter", parent_id=structure.root.id)
        )
        return next(c.id for c in doc.root.children if c.type == "manuscript:chapter" and c.title == title)

    def _scene(self, parent_id: str, title: str) -> str:
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=parent_id)).id

    def _structure_node_id_for_scene(self, scene_id: str) -> str:
        node = TreeStructureService.find_by_leaf_ref(self.service.read_structure(), scene_id)
        assert node is not None
        return node.id

    def _leaf_scene_ids(self) -> set[str]:
        # Every leaf scene in the manuscript (a fresh project pre-seeds one, so
        # the seed assertions are relative to this, not to a hardcoded count).
        ids: set[str] = set()

        def walk(node) -> None:
            if node.type == "manuscript:scene" and node.scene_id:
                ids.add(node.scene_id)
            for child in node.children:
                walk(child)

        walk(self.service.read_structure().root)
        return ids

    # ----- realize --------------------------------------------------------

    def test_realize_mints_and_attaches_a_scene(self) -> None:
        card = self.client.post("/api/plot/cards", json={"title": "The Confession"}).json()
        realized = self.client.post(f"/api/plot/cards/{card['id']}/realize", json={})
        self.assertEqual(realized.status_code, 200, realized.text)
        scene_id = realized.json()["metadata"]["scene"]
        # New manuscript nodes mint `manuscript_*` ids now the kind is renamed (#86).
        self.assertTrue(scene_id.startswith("manuscript_"))
        # The scene is real, titled after the card, and starts empty — the
        # synopsis is the card's plan, not the scene's prose.
        scene = self.service.read_scene(scene_id)
        self.assertEqual(scene.title, "The Confession")
        self.assertEqual(scene.body, "")

    def test_realize_keeps_the_synopsis_on_the_card(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="Card"))
        self.service.save_card(card.id, SaveCardRequest(title="Card", body="She finally tells him."))
        realized = self.service.realize_card(card.id, RealizeCardRequest())
        self.assertEqual(realized.body, "She finally tells him.\n")  # synopsis stays on the card
        self.assertEqual(self.service.read_scene(realized.metadata["scene"]).body, "")  # scene prose is empty

    def test_realize_places_the_scene_under_a_given_parent(self) -> None:
        chapter_id = self._chapter("Act One")
        card = self.service.create_card(CreateCardRequest(title="Beat"))
        realized = self.service.realize_card(card.id, RealizeCardRequest(parent_id=chapter_id))
        chapter = TreeStructureService.find_node(self.service.read_structure(), chapter_id)
        node_id = self._structure_node_id_for_scene(realized.metadata["scene"])
        self.assertIn(node_id, [c.id for c in chapter.children])

    def test_realize_on_an_attached_card_409s(self) -> None:
        scene_id = self._scene(self._chapter(), "Existing")
        card = self.service.create_card(CreateCardRequest(title="Card"))
        self.service.save_card(card.id, SaveCardRequest(title="Card", metadata={"scene": scene_id}))
        # 0..1 scene per card: realizing again would orphan the first scene.
        response = self.client.post(f"/api/plot/cards/{card.id}/realize", json={})
        self.assertEqual(response.status_code, 409, response.text)

    # ----- seed-from-manuscript ------------------------------------------

    def test_seed_creates_one_attached_card_per_scene(self) -> None:
        chapter_id = self._chapter()
        scene_ids = [self._scene(chapter_id, t) for t in ("Arrival", "The Turn", "Aftermath")]
        all_scenes = self._leaf_scene_ids()
        seeded = self.client.post("/api/plot/seed-from-manuscript")
        self.assertEqual(seeded.status_code, 200, seeded.text)
        cards = self.service.list_cards().entries
        # Exactly one card per leaf scene, attached — my three among them.
        self.assertEqual({c.metadata.get("scene") for c in cards}, all_scenes)
        self.assertEqual(len(cards), len(all_scenes))
        self.assertLessEqual(set(scene_ids), all_scenes)
        # Title mirrors the scene.
        arrival = next(c for c in cards if c.metadata.get("scene") == scene_ids[0])
        self.assertEqual(arrival.title, "Arrival")

    def test_seed_is_idempotent(self) -> None:
        chapter_id = self._chapter()
        for t in ("One", "Two"):
            self._scene(chapter_id, t)
        expected = len(self._leaf_scene_ids())
        first = self.service.seed_cards_from_manuscript()
        second = self.service.seed_cards_from_manuscript()
        self.assertEqual(len(first.entries), expected)
        self.assertEqual(len(second.entries), expected)  # a second run adds nothing

    def test_seed_skips_scenes_that_already_have_a_card(self) -> None:
        chapter_id = self._chapter()
        kept, fresh = self._scene(chapter_id, "Kept"), self._scene(chapter_id, "New")
        all_scenes = self._leaf_scene_ids()
        existing = self.service.create_card(CreateCardRequest(title="Hand-made"))
        self.service.save_card(existing.id, SaveCardRequest(title="Hand-made", metadata={"scene": kept}))
        self.service.seed_cards_from_manuscript()
        cards = self.service.list_cards().entries
        # One card per leaf scene, no duplicate for the scene that already had a
        # hand-made card (the kept scene keeps exactly one).
        self.assertEqual(len(cards), len(all_scenes))
        self.assertEqual({c.metadata.get("scene") for c in cards}, all_scenes)
        self.assertEqual(sum(1 for c in cards if c.metadata.get("scene") == kept), 1)
        self.assertIn(fresh, {c.metadata.get("scene") for c in cards})

    def _seed_fresh_project_and_count_rebuilds(self, scene_count: int) -> tuple[int, int]:
        # A separate project per call (not self.service) so the two scene counts
        # don't share manuscript state. Node-index calls are counted only across
        # seed_cards_from_manuscript() itself, not the scene setup above it.
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name).resolve() / "project"
        service = open_test_project(root, "Perf Project")
        structure = service.read_structure()
        doc = service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter", entry_type="manuscript:chapter", parent_id=structure.root.id)
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "manuscript:chapter" and c.title == "Chapter")
        for i in range(scene_count):
            service.create_scene(CreateSceneRequest(title=f"Scene {i}", parent_id=chapter_id))

        calls = 0
        original = service._build_node_index

        def counting(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        with patch.object(service, "_build_node_index", side_effect=counting):
            result = service.seed_cards_from_manuscript()
        # Attachment preserved: every minted card carries its own scene ref.
        # (A fresh project pre-seeds one scene, so the count is relative to what
        # this helper added, not a bare `scene_count`.)
        self.assertEqual(len(result.entries), scene_count + 1)
        for card in result.entries:
            self.assertTrue(card.metadata.get("scene"))
        return calls, len(result.entries)

    def test_seed_index_lookups_scale_one_to_one_with_scenes_not_writes(self) -> None:
        # _create_plot_folder_node (unchanged, per #747) validates the seeded
        # `scene` ref through _validate_reference_target, which needs exactly one
        # _build_node_index() lookup per scene to confirm the id exists — that
        # one-per-scene cost is inherent to the validated-write path and not what
        # this fix removes. What it removes is the *second* multiplier: the old
        # create_card + _set_card_scene loop cost ~3 lookups per scene (create's
        # read-back, save's own validation, save's read-back — see the diagnostic
        # in this PR's description), a genuine O(N) x O(N) node-index touch. This
        # fix does exactly one lookup per scene, so the *delta* in call count
        # between two runs must equal exactly the delta in scene count — not some
        # multiple of it — as scenes scale up.
        few_calls, few_scenes = self._seed_fresh_project_and_count_rebuilds(2)
        many_calls, many_scenes = self._seed_fresh_project_and_count_rebuilds(6)
        self.assertEqual(many_calls - few_calls, many_scenes - few_scenes)
        self.assertLess(many_calls, many_scenes * 2)  # nowhere near the old ~3x/scene

    # ----- cardinality invariants (ADR §S5) -------------------------------

    def test_many_cards_may_attach_one_scene(self) -> None:
        scene_id = self._scene(self._chapter(), "Crowded")
        for title in ("Beat A", "Beat B"):
            card = self.service.create_card(CreateCardRequest(title=title))
            self.service.save_card(card.id, SaveCardRequest(title=title, metadata={"scene": scene_id}))
        attached = [c for c in self.service.list_cards().entries if c.metadata.get("scene") == scene_id]
        self.assertEqual(len(attached), 2)  # 0..n cards per scene — no uniqueness the other way

    def test_attachment_survives_a_scene_move(self) -> None:
        source, dest = self._chapter("Source"), self._chapter("Dest")
        scene_id = self._scene(source, "Wanderer")
        card = self.service.create_card(CreateCardRequest(title="Card"))
        self.service.save_card(card.id, SaveCardRequest(title="Card", metadata={"scene": scene_id}))
        self.service.move_structure_node(self._structure_node_id_for_scene(scene_id), dest, 0)
        # The ref is by id, not by path or manuscript slot, so the move is invisible to it.
        self.assertEqual(self.service.read_card(card.id).metadata.get("scene"), scene_id)

    def test_realized_scene_deletion_leaves_the_card_visibly_dangling(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="Card"))
        realized = self.service.realize_card(card.id, RealizeCardRequest())
        self.service.delete_scene(realized.metadata["scene"])
        # Not silent, not a dead id: the attachment blanks to "" (§S5 / #345 heal).
        self.assertEqual(self.service.read_card(card.id).metadata.get("scene"), "")


class PlotCrossFamilyGuardTests(PlotTestCase):
    """Plotlines, cards, and templates share the `plot/` folder and the `plot_`
    id space, so the endpoint is the only discriminator between them. A node of
    one family must not be created, read, retyped, or deleted through another
    family's endpoint (ADR-0048 S5a review): the `is_a` family guard enforces it.
    read_plot_template always guarded this; the shared plot-folder CRUD now does
    for plotlines and cards too."""

    def test_creating_a_foreign_plot_type_via_the_cards_endpoint_is_refused(self) -> None:
        for foreign in ("plot:plotline", "plot:template", "plot:board"):
            response = self.client.post("/api/plot/cards", json={"title": "X", "entry_type": foreign})
            self.assertEqual(response.status_code, 422, f"{foreign}: {response.text}")

    def test_reading_a_plotline_via_the_cards_endpoint_404s(self) -> None:
        plotline = self.client.post("/api/plot/plotlines", json={"title": "Thread"}).json()
        self.assertEqual(self.client.get(f"/api/plot/cards/{plotline['id']}").status_code, 404)

    def test_saving_a_card_over_a_plotline_is_refused_and_leaves_it_untouched(self) -> None:
        plotline = self.client.post("/api/plot/plotlines", json={"title": "Thread"}).json()
        # A color so a retype-to-card (which would drop non-card fields) is detectable.
        self.client.put(
            f"/api/plot/plotlines/{plotline['id']}",
            json={"title": "Thread", "body": "b", "metadata": {"color": "rose"}},
        )
        response = self.client.put(f"/api/plot/cards/{plotline['id']}", json={"title": "Hijack", "body": ""})
        self.assertEqual(response.status_code, 404, response.text)
        got = self.client.get(f"/api/plot/plotlines/{plotline['id']}").json()
        self.assertEqual(got["entry_type"], "plot:plotline")  # not retyped
        self.assertEqual(got["metadata"]["color"], "rose")  # its own field survives

    def test_deleting_a_plotline_via_the_cards_endpoint_is_refused(self) -> None:
        plotline = self.client.post("/api/plot/plotlines", json={"title": "Thread"}).json()
        self.assertEqual(self.client.delete(f"/api/plot/cards/{plotline['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/plot/plotlines/{plotline['id']}").status_code, 200)

    def test_saving_a_plotline_over_a_card_is_refused_symmetrically(self) -> None:
        # The pre-existing plotline path is hardened by the same shared guard.
        card = self.client.post("/api/plot/cards", json={"title": "Card"}).json()
        response = self.client.put(f"/api/plot/plotlines/{card['id']}", json={"title": "Hijack", "body": ""})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.client.get(f"/api/plot/cards/{card['id']}").json()["entry_type"], "plot:card")

    def test_creating_a_foreign_plot_type_via_the_plotlines_endpoint_is_refused(self) -> None:
        for foreign in ("plot:card", "plot:template", "plot:board"):
            response = self.client.post("/api/plot/plotlines", json={"title": "X", "entry_type": foreign})
            self.assertEqual(response.status_code, 422, f"{foreign}: {response.text}")

    def test_reading_a_card_via_the_plotlines_endpoint_404s(self) -> None:
        card = self.client.post("/api/plot/cards", json={"title": "Card"}).json()
        self.assertEqual(self.client.get(f"/api/plot/plotlines/{card['id']}").status_code, 404)

    def test_saving_an_owned_template_via_the_cards_endpoint_keeps_its_beat_roster(self) -> None:
        # The worst case: a card-endpoint write over an owned template would drop
        # its `template:` block (the beat roster) — _write_node_entry_file emits no
        # such block. The is_a guard 404s it before any write.
        library = next(t for t in self.client.get("/api/plot/templates").json()["entries"] if not t["editable"])
        owned = self.client.post(f"/api/plot/templates/{library['id']}/fork").json()
        response = self.client.put(f"/api/plot/cards/{owned['id']}", json={"title": "Hijack", "body": ""})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertTrue(self.client.get(f"/api/plot/templates/{owned['id']}").json()["metadata"]["beats"])


class PlotBoardHttpTests(PlotTestCase):
    def test_get_or_creates_the_board_singleton(self) -> None:
        first = self.client.get("/api/plot/board")
        self.assertEqual(first.status_code, 200, first.text)
        board = first.json()
        self.assertTrue(board["id"].startswith("plot_"))
        self.assertEqual(board["entry_type"], "plot:board")
        # Created on first open, at the project root (not in the plot/ folder).
        self.assertTrue((self.root / "plot-board.md").exists())
        self.assertFalse((self.root / "plot" / "plot-board.md").exists())
        # Singleton: a second open returns the same identity, not a new one.
        self.assertEqual(self.client.get("/api/plot/board").json()["id"], board["id"])

    def test_layout_round_trips(self) -> None:
        self.client.get("/api/plot/board")  # create
        layout = {"columns": {"c1": ["card_a", "card_b"]}, "collapsed": ["g1"], "viewport": {"x": 10, "zoom": 1.5}}
        saved = self.client.put("/api/plot/board", json={"layout": layout})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get("/api/plot/board").json()["layout"], layout)

    def test_stale_base_revision_conflicts(self) -> None:
        self.client.get("/api/plot/board")
        conflict = self.client.put("/api/plot/board", json={"layout": {}, "base_revision": "stale"})
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_board_is_not_in_the_node_index(self) -> None:
        # The board is a directly-addressed singleton, deliberately NOT a member
        # of the plot/ family folder — so it never enters the node index, and an
        # ancestor's board can never leak into the resolved set (ADR-0048 §3).
        self.service.read_plot_board()  # create via the bound service
        index = self.service._build_node_index()
        self.assertEqual([e for e in index.by_id.values() if e.entry_type == "plot:board"], [])
        # It is not a plotline either.
        self.assertEqual(self.service.list_plotlines().entries, [])


class PlotBoardProjectionTests(PlotTestCase):
    """The board projection (ADR-0048 S7a; ADR-0053): one read model — plotlines
    (with their beat rosters), cards with their plotline/scene refs, and the board's
    opaque layout. A deleted scene purges the card ref, so a gone scene projects as
    an unattached card, never a dangling pointer. Computed and read-only; card +
    plotline + board data only, never the read-only Library templates."""

    def _scene(self, title: str) -> str:
        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter", entry_type="manuscript:chapter", parent_id=structure.root.id)
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "manuscript:chapter")
        return self.service.create_scene(CreateSceneRequest(title=title, parent_id=chapter_id)).id

    def test_empty_board_projects_empty_and_creates_the_singleton(self) -> None:
        response = self.client.get("/api/plot/board/projection")
        self.assertEqual(response.status_code, 200, response.text)
        projection = response.json()
        self.assertTrue(projection["board_id"].startswith("plot_"))
        self.assertEqual(projection["plotlines"], [])
        self.assertEqual(projection["cards"], [])
        self.assertEqual(projection["layout"], {})
        # The projection opens the board, so a first read mints the singleton.
        self.assertTrue((self.root / "plot-board.md").exists())

    def test_projects_cards_with_resolved_plotline_and_scene_refs(self) -> None:
        romance = self.service.create_plotline(CreatePlotlineRequest(title="Romance"))
        self.service.save_plotline(romance.id, SavePlotlineRequest(title="Romance", metadata={"color": "rose"}))
        self.service.create_plotline(CreatePlotlineRequest(title="Mystery"))
        scene_id = self._scene("The Meeting")
        card = self.service.create_card(CreateCardRequest(title="They Meet"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title="They Meet",
                body="She spills his coffee.",
                metadata={"plotline": romance.id, "scene": scene_id},
            ),
        )
        projection = self.client.get("/api/plot/board/projection").json()
        # Both plotlines are present; a set colour is carried, an unset one is null.
        lanes = {p["title"]: p for p in projection["plotlines"]}
        self.assertEqual(lanes["Romance"]["color"], "rose")
        self.assertIsNone(lanes["Mystery"]["color"])
        # The card carries its synopsis (the body) and both resolved refs.
        projected = next(c for c in projection["cards"] if c["id"] == card.id)
        self.assertEqual(projected["synopsis"], "She spills his coffee.\n")
        self.assertEqual(projected["plotline"], romance.id)
        self.assertEqual(projected["scene"], scene_id)

    def test_projection_carries_a_plotlines_beat_roster(self) -> None:
        # ADR-0053 §1/§3: a plotline IS a template instance, so the board node needs
        # its beats — the projection surfaces the roster (beat_id + title, in order).
        plotline = self.service.instantiate_plot_template("builtin-plot-three-act-story-arc")
        roster = plotline.metadata["instance_beats"]
        projected = next(
            p for p in self.service.read_plot_board_projection().plotlines if p.id == plotline.id
        )
        self.assertEqual([b.beat_id for b in projected.beats], [b["id"] for b in roster])
        self.assertEqual(projected.beats[0].title, roster[0]["title"])
        # With no cards linking anything, every beat is a gap (use_count 0; ADR-0053 §6).
        self.assertTrue(all(b.use_count == 0 for b in projected.beats))
        # A plain / ad-hoc plotline carries an empty roster, not a missing field.
        plain = self.service.create_plotline(CreatePlotlineRequest(title="Ad-hoc"))
        projected_plain = next(
            p for p in self.service.read_plot_board_projection().plotlines if p.id == plain.id
        )
        self.assertEqual(projected_plain.beats, [])

    def test_projection_counts_how_many_cards_fulfil_each_beat(self) -> None:
        # ADR-0053 §6 / S5a: each beat's use_count = how many cards fulfil it (0 = a gap).
        plotline = self.service.instantiate_plot_template("builtin-plot-three-act-story-arc")
        roster = plotline.metadata["instance_beats"]
        first, second = roster[0]["id"], roster[1]["id"]
        # Two cards fulfil the first beat, one the second — the rest stay gaps.
        for title in ("Card A", "Card B"):
            card = self.service.create_card(CreateCardRequest(title=title))
            self.service.save_card(
                card.id,
                SaveCardRequest(
                    title=title, body="", metadata={"beat_links": [{"plotline": plotline.id, "beat_id": first}]}
                ),
            )
        card_c = self.service.create_card(CreateCardRequest(title="Card C"))
        self.service.save_card(
            card_c.id,
            SaveCardRequest(
                title="Card C", body="", metadata={"beat_links": [{"plotline": plotline.id, "beat_id": second}]}
            ),
        )
        projected = next(
            p for p in self.service.read_plot_board_projection().plotlines if p.id == plotline.id
        )
        counts = {b.beat_id: b.use_count for b in projected.beats}
        self.assertEqual(counts[first], 2)
        self.assertEqual(counts[second], 1)
        # Only those two beats are fulfilled; every other beat of the roster is a 0.
        self.assertEqual(sum(counts.values()), 3)

    def test_unattached_card_projects_null_refs(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="Floating"))
        projected = next(c for c in self.service.read_plot_board_projection().cards if c.id == card.id)
        self.assertIsNone(projected.plotline)
        self.assertIsNone(projected.scene)

    def test_deleting_an_attached_scene_leaves_the_card_unattached(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="Orphan"))
        realized = self.service.realize_card(card.id, RealizeCardRequest())
        self.service.delete_scene(realized.metadata["scene"])
        projected = next(c for c in self.service.read_plot_board_projection().cards if c.id == card.id)
        # delete_scene purges the card's ref (§S5), so the card projects as
        # unattached — not a live scene, and not a dangling pointer to chase.
        self.assertIsNone(projected.scene)

    def test_layout_is_carried_through_verbatim(self) -> None:
        self.client.get("/api/plot/board")  # create
        layout = {"positions": {"card_a": {"x": 40, "y": 12}}, "viewport": {"zoom": 1.5}}
        self.client.put("/api/plot/board", json={"layout": layout})
        projection = self.client.get("/api/plot/board/projection").json()
        self.assertEqual(projection["layout"], layout)
        self.assertTrue(projection["board_revision"])  # a saved board carries a revision


class PlotBoardContainerProjectionTests(PlotTestCase):
    """The board projection's manuscript-structure join (ADR-0048 S7 Slice 4): a
    card lays out inside its scene's INNERMOST container, and the projection carries
    the used containers (plus ancestors) in manuscript reading order so the board
    can nest a chapter box inside its act. Membership is derived from the scene —
    a homeless card (no scene, or a scene under the root) has no container."""

    def _node(self, title: str, entry_type: str, parent_id: str) -> str:
        self.service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type=entry_type, parent_id=parent_id)
        )
        found: list[str] = []

        def walk(node) -> None:
            if node.title == title and node.type == entry_type:
                found.append(node.id)
            for child in node.children:
                walk(child)

        walk(self.service.read_structure().root)
        return found[-1]

    def _card_on(self, title: str, scene_id: str | None) -> str:
        card = self.service.create_card(CreateCardRequest(title=title))
        metadata = {"scene": scene_id} if scene_id else {}
        self.service.save_card(card.id, SaveCardRequest(title=title, body="", metadata=metadata))
        return card.id

    def _containers_by_id(self, projection) -> dict:
        return {c.id: c for c in projection.containers}

    def test_card_projects_its_innermost_container_with_the_nesting(self) -> None:
        root = self.service.read_structure().root.id
        act = self._node("Act I", "manuscript:act", root)
        chapter = self._node("Chapter 1", "manuscript:chapter", act)
        scene = self.service.create_scene(CreateSceneRequest(title="Opening", parent_id=chapter)).id
        card_id = self._card_on("Beat card", scene)

        projection = self.service.read_plot_board_projection()
        projected = next(c for c in projection.cards if c.id == card_id)
        # The card's home is the scene's immediate container (the chapter), not the act.
        self.assertEqual(projected.container, chapter)
        by_id = self._containers_by_id(projection)
        self.assertEqual(by_id[chapter].parent, act)  # chapter nests inside its act
        self.assertIsNone(by_id[act].parent)  # the act is top-level (parent is the root)
        self.assertEqual(by_id[chapter].title, "Chapter 1")

    def test_containers_are_in_manuscript_reading_order(self) -> None:
        root = self.service.read_structure().root.id
        act1 = self._node("Act I", "manuscript:act", root)
        chapter1 = self._node("Chapter 1", "manuscript:chapter", act1)
        act2 = self._node("Act II", "manuscript:act", root)
        chapter2 = self._node("Chapter 2", "manuscript:chapter", act2)
        for title, chapter in (("c1", chapter1), ("c2", chapter2)):
            scene = self.service.create_scene(CreateSceneRequest(title=title, parent_id=chapter)).id
            self._card_on(title, scene)

        ids = [c.id for c in self.service.read_plot_board_projection().containers]
        # Pre-order (reading order): each act immediately followed by its chapter.
        self.assertEqual(ids, [act1, chapter1, act2, chapter2])

    def test_only_containers_that_hold_a_carded_scene_are_projected(self) -> None:
        root = self.service.read_structure().root.id
        act = self._node("Act I", "manuscript:act", root)
        carded = self._node("Carded", "manuscript:chapter", act)
        empty = self._node("Empty", "manuscript:chapter", act)
        # `empty` even holds a scene — but no card points at it, so it is not a
        # board concern and must not be projected.
        self.service.create_scene(CreateSceneRequest(title="lonely", parent_id=empty))
        scene = self.service.create_scene(CreateSceneRequest(title="carded scene", parent_id=carded)).id
        self._card_on("card", scene)

        ids = {c.id for c in self.service.read_plot_board_projection().containers}
        self.assertEqual(ids, {act, carded})  # the ancestor act rides along; the empty chapter does not

    def test_a_scene_less_card_is_homeless(self) -> None:
        card_id = self._card_on("Floating", None)
        projected = next(c for c in self.service.read_plot_board_projection().cards if c.id == card_id)
        self.assertIsNone(projected.container)

    def test_a_scene_under_the_root_is_homeless(self) -> None:
        # A fresh project has no containers, so create_scene drops the scene under
        # the root itself — its card has no container box to lay out inside.
        scene = self.service.create_scene(CreateSceneRequest(title="Rootless")).id
        card_id = self._card_on("under root", scene)
        projection = self.service.read_plot_board_projection()
        projected = next(c for c in projection.cards if c.id == card_id)
        self.assertIsNone(projected.container)
        self.assertEqual(projection.containers, [])

    def test_deleting_the_scene_makes_the_card_homeless(self) -> None:
        root = self.service.read_structure().root.id
        chapter = self._node("Chapter 1", "manuscript:chapter", root)
        scene = self.service.create_scene(CreateSceneRequest(title="Opening", parent_id=chapter)).id
        card_id = self._card_on("Beat card", scene)
        self.service.delete_scene(scene)

        projection = self.service.read_plot_board_projection()
        projected = next(c for c in projection.cards if c.id == card_id)
        # delete_scene purges the card's ref (§S5) → no scene → no container, and
        # the now-empty chapter drops out of the projection.
        self.assertIsNone(projected.container)
        self.assertEqual(projection.containers, [])

    def _sequence_of(self, projection, card_id: str) -> int | None:
        return next(c for c in projection.cards if c.id == card_id).sequence

    def test_sequence_follows_manuscript_reading_order(self) -> None:
        # Slice 6: each carded scene's reveal-order rank drives the manuscript edge
        # layer. Two acts, one carded scene each — the first reads before the second.
        root = self.service.read_structure().root.id
        act1 = self._node("Act I", "manuscript:act", root)
        chapter1 = self._node("Chapter 1", "manuscript:chapter", act1)
        act2 = self._node("Act II", "manuscript:act", root)
        chapter2 = self._node("Chapter 2", "manuscript:chapter", act2)
        scene1 = self.service.create_scene(CreateSceneRequest(title="s1", parent_id=chapter1)).id
        scene2 = self.service.create_scene(CreateSceneRequest(title="s2", parent_id=chapter2)).id
        first = self._card_on("first", scene1)
        second = self._card_on("second", scene2)

        projection = self.service.read_plot_board_projection()
        first_seq = self._sequence_of(projection, first)
        second_seq = self._sequence_of(projection, second)
        # scene1 reads immediately before scene2, so their ranks are consecutive —
        # a relative assertion (robust to the project's pre-existing starter scene,
        # which occupies an earlier rank) and exactly what the manuscript chain needs.
        self.assertIsNotNone(first_seq)
        self.assertEqual(second_seq, first_seq + 1)

    def test_a_scene_less_card_has_no_sequence(self) -> None:
        card_id = self._card_on("Floating", None)
        # No scene → no reveal-order position, so it joins no manuscript chain.
        self.assertIsNone(self._sequence_of(self.service.read_plot_board_projection(), card_id))

    def test_a_scene_under_the_root_is_still_ranked(self) -> None:
        # Homeless (no container) but carded — it holds a real reading position, so
        # it is ranked and can join the manuscript spine.
        scene = self.service.create_scene(CreateSceneRequest(title="Rootless")).id
        card_id = self._card_on("under root", scene)
        projection = self.service.read_plot_board_projection()
        self.assertIsNone(next(c for c in projection.cards if c.id == card_id).container)
        self.assertIsNotNone(self._sequence_of(projection, card_id))  # ranked despite being homeless

    def test_cards_on_the_same_scene_share_a_sequence(self) -> None:
        # n cards per scene (ADR §S5) → they sit at the same reveal-order rank.
        root = self.service.read_structure().root.id
        chapter = self._node("Chapter 1", "manuscript:chapter", root)
        scene = self.service.create_scene(CreateSceneRequest(title="Opening", parent_id=chapter)).id
        a = self._card_on("a", scene)
        b = self._card_on("b", scene)
        projection = self.service.read_plot_board_projection()
        self.assertEqual(self._sequence_of(projection, a), self._sequence_of(projection, b))

    def test_detaching_the_scene_clears_the_sequence(self) -> None:
        root = self.service.read_structure().root.id
        chapter = self._node("Chapter 1", "manuscript:chapter", root)
        scene = self.service.create_scene(CreateSceneRequest(title="Opening", parent_id=chapter)).id
        card_id = self._card_on("Beat card", scene)
        self.service.delete_scene(scene)
        # Ref purged → no scene → no sequence (tracks re-attachment, like page_status).
        self.assertIsNone(self._sequence_of(self.service.read_plot_board_projection(), card_id))


class PlotKindRegistrationTests(PlotTestCase):
    def test_plot_family_registered_and_reference_bearing(self) -> None:
        self.assertIn("plot", {family.kind for family in NODE_FAMILIES})
        self.assertIn("plot", REFERENCE_BEARING_KINDS)

    def test_default_schema_defines_plot_types(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertIn("plot:plotline", schema.entry_types)
        self.assertIn("plot:board", schema.entry_types)
        self.assertIn("plot:template", schema.entry_types)
        self.assertIn("plot:card", schema.entry_types)
        self.assertEqual(schema.entry_types["plot:plotline"].kind, "plot")
        self.assertEqual(schema.entry_types["plot:template"].kind, "plot")
        self.assertEqual(schema.entry_types["plot:card"].kind, "plot")

    def test_card_type_is_shown_and_editable_in_detail_types(self) -> None:
        # ADR-0048 §1 / #738: the card must appear in Detail Types (a `plot`-kind
        # entry type, so #729's Plot tab surfaces it) with editable fields. The
        # resolved fields carry the intrinsic title (editable) plus the card's
        # `plotline` and `scene` references — the fields the schema-authoring UI
        # and the editor render. `has_body` gives it the synopsis prose editor.
        card = self.service.read_metadata_schema().entry_types["plot:card"]
        self.assertTrue(card.has_body)  # synopsis is the body
        self.assertIn("plotline", card.fields)
        self.assertIn("scene", card.fields)
        self.assertIn("title", card.fields)  # intrinsic, injected first — editable

    def test_card_is_indexed_and_kind_tagged(self) -> None:
        created = self.service.create_card(CreateCardRequest(title="A Card"))
        entry = self.service._build_node_index().by_id.get(created.id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, "plot")
        self.assertEqual(entry.entry_type, "plot:card")

    def test_plot_kind_has_an_abstract_base_root(self) -> None:
        # #724: like lore:base / prompt:base, the `plot` kind needs a single
        # abstract root the three concrete types hang off — otherwise
        # `defaultView("plot")` (descendants_of:<root>) resolves to just the first
        # parentless type and the Plot templates pane comes up empty.
        schema = self.service.read_metadata_schema()
        base = schema.entry_types.get("plot:base")
        self.assertIsNotNone(base)
        self.assertTrue(base.abstract)
        self.assertEqual(base.kind, "plot")
        for concrete in ("plot:template", "plot:board", "plot:card"):
            self.assertEqual(
                schema.entry_types[concrete].parent,
                "plot:base",
                f"{concrete} must hang off plot:base so the whole-kind roster resolves",
            )
        # A plotline hangs off plot:base transitively, through the shared
        # plot:thread beat-holder base it and plot:character_arc both inherit
        # from (ADR-0080 §1) — not a direct child any more.
        self.assertEqual(schema.entry_types["plot:plotline"].parent, "plot:thread")
        self.assertIn("plot:base", self.service.entry_type_ancestry("plot:plotline", schema=schema))

    def test_plotline_carries_beats_and_lineage_fields(self) -> None:
        # ADR-0053 §1: a plotline IS a plot-template instance — the `plot:plotline`
        # type carries the specialized-beat + lineage fields (folded in from the
        # retired `plot:template_instance`), and its beats bind to a
        # `plot_instance_beat` group that adds `specifics` to the `plot_beat` shape.
        schema = self.service.read_metadata_schema()
        plotline = schema.entry_types.get("plot:plotline")
        self.assertIsNotNone(plotline)
        self.assertEqual(plotline.kind, "plot")
        self.assertTrue(plotline.has_body)
        # `color` (built-in swatch, #737) lets a plotline carry its own colour.
        for field_id in ("instance_beats", "color", "source_template_id", "source_template_name"):
            self.assertIn(field_id, plotline.fields)
        group = schema.groups.get("plot_instance_beat")
        self.assertIsNotNone(group)
        member_keys = {member.key for member in group.members}
        self.assertIn("specifics", member_keys)
        self.assertTrue({"title", "function", "guidance", "required", "id"} <= member_keys)

    def test_plot_is_a_library_tenant(self) -> None:
        # The Library ships the plot family (its `plot/` folder holds templates),
        # so a second, non-prompt tenant proves the Library model is kind-agnostic.
        self.assertIn("plot", {family.kind for family in LIBRARY_LAYER_FAMILIES})

    def test_project_creation_makes_the_plot_folder(self) -> None:
        self.assertTrue((self.root / "plot").is_dir())

    def test_plotline_is_indexed_and_kind_tagged(self) -> None:
        created = self.service.create_plotline(CreatePlotlineRequest(title="Indexed"))
        entry = self.service._build_node_index().by_id.get(created.id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, "plot")
        self.assertEqual(entry.entry_type, "plot:plotline")

    def test_plot_kind_is_authorable_as_a_subtype(self) -> None:
        # The whitelist accepts `plot`, so the kind is schema-extensible: a user
        # can author a plotline sub-type (ADR-0048 "done means: schema-extensible").
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="plot:romance",
                entry_type=EntryTypeDefinition(name="Romance", kind="plot", parent="plot:plotline"),
            )
        )
        self.assertIn("plot:romance", self.service.read_metadata_schema().entry_types)

    def test_a_plotline_subtype_instance_is_accepted_by_the_family_guard(self) -> None:
        # The family guard admits SUB-TYPES (is_a plot:plotline), not just the
        # exact type — a plot:plotline sub-type instance must create and read back
        # through the plotlines endpoint. A regression tightening the guard to
        # exact-match (`entry_type != family_root`) would 422 the create / 404 the
        # read, and every OTHER test would still pass, so pin the is_a branch here.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="plot:romance",
                entry_type=EntryTypeDefinition(name="Romance", kind="plot", parent="plot:plotline"),
            )
        )
        created = self.service.create_plotline(CreatePlotlineRequest(title="A Romance", entry_type="plot:romance"))
        self.assertEqual(created.entry_type, "plot:romance")
        self.assertEqual(self.service.read_plotline(created.id).entry_type, "plot:romance")

    def test_unknown_kind_is_still_rejected(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="bogus:thing",
                    entry_type=EntryTypeDefinition(name="Bogus", kind="bogus"),
                )
            )
        self.assertEqual(ctx.exception.status_code, 422)


class PlotlineLayeredTests(unittest.TestCase):
    """`plot` is a layered kind, so a plotline can be inherited from an ancestor.

    S4a refuses to edit or delete an inherited plotline: without fork/override
    routing, the write would resolve to the ancestor's own file and rewrite
    (or delete) canon for every downstream book. Plot planning is per-book.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _write_ancestor_plotline(self, folder: Path, node_id: str, title: str) -> None:
        (folder / "plot").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "plot" / f"{node_id}.md", node_id, title, "plot:plotline", {}, ""
        )

    def test_inherited_plotline_is_readable(self) -> None:
        self._write_ancestor_plotline(self.series, "plot_series", "Series Thread")
        got = self.service.read_plotline("plot_series")
        self.assertEqual(got.title, "Series Thread")
        self.assertTrue(got.source_layer_id)  # provenance surfaced

    def test_saving_an_inherited_plotline_is_refused_and_ancestor_untouched(self) -> None:
        self._write_ancestor_plotline(self.series, "plot_series", "Series Thread")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_plotline("plot_series", SavePlotlineRequest(title="Hijacked", body="new"))
        self.assertEqual(ctx.exception.status_code, 409)
        # The ancestor's file must be byte-untouched.
        ancestor = (self.series / "plot" / "plot_series.md").read_text(encoding="utf-8")
        self.assertIn("Series Thread", ancestor)
        self.assertNotIn("Hijacked", ancestor)

    def test_deleting_an_inherited_plotline_is_refused_and_ancestor_survives(self) -> None:
        self._write_ancestor_plotline(self.series, "plot_series", "Series Thread")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_plotline("plot_series")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue((self.series / "plot" / "plot_series.md").exists())


class CardLayeredTests(unittest.TestCase):
    """A card can be inherited from an ancestor (a series-level card flows into the
    book, ADR-0048 §1), and shares the plotline's deferred-inherited-write
    contract: read is fine, save/delete refuse and leave the ancestor untouched.
    Mirrors PlotlineLayeredTests — cards and plotlines are the same book-local
    plot-planning shape."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _write_ancestor_card(self, folder: Path, node_id: str, title: str) -> None:
        (folder / "plot").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "plot" / f"{node_id}.md", node_id, title, "plot:card", {}, ""
        )

    def test_inherited_card_is_readable(self) -> None:
        self._write_ancestor_card(self.series, "plot_series_card", "Series Beat")
        got = self.service.read_card("plot_series_card")
        self.assertEqual(got.title, "Series Beat")
        self.assertTrue(got.source_layer_id)  # provenance surfaced

    def test_saving_an_inherited_card_is_refused_and_ancestor_untouched(self) -> None:
        self._write_ancestor_card(self.series, "plot_series_card", "Series Beat")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_card("plot_series_card", SaveCardRequest(title="Hijacked", body="new"))
        self.assertEqual(ctx.exception.status_code, 409)
        ancestor = (self.series / "plot" / "plot_series_card.md").read_text(encoding="utf-8")
        self.assertIn("Series Beat", ancestor)
        self.assertNotIn("Hijacked", ancestor)

    def test_deleting_an_inherited_card_is_refused_and_ancestor_survives(self) -> None:
        self._write_ancestor_card(self.series, "plot_series_card", "Series Beat")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_card("plot_series_card")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue((self.series / "plot" / "plot_series_card.md").exists())

    def test_realizing_an_inherited_card_is_refused_without_minting_a_scene(self) -> None:
        # realize has a side effect (it creates a scene), so the inherited-write
        # refusal must happen BEFORE the scene is minted — otherwise the 409
        # leaves an orphan scene in the book's manuscript.
        self._write_ancestor_card(self.series, "plot_series_card", "Series Beat")
        before = len(list((self.root / "scenes").glob("*.md")))
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.realize_card("plot_series_card", RealizeCardRequest())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(len(list((self.root / "scenes").glob("*.md"))), before)  # no orphan scene


class PlotTemplateLayeredTests(unittest.TestCase):
    """A `plot:template` can be inherited from an ancestor *project*, not only the
    built-in Library. It is read-only in place there too — save/delete refuse and
    leave the ancestor's file untouched, and fork clones it into this book. Mirrors
    PlotlineLayeredTests, but templates carry a `template:` spec block and (unlike
    plotlines, whose inherited-fork is deferred) support clone-to-own here.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _write_ancestor_template(self, folder: Path, node_id: str, title: str) -> Path:
        (folder / "plot").mkdir(parents=True, exist_ok=True)
        path = folder / "plot" / f"{node_id}.md"
        spec = PlotTemplateSpec(slug=node_id, display_name=title)
        metadata = {"beats": [{"id": "p1", "title": "Beat 1", "function": "Sets the frame."}]}
        self.service._write_plot_template_file(path, node_id, title, spec, "# Series Guide\n", metadata)
        return path

    def test_inherited_template_is_readable_and_read_only(self) -> None:
        self._write_ancestor_template(self.series, "plot_series_tpl", "Series Arc")
        got = self.service.read_plot_template("plot_series_tpl")
        self.assertEqual(got.title, "Series Arc")
        self.assertFalse(got.editable)  # inherited from an ancestor project → read-only
        self.assertTrue(got.source_layer_id)  # provenance surfaced
        self.assertEqual(len(got.metadata["beats"]), 1)

    def test_saving_an_inherited_template_is_refused_and_ancestor_untouched(self) -> None:
        path = self._write_ancestor_template(self.series, "plot_series_tpl", "Series Arc")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_plot_template(
                "plot_series_tpl", SavePlotTemplateRequest(title="Hijacked", template=PlotTemplateSpec())
            )
        self.assertEqual(ctx.exception.status_code, 409)
        ancestor = path.read_text(encoding="utf-8")
        self.assertIn("Series Arc", ancestor)
        self.assertNotIn("Hijacked", ancestor)

    def test_deleting_an_inherited_template_is_refused_and_ancestor_survives(self) -> None:
        path = self._write_ancestor_template(self.series, "plot_series_tpl", "Series Arc")
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_plot_template("plot_series_tpl")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue(path.exists())

    def test_forking_an_inherited_template_clones_into_this_book(self) -> None:
        path = self._write_ancestor_template(self.series, "plot_series_tpl", "Series Arc")
        clone = self.service.fork_plot_template("plot_series_tpl")
        self.assertNotEqual(clone.id, "plot_series_tpl")
        self.assertTrue(clone.editable)  # the book owns the clone
        self.assertEqual(clone.title, "Series Arc")
        self.assertEqual(len(clone.metadata["beats"]), 1)  # beats copied
        # The clone lives in this book, the ancestor original is left in place.
        self.assertTrue((self.root / "plot").is_dir())
        self.assertTrue(path.exists())

    def _author_owned_template_genre(self, title: str, genre: str) -> str:
        created = self.service.create_plot_template(CreatePlotTemplateRequest(title=title))
        current = self.service.read_plot_template(created.id)
        self.service.save_plot_template(
            created.id,
            SavePlotTemplateRequest(
                title=current.title,
                template=current.template,
                body=current.body,
                base_revision=current.revision,
                metadata={**current.metadata, "genre": genre},
            ),
        )
        return created.id

    def test_genre_is_a_template_metadata_field_a_writer_can_author(self) -> None:
        # #1744: genre is a node-metadata field on plot:template, not a hidden
        # `template:` spec attribute — a writer authors it through the ordinary
        # metadata save path, it round-trips on read, and on disk it lives in the
        # `metadata:` block, never back in the spec block.
        genre = "Cozy mystery — a small town, an amateur sleuth, no on-page gore."
        template_id = self._author_owned_template_genre("Cozy Mystery Lens", genre)
        self.assertEqual(self.service.read_plot_template(template_id).metadata["genre"], genre)
        on_disk = self.service._read_front_matter_only(
            self.service._path_for_node_id(template_id, "plot"), strict=True
        )
        self.assertEqual(on_disk["metadata"]["genre"], genre)
        self.assertNotIn("genre", on_disk.get("template", {}))

    def test_instantiating_a_template_seeds_the_plotline_genre_from_its_metadata(self) -> None:
        # #1744: instantiate snapshots the template's *metadata* genre onto the new
        # plotline (previously it read the removed `template.genre` spec attribute).
        genre = "Heist — a crew, a mark, a plan that goes sideways."
        template_id = self._author_owned_template_genre("Heist Lens", genre)
        plotline = self.service.instantiate_plot_template(template_id)
        self.assertEqual(plotline.metadata.get("genre"), genre)


if __name__ == "__main__":
    unittest.main()
