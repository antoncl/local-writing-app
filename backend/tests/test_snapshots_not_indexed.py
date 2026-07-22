"""`snapshots/` contributes nothing to the node index (ADR-0043, #395 slice 1).

The invariant: a snapshot store is *node-shaped* but is not an *indexed node*.
A witness is evidence about the graph, not a participant in it.

**This test landed before the store did, deliberately** (#395, ahead of slice
1), so slice 1 could not introduce a store that gets walked. The invariant holds
for free — the index walk enumerates `<layer>/<family folder>/*.md` from a fixed
family list, so a store at the project root is never reached. That is a property
of the current walk, not a decision anyone recorded in code, and the obvious
future edit breaks it silently: someone reaches for a recursive glob to pick up
nested files, and every snapshot's byte-copy joins the index carrying **its
source scene's id**. That is an id collision, which makes `_path_for_node_id`
non-deterministic and reference resolution ambiguous — the exact failure
ADR-0043's identity section exists to prevent.

The store is now real, so the fixture captures through the shipped API (#401)
rather than materialising the two files by hand, and asserts on the whole index
rather than on the walk's shape: nothing the index holds, and nothing the
staleness manifest fingerprints, may live under `snapshots/`.

Two halves, because they fail differently:

- **Cold build** catches a walk that reaches the store. This is the half that a
  future recursive glob trips.
- **Freshness** catches the other direction — ADR-0040 requires the manifest to
  skip the store too, or every capture invalidates the index and each save pays
  for a full rebuild.

The cold half must delete the cached index first. Without that it passes
vacuously: capture does not touch any fingerprinted file, so the cache is
correctly still fresh and the walk never runs at all.

**What the assertions are, and why, was decided by mutating the walk to a
recursive glob and keeping only the assertions that went red.**

The obvious assertion — no indexed path under `snapshots/` — is *not* sufficient
on its own, and the reason is worth knowing before someone simplifies this file.
A snapshot's byte-copy claims its source scene's id, `scenes/` sorts before
`snapshots/`, and collection keeps the first claimant of an id within a layer.
So the live scene wins, the intruder is dropped as a same-layer duplicate, and
`candidates` looks untouched. **The invariant is broken and the index looks
clean.**

Two things do see it, and they are the load-bearing assertions here:

- the **staleness manifest**, which fingerprints every file the walk reads;
- the **duplicate-id error** the collector records when two files at one layer
  claim an id — it names both paths, and one of them is under `snapshots/`.

The path assertions stay because they catch the shapes those two would not: a
store that ever wins the duplicate race, or a snapshot file carrying an id of
its own.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import Snapshot
from app.services.project.node_index_snapshot import SNAPSHOT_RELATIVE_PATH
from app.services.project_service import ProjectService

SCENE_ID = "scene-tide"


class SnapshotsAreNotIndexedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: on Windows `TemporaryDirectory()` returns the 8.3 short form
        # while the layer walk canonicalises (#356).
        self.root = Path(self.temp_dir.name).resolve() / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.scene_path = self._write_scene(SCENE_ID, "The Tide")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_scene(self, node_id: str, title: str) -> Path:
        (self.root / "scenes").mkdir(parents=True, exist_ok=True)
        path = self.root / "scenes" / f"{node_id}.md"
        self.service._write_markdown_with_front_matter(
            path,
            {"id": node_id, "title": title, "entry_type": "scene:scene", "metadata": {}},
            "The tide went out further than she had ever seen it.",
        )
        return path

    def _capture(self) -> Snapshot:
        """One real snapshot, through the shipped capture (#401 slice 1).

        This used to materialise the two files by hand, because the store did
        not exist yet. Now that it does, the fixture goes through the API — a
        hand-built store would keep passing after the real one moved.

        The `.md` is a **byte-for-byte copy**, front matter included, so it
        carries the source scene's id. That is what makes this a real probe
        rather than a decoy: a walk that reaches it does not merely gain a node,
        it gains a *second claimant to a live scene's id*.

        Explicit rather than automatic, so nothing is thinned away underneath a
        test that counts on six being there.
        """
        return self.service.capture_snapshot(SCENE_ID)

    def _cold_index(self):
        """Rebuild from disk, defeating the cached index (see the module note)."""
        cached = self.root / SNAPSHOT_RELATIVE_PATH
        cached.unlink(missing_ok=True)
        return self.service._build_node_index(self.root)

    def _under_snapshots(self, paths) -> list[str]:
        store = self.root / "snapshots"
        return [str(path) for path in paths if store in Path(path).resolve().parents]

    def test_a_cold_rebuild_ignores_the_snapshot_store(self) -> None:
        for _ in range(6):
            self._capture()

        index = self._cold_index()

        indexed = [entry.path for entries in index.candidates.values() for entry in entries]
        self.assertEqual(
            self._under_snapshots(indexed),
            [],
            "a node under snapshots/ reached the index — the store is being walked",
        )

    def test_a_snapshot_does_not_become_a_second_claimant_to_the_scene_id(self) -> None:
        self._capture()

        index = self._cold_index()

        candidates = index.candidates.get(SCENE_ID, [])
        self.assertEqual(
            [entry.path for entry in candidates],
            [self.scene_path],
            "the scene's id resolves to more than one file",
        )
        self.assertEqual(self.service._path_for_node_id(SCENE_ID, "scene"), self.scene_path)

    def test_the_index_has_the_same_members_before_and_after_six_captures(self) -> None:
        before = sorted(self._cold_index().by_id)

        for _ in range(6):
            self._capture()

        self.assertEqual(sorted(self._cold_index().by_id), before)

    def test_the_staleness_manifest_does_not_change_on_capture(self) -> None:
        layers = self.service.collect_layers(self.root, include_machine=True)
        before = self.service._build_index_manifest(layers)

        self._capture()

        after = self.service._build_index_manifest(layers)
        self.assertEqual(
            self._under_snapshots(after),
            [],
            "the manifest fingerprinted a file under snapshots/",
        )
        self.assertEqual(
            after,
            before,
            "capture changed the staleness manifest — every capture would invalidate the index",
        )

    def test_a_snapshot_contributes_no_reference_edges(self) -> None:
        snapshot = self._capture()

        index = self._cold_index()

        sources = {src for _layer, src in index.edges_by_layer_src}
        self.assertNotIn(snapshot.id, sources)

    def test_the_walk_never_reads_a_file_in_the_store(self) -> None:
        """The assertion that survives the duplicate mask (see the module note).

        A walked store collides with the live scene's id at the same layer,
        which the collector records as an error naming both files. So the store
        is visible in `errors` even when it is invisible in `candidates` — and
        an error mentioning it means the walk opened and parsed it.
        """
        self._capture()

        index = self._cold_index()

        mentions = [
            message
            for message in [*index.errors, *index.warnings]
            if "snapshots" in message
        ]
        self.assertEqual(mentions, [], "the index walk read a file under snapshots/")


if __name__ == "__main__":
    unittest.main()
