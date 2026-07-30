"""Backend tests for the `plot` kind (ADR-0048 S4a).

Two node types under the new kind: plotlines (`plot:plotline`, a flat layered
entry) and the board (`plot:board`, a per-project layout singleton). These prove
the wiring end-to-end through FastAPI plus the registration facts (family,
schema, folder, whitelist) and the two design invariants — a plotline is indexed
and reference-bearing, while the board is a directly-addressed singleton kept out
of the node index so an ancestor's board can never leak in.
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
    CreatePlotlineRequest,
    EntryTypeDefinition,
    SavePlotlineRequest,
    UpsertMetadataEntryTypeRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.references import NODE_FAMILIES, REFERENCE_BEARING_KINDS
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


class PlotKindRegistrationTests(_PlotTestCase):
    def test_plot_family_registered_and_reference_bearing(self) -> None:
        self.assertIn("plot", {family.kind for family in NODE_FAMILIES})
        self.assertIn("plot", REFERENCE_BEARING_KINDS)

    def test_default_schema_defines_plot_types(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertIn("plot:plotline", schema.entry_types)
        self.assertIn("plot:board", schema.entry_types)
        self.assertEqual(schema.entry_types["plot:plotline"].kind, "plot")

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


if __name__ == "__main__":
    unittest.main()
