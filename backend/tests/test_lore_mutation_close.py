"""Interval-close markers (#59). A close marker `mutate:close;ref=<start>;id=..`
ends a start record at its prose point — the record is live iff `S ≤ P < C`
(close exclusive, ADR-0010). Proves out-of-order retraction, same-scene revert,
position-granular close, and the live-records (close picker) surface.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.models import CreateLoreEntryRequest
from app.runtime import service as svc


class IntervalCloseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Interval Close Tests")
        self.remus = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Remus", entry_type="lore:character")
        ).id
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str) -> str:
        scene_id = self.client.post("/api/scenes", json={"title": title}).json()["id"]
        saved = self.client.put(
            f"/api/scenes/{scene_id}", json={"title": title, "body": body}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    def _start(self, field: str, value: str, mid: str) -> str:
        return f"<!-- mutate:entity={self.remus};field={field};value={value};id={mid} -->"

    def _close(self, ref: str, mid: str) -> str:
        return f"<!-- mutate:close;ref={ref};id={mid} -->"

    # --- revert on close --------------------------------------------------

    def test_record_reverts_after_close_scene(self) -> None:
        # Werewolf: title changes at s2, closes at s3 → s2 sees the change, s3
        # (at/after the close) reverts to base.
        s1 = self._new_scene("One", "Calm.")
        s2 = self._new_scene("Two", "Dusk. " + self._start("title", "The%20Wolf", "w1"))
        s3 = self._new_scene("Three", "Dawn. " + self._close("w1", "wc1"))
        self.assertEqual(svc.effective_state(self.remus, s1), {})
        self.assertEqual(svc.effective_state(self.remus, s2), {"title": "The Wolf"})
        self.assertEqual(svc.effective_state(self.remus, s3), {})

    def test_out_of_order_close_leaves_siblings_live(self) -> None:
        # Two independent records; close only the first at s3.
        self._new_scene("One", "Calm.")
        self._new_scene(
            "Two", "Dusk. " + self._start("title", "The%20Wolf", "w1") + self._start("rank", "Beast", "w2")
        )
        s3 = self._new_scene("Three", "Dawn. " + self._close("w1", "wc1"))
        self.assertEqual(svc.effective_state(self.remus, s3), {"rank": "Beast"})

    def test_same_scene_start_and_close_is_closed_at_end(self) -> None:
        # Transform and revert within one scene → net base at end-of-scene.
        self._new_scene("One", "Calm.")
        s2 = self._new_scene(
            "Two", "Dusk. " + self._start("title", "The%20Wolf", "w1") + " Dawn. " + self._close("w1", "wc1")
        )
        self.assertEqual(svc.effective_state(self.remus, s2), {})

    # --- position-granular close within a scene ---------------------------

    def test_position_between_start_and_close_is_live(self) -> None:
        s2 = self._new_scene(
            "Two", "A " + self._start("title", "The%20Wolf", "w1") + " B " + self._close("w1", "wc1") + " C"
        )
        index = svc.build_mutations_index()
        start_off = index.by_entity[self.remus][0].offset
        close_off = index.closes_by_start["w1"][1]
        mid = (start_off + close_off) // 2
        self.assertEqual(
            svc.effective_state(self.remus, s2, position=mid, index=index), {"title": "The Wolf"}
        )
        self.assertEqual(
            svc.effective_state(self.remus, s2, position=close_off + 1, index=index), {}
        )

    def test_close_before_its_start_is_ignored(self) -> None:
        # A close positioned before its start marks an empty interval → ignored,
        # record stays open.
        s2 = self._new_scene(
            "Two", self._close("w1", "wc1") + " later " + self._start("title", "The%20Wolf", "w1")
        )
        self.assertEqual(svc.effective_state(self.remus, s2), {"title": "The Wolf"})

    # --- index + live picker ---------------------------------------------

    def test_version_changes_when_close_added(self) -> None:
        self._new_scene("One", "Calm.")
        self._new_scene("Two", self._start("title", "The%20Wolf", "w1"))
        before = svc.build_mutations_index().version
        self._new_scene("Three", self._close("w1", "wc1"))
        self.assertNotEqual(before, svc.build_mutations_index().version)

    def test_live_mutations_excludes_closed(self) -> None:
        self._new_scene("One", "Calm.")
        s2 = self._new_scene("Two", self._start("title", "The%20Wolf", "w1"))
        s3 = self._new_scene("Three", "Dawn. " + self._close("w1", "wc1"))
        # Open at s2, closed by s3.
        self.assertEqual(
            [m.marker_id for m in svc.live_mutations(self.remus, s2).items], ["w1"]
        )
        self.assertEqual(svc.live_mutations(self.remus, s3).items, [])


if __name__ == "__main__":
    unittest.main()
