"""Node-scoped snapshots for the **plot** kind (ADR-0087 S5b, #1992).

Split out of `test_node_snapshots.py` (the file-size guard). Plot is the last kind
in the rollout, and the one whose "restore healer" turned out to be a misread: a
plot node byte-restores like lore/tag/prompt and heals nothing out of its own
file. Its `beat_links`/`causal_links` are denormalised onto the card and healed on
READ; the plot board is an opaque layout recomputed from live nodes — so there is
no second persisted representation to reconcile, and the byte-write plus the index
re-fold is the whole restore. These tests pin exactly that: byte-exact restore, a
dangling link left for the read path to heal (never rewritten on restore), the
delete-store reap on both plot delete paths, and the inherited/Library refusals.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain, make_project_folder
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateCardRequest, CreatePlotTemplateRequest

_THREE_ACT_TEMPLATE = "builtin-plot-three-act-story-arc"


class PlotCardSnapshotRoundTripTests(unittest.TestCase):
    """One plot card through the shipped node routes (ADR-0087 S5b). A plot node
    byte-restores like lore/tag and heals nothing out of its own file: its
    beat_links/causal_links are denormalised onto the card and healed on READ, and
    the plot board is recomputed from live nodes — so the byte-write plus the index
    re-fold is the whole restore, with no owned-file rewrite (§4)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Plot Snapshot Tests")
        self.client = TestClient(app)
        self.card_id = self.service.create_card(CreateCardRequest(title="A Card")).id

    def _card_path(self) -> Path:
        return self.service._path_for_node_id(self.card_id, "plot")

    def _store_dir(self) -> Path:
        return self.root / "snapshots" / self.card_id

    def _save_card(self, *, title: str, metadata: dict) -> None:
        saved = self.client.put(
            f"/api/plot/cards/{self.card_id}",
            json={"title": title, "body": "", "metadata": metadata},
        )
        self.assertEqual(saved.status_code, 200, saved.text)

    def _card_links(self) -> list:
        got = self.client.get(f"/api/plot/cards/{self.card_id}")
        self.assertEqual(got.status_code, 200, got.text)
        return got.json()["metadata"].get("beat_links", [])

    def _linked_plotline(self) -> tuple[str, str]:
        plotline = self.client.post(
            f"/api/plot/templates/{_THREE_ACT_TEMPLATE}/instantiate"
        ).json()
        beat_id = plotline["metadata"]["instance_beats"][0]["id"]
        return plotline["id"], beat_id

    def _capture(self) -> dict:
        response = self.client.post(f"/api/nodes/{self.card_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_capture_writes_the_store_under_the_open_project(self) -> None:
        snapshot = self._capture()
        store = self._store_dir()
        self.assertTrue(store.is_dir(), "the plot card store was not created")
        self.assertTrue((store / f"{snapshot['id']}.md").exists())
        self.assertEqual(snapshot["snapshot_of"], self.card_id)

    def test_byte_restore_reverts_the_card(self) -> None:
        snapshot = self._capture()
        original = self._card_path().read_bytes()
        self._save_card(title="A Wholly Different Title", metadata={})
        self.assertNotEqual(self._card_path().read_bytes(), original)
        restored = self.client.post(
            f"/api/nodes/{self.card_id}/snapshots/{snapshot['id']}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["title"], "A Card")
        self.assertEqual(self._card_path().read_bytes(), original)

    def test_a_card_capture_writes_no_witness(self) -> None:
        snapshot = self._capture()
        witness = self.service.read_snapshot_witness(self.root, self.card_id, snapshot["id"])
        self.assertIsNone(witness)

    def test_pin_and_delete_over_the_node_route(self) -> None:
        kept = self._capture()
        self._save_card(title="A Second Version", metadata={})
        self.client.post(f"/api/nodes/{self.card_id}/snapshots/{kept['id']}/restore")
        listed = self.client.get(f"/api/nodes/{self.card_id}/snapshots").json()["snapshots"]
        thinned = [s for s in listed if s["retention"] == "thinned"]
        self.assertTrue(thinned, "restore did not leave a thinned pre-restore snapshot")
        pinned = self.client.post(
            f"/api/nodes/{self.card_id}/snapshots/{thinned[0]['id']}/pin"
        )
        self.assertEqual(pinned.status_code, 200, pinned.text)
        self.assertEqual(pinned.json()["retention"], "kept")
        deleted = self.client.delete(f"/api/nodes/{self.card_id}/snapshots/{kept['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_deleting_the_card_removes_its_snapshot_store(self) -> None:
        self._capture()
        self.assertTrue(self._store_dir().is_dir())
        deleted = self.client.delete(f"/api/plot/cards/{self.card_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(self._store_dir().exists())

    def test_deleting_an_absent_card_404s_with_the_card_noun(self) -> None:
        # The reap must not pre-empt the delete path's noun-correct 404 for a
        # truly-absent node (S5a review): the store key is derived from the path
        # `_plot_node_path` resolves, so a missing card still 404s as "Card …", not
        # the shared resolver's fixed "Plotline" label.
        missing = self.client.delete("/api/plot/cards/plot_missing_xyz")
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertIn("Card", missing.json()["detail"])
        self.assertNotIn("Plotline", missing.json()["detail"])

    def test_restore_of_a_card_with_a_live_link_is_byte_exact(self) -> None:
        plotline_id, beat_id = self._linked_plotline()
        self._save_card(
            title="A Card",
            metadata={"beat_links": [{"plotline": plotline_id, "beat_id": beat_id}]},
        )
        snapshot = self._capture()
        frozen = self._card_path().read_bytes()
        self.assertIn(beat_id, frozen.decode("utf-8"))
        # Mutate the card, then restore — the frozen link comes back byte-for-byte.
        self._save_card(title="Renamed", metadata={})
        self.assertNotEqual(self._card_path().read_bytes(), frozen)
        restored = self.client.post(
            f"/api/nodes/{self.card_id}/snapshots/{snapshot['id']}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self._card_path().read_bytes(), frozen)
        self.assertEqual(
            self._card_links(), [{"plotline": plotline_id, "beat_id": beat_id}]
        )

    def test_restore_leaves_a_dangling_link_for_read_to_heal(self) -> None:
        # The design decision made executable: plot restore is byte-exact and does
        # NOT rewrite the card's own file. A link that dangled since the snapshot
        # comes back on disk — exactly as ordinary editing leaves a stale link until
        # the next save — while the read path heals it away for display. (A restore
        # that healed on disk would break the byte-exact guarantee every other kind
        # keeps and would be the only kind to rewrite the restored node's own file.)
        plotline_id, beat_id = self._linked_plotline()
        self._save_card(
            title="Renamed",
            metadata={"beat_links": [{"plotline": plotline_id, "beat_id": beat_id}]},
        )
        snapshot = self._capture()
        frozen = self._card_path().read_bytes()
        # Delete the plotline the link points at (this never rewrites the card —
        # beat_links are plain text the reference purge does not touch)…
        deleted = self.client.delete(f"/api/plot/plotlines/{plotline_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self._card_links(), [], "read should heal the now-dangling link")
        # …restore is byte-exact, so the dangling link is back on disk…
        restored = self.client.post(
            f"/api/nodes/{self.card_id}/snapshots/{snapshot['id']}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self._card_path().read_bytes(), frozen)
        self.assertIn(beat_id, self._card_path().read_bytes().decode("utf-8"))
        # …and the read path still heals it away — the restore itself healed nothing.
        self.assertEqual(self._card_links(), [])


class PlotPlotlineAndTemplateSnapshotTests(unittest.TestCase):
    """The rest of the plot family through the node routes (ADR-0087 S5b): a
    plotline reaches the store and reaps through the shared folder-node delete; an
    owned template reaps through its own delete path; and an inherited built-in
    Library template stays refused for both snapshot and delete."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Plot Family Snapshot Tests")
        self.client = TestClient(app)

    def _store_dir(self, node_id: str) -> Path:
        return self.root / "snapshots" / node_id

    def test_a_plotline_snapshots_and_its_delete_reaps_the_store(self) -> None:
        plotline_id = self.client.post(
            f"/api/plot/templates/{_THREE_ACT_TEMPLATE}/instantiate"
        ).json()["id"]
        captured = self.client.post(f"/api/nodes/{plotline_id}/snapshots")
        self.assertEqual(captured.status_code, 200, captured.text)
        self.assertTrue(self._store_dir(plotline_id).is_dir())
        deleted = self.client.delete(f"/api/plot/plotlines/{plotline_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(self._store_dir(plotline_id).exists())

    def test_an_owned_template_snapshots_and_its_delete_reaps_the_store(self) -> None:
        template_id = self.service.create_plot_template(
            CreatePlotTemplateRequest(title="My Template")
        ).id
        captured = self.client.post(f"/api/nodes/{template_id}/snapshots")
        self.assertEqual(captured.status_code, 200, captured.text)
        self.assertTrue(self._store_dir(template_id).is_dir())
        # The template delete is a SEPARATE path from the folder-node delete — it
        # must reap too, or it leaks the store.
        deleted = self.client.delete(f"/api/plot/templates/{template_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(self._store_dir(template_id).exists())

    def test_a_builtin_library_template_snapshot_is_refused(self) -> None:
        # A built-in template is a read-only Library node; the writability floor
        # refuses snapshotting it (fork-only), and nothing is written.
        refused = self.client.post(f"/api/nodes/{_THREE_ACT_TEMPLATE}/snapshots")
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertFalse((self.root / "snapshots" / _THREE_ACT_TEMPLATE).exists())

    def test_deleting_a_builtin_library_template_is_refused(self) -> None:
        refused = self.client.delete(f"/api/plot/templates/{_THREE_ACT_TEMPLATE}")
        self.assertEqual(refused.status_code, 409, refused.text)


class InheritedPlotSnapshotTests(unittest.TestCase):
    """A plot node owned by an ancestor PROJECT layer stays refused for snapshots:
    plot is book-local for writes, and a base restore byte-writes the owning
    layer's file, so it must never target an ancestor's plot canon. Plot is
    deliberately kept out of ANCESTOR_RESTORE_SAFE_KINDS for exactly this."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.book = self.universe / "book"
        self.service = open_test_project(self.book, "Book")
        make_project_folder(self.service, self.universe, "Universe")
        declare_full_chain(self.service, self.book, self.base)
        self.client = TestClient(app)
        # Author a plot card owned by the ancestor (universe) directly on disk.
        self.card_id = "plot_ancestorcard"
        (self.universe / "plot").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.universe / "plot" / f"{self.card_id}.md",
            self.card_id, "Ancestor Card", "plot:card", {}, "",
            omit_empty_metadata=True,
        )

    def test_snapshotting_an_inherited_plot_card_is_refused(self) -> None:
        refused = self.client.post(f"/api/nodes/{self.card_id}/snapshots")
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertFalse((self.universe / "snapshots" / self.card_id).exists())
        self.assertFalse((self.book / "snapshots" / self.card_id).exists())


if __name__ == "__main__":
    unittest.main()
