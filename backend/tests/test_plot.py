"""Backend tests for the `plot` kind (ADR-0048 S4a + S4b).

Node types under the new kind: plotlines (`plot:plotline`, a flat layered entry),
the board (`plot:board`, a per-project layout singleton), and templates
(`plot:template`, S4b — the ADR-0049 Library's second tenant). These prove the
wiring end-to-end through FastAPI plus the registration facts (family, schema,
folder, whitelist, Library membership) and the design invariants — a plotline is
indexed and reference-bearing, the board is a directly-addressed singleton kept
out of the node index, and templates ship read-only from the Library and clone
into the project on demand.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateCardRequest,
    CreatePlotlineRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    PlotTemplatePoint,
    PlotTemplateSpec,
    SaveCardRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.references import (
    LIBRARY_LAYER_FAMILIES,
    NODE_FAMILIES,
    REFERENCE_BEARING_KINDS,
)
from app.services.project_service import ProjectService


class _PlotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Plot Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()


class PlotlineHttpTests(_PlotTestCase):
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


class CardHttpTests(_PlotTestCase):
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


class CardReferenceTests(_PlotTestCase):
    """Cards are ordinary nodes, so the reference graph works for free (ADR-0048
    §1): a card's `plotline` / `scene` references round-trip, and a deleted target
    visibly stops resolving — purged when the delete purges referrers (plotline),
    healed on read when it does not (scene)."""

    def _make_scene(self, title: str = "Arrival") -> str:
        structure = self.service.read_structure()
        doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter", entry_type="scene:chapter", parent_id=structure.root.id)
        )
        chapter_id = next(c.id for c in doc.root.children if c.type == "scene:chapter")
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


class PlotCrossFamilyGuardTests(_PlotTestCase):
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

    def test_saving_an_owned_template_via_the_cards_endpoint_keeps_its_beat_roster(self) -> None:
        # The worst case: a card-endpoint write over an owned template would drop
        # its `template:` block (the beat roster) — _write_node_entry_file emits no
        # such block. The is_a guard 404s it before any write.
        library = next(t for t in self.client.get("/api/plot/templates").json()["entries"] if not t["editable"])
        owned = self.client.post(f"/api/plot/templates/{library['id']}/fork").json()
        response = self.client.put(f"/api/plot/cards/{owned['id']}", json={"title": "Hijack", "body": ""})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertTrue(self.client.get(f"/api/plot/templates/{owned['id']}").json()["template"]["plot_points"])


class PlotBoardHttpTests(_PlotTestCase):
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


_THREE_ACT = "builtin-plot-three-act-story-arc"
# The shipped node file behind _THREE_ACT — read to prove a refused write left it
# byte-untouched (backend/app/builtin_library/plot/, relative to backend/tests/).
_BUILTIN_THREE_ACT = Path(__file__).resolve().parents[1] / "app" / "builtin_library" / "plot" / "three-act-story-arc.md"


class PlotTemplateLibraryTests(_PlotTestCase):
    """`plot:template` is the ADR-0049 Library's second tenant (ADR-0048 S4b).

    The 14 diagnostic templates ship as read-only ancestor nodes; a writer clones
    one into the project (a new id, editable) to adapt it. Read-only-in-place and
    clone are the shared Library-tenant surface, proven here for a non-prompt kind.
    """

    def test_ships_fourteen_readonly_library_templates(self) -> None:
        listing = self.client.get("/api/plot/templates")
        self.assertEqual(listing.status_code, 200, listing.text)
        entries = listing.json()["entries"]
        self.assertEqual(len(entries), 14)
        # Every shipped template is inherited from the Library: read-only, flagged.
        self.assertTrue(all(e["is_library"] for e in entries))
        self.assertTrue(all(e["editable"] is False for e in entries))
        self.assertIn(_THREE_ACT, [e["id"] for e in entries])

    def test_read_round_trips_the_spec_and_guide(self) -> None:
        got = self.client.get(f"/api/plot/templates/{_THREE_ACT}")
        self.assertEqual(got.status_code, 200, got.text)
        body = got.json()
        self.assertEqual(body["entry_type"], "plot:template")
        self.assertFalse(body["editable"])
        self.assertEqual(body["template"]["family"], "act")
        points = body["template"]["plot_points"]
        self.assertEqual(len(points), 7)
        self.assertEqual(points[0]["id"], "setup_pressure")
        # The prose guide is the node body.
        self.assertIn("# Three-Act Story Arc", body["body"])

    def test_saving_an_inherited_template_is_refused(self) -> None:
        before = _BUILTIN_THREE_ACT.read_bytes()
        refused = self.client.put(
            f"/api/plot/templates/{_THREE_ACT}",
            json={"title": "Hijacked", "body": "", "template": {}},
        )
        self.assertEqual(refused.status_code, 409, refused.text)
        # The 409 must precede any write: the shipped file is byte-untouched.
        self.assertEqual(_BUILTIN_THREE_ACT.read_bytes(), before)
        self.assertNotIn(b"Hijacked", before)
        # And a re-read still shows the original.
        self.assertEqual(self.client.get(f"/api/plot/templates/{_THREE_ACT}").json()["title"], "Three-Act Story Arc")

    def test_deleting_an_inherited_template_is_refused(self) -> None:
        refused = self.client.delete(f"/api/plot/templates/{_THREE_ACT}")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(self.client.get(f"/api/plot/templates/{_THREE_ACT}").status_code, 200)

    def test_fork_mints_an_owned_editable_copy(self) -> None:
        forked = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork")
        self.assertEqual(forked.status_code, 200, forked.text)
        clone = forked.json()
        # New id, owned + editable, and the Library original stays in place.
        self.assertTrue(clone["id"].startswith("plot_"))
        self.assertNotEqual(clone["id"], _THREE_ACT)
        self.assertTrue(clone["editable"])
        self.assertFalse(clone["is_library"])
        self.assertEqual(clone["title"], "Three-Act Story Arc")
        # The whole spec came across (not just title/body).
        self.assertEqual(len(clone["template"]["plot_points"]), 7)
        # The owned clone is a plot/ family node — indexed like a plotline.
        entry = self.service._build_node_index().by_id.get(clone["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.entry_type, "plot:template")
        # The Library original is still listed alongside the clone.
        ids = [e["id"] for e in self.client.get("/api/plot/templates").json()["entries"]]
        self.assertIn(_THREE_ACT, ids)
        self.assertIn(clone["id"], ids)

    def test_owned_clone_is_editable_and_deletable(self) -> None:
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        spec = clone["template"]
        spec["description"] = "My adapted lens."
        saved = self.client.put(
            f"/api/plot/templates/{clone['id']}",
            json={"title": "My Three-Act", "body": "# Mine\n", "template": spec, "base_revision": clone["revision"]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        reread = self.client.get(f"/api/plot/templates/{clone['id']}").json()
        self.assertEqual(reread["title"], "My Three-Act")
        self.assertEqual(reread["template"]["description"], "My adapted lens.")
        self.assertTrue(reread["editable"])
        deleted = self.client.delete(f"/api/plot/templates/{clone['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get(f"/api/plot/templates/{clone['id']}").status_code, 404)

    def test_forking_an_owned_template_is_refused(self) -> None:
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        # Nothing to clone — an owned template is directly editable.
        again = self.client.post(f"/api/plot/templates/{clone['id']}/fork")
        self.assertEqual(again.status_code, 409, again.text)

    def test_owned_clone_metadata_round_trips_on_save(self) -> None:
        # S4c finding #1: read_plot_template heals + returns metadata, so the save
        # path must persist it — a schema-editor-added field must survive an edit,
        # not be silently wiped (the write-side of the S4b finding #5 gap). Add a
        # `note` field to plot:template, set it on an owned clone, save, re-read.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="note",
                field=MetadataFieldDefinition(name="Note", type="text"),
                entry_type="plot:template",
            )
        )
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        saved = self.client.put(
            f"/api/plot/templates/{clone['id']}",
            json={
                "title": clone["title"],
                "body": "# edited\n",
                "template": clone["template"],
                "metadata": {"note": "keep me"},
                "base_revision": clone["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        # Persisted to disk, not just echoed: a fresh read carries the field.
        reread = self.client.get(f"/api/plot/templates/{clone['id']}").json()
        self.assertEqual(reread["metadata"].get("note"), "keep me")

    def test_a_plotline_is_not_a_template(self) -> None:
        created = self.client.post("/api/plot/plotlines", json={"title": "A Thread"}).json()
        # Same `plot` kind + folder, but reading it as a template is refused.
        self.assertEqual(self.client.get(f"/api/plot/templates/{created['id']}").status_code, 404)
        # And templates never leak into the plotline list.
        plotline_ids = [e["id"] for e in self.client.get("/api/plot/plotlines").json()["entries"]]
        self.assertNotIn(_THREE_ACT, plotline_ids)

    def test_missing_template_404s(self) -> None:
        self.assertEqual(self.client.get("/api/plot/templates/builtin-plot-nope").status_code, 404)


class PlotKindRegistrationTests(_PlotTestCase):
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
        for concrete in ("plot:plotline", "plot:template", "plot:board", "plot:card"):
            self.assertEqual(
                schema.entry_types[concrete].parent,
                "plot:base",
                f"{concrete} must hang off plot:base so the whole-kind roster resolves",
            )

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
        spec = PlotTemplateSpec(
            slug=node_id,
            display_name=title,
            plot_points=[PlotTemplatePoint(id="p1", title="Beat 1", function_claim="Sets the frame.")],
        )
        self.service._write_plot_template_file(path, node_id, title, spec, "# Series Guide\n")
        return path

    def test_inherited_template_is_readable_and_read_only(self) -> None:
        self._write_ancestor_template(self.series, "plot_series_tpl", "Series Arc")
        got = self.service.read_plot_template("plot_series_tpl")
        self.assertEqual(got.title, "Series Arc")
        self.assertFalse(got.editable)  # inherited from an ancestor project → read-only
        self.assertTrue(got.source_layer_id)  # provenance surfaced
        self.assertEqual(len(got.template.plot_points), 1)

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
        self.assertEqual(len(clone.template.plot_points), 1)  # spec copied
        # The clone lives in this book, the ancestor original is left in place.
        self.assertTrue((self.root / "plot").is_dir())
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
