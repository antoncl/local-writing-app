"""The persisted node index and its staleness manifest (#306).

Two things have to hold, and the second is the one that can hurt. The snapshot
must actually be *used* — a test suite that never hits the cache passes whether
or not the cache works — and it must be discarded whenever anything the build
read has moved. Under ADR-0039 the index materializes ancestor-owned nodes into
the open project, so serving a stale one is a wrong answer, not a slow one.

Every rebuild path is therefore pinned from the outside: change a file, delete
one, add one, make a layer appear, corrupt the payload, bump the format. The
counting spy is what distinguishes "served from disk" from "rebuilt and happened
to agree".
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.project import node_index_snapshot as snapshot
from app.services.project_service import ProjectService


class SnapshotTestCase(unittest.TestCase):
    """A book under a universe under the configured base folder."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: on Windows `TemporaryDirectory()` hands back the 8.3 short
        # form while the layer walk canonicalises (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.root = self.universe / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        self._set_base_folder(self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set_base_folder(self, folder: Path) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(folder)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def _write_lore(self, folder: Path, node_id: str, title: str, *, refs: list[str] | None = None) -> Path:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        path = folder / "lore" / f"{node_id}.md"
        self.service._write_markdown_with_front_matter(
            path,
            {
                "id": node_id,
                "title": title,
                "entry_type": "lore:character",
                "metadata": {"related_entries": refs} if refs else {},
            },
            "Body.",
        )
        return path

    def _count_collections(self) -> list[int]:
        """Install a spy on the per-layer collector; returns a one-slot counter.

        Zero calls after a build is the only direct evidence that an index came
        off disk rather than out of a re-parse.
        """
        calls = [0]
        original = self.service._collect_layer_entries

        def counting(**kwargs: object) -> None:
            calls[0] += 1
            original(**kwargs)

        # Instance attribute shadows the mixin's method, so `self._service.…`
        # inside the builder resolves to this.
        self.service._collect_layer_entries = counting  # type: ignore[method-assign]
        return calls

    def _snapshot_payload(self) -> dict:
        return json.loads(snapshot.snapshot_path(self.root).read_text(encoding="utf-8"))

    def _write_payload(self, payload: dict) -> None:
        snapshot.snapshot_path(self.root).write_text(json.dumps(payload), encoding="utf-8")


class SnapshotIsUsedTests(SnapshotTestCase):
    def test_first_build_writes_a_snapshot(self) -> None:
        self.service._build_node_index(self.root)
        self.assertTrue(snapshot.snapshot_path(self.root).exists())

    def test_second_build_reads_it_instead_of_reparsing(self) -> None:
        self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)
        calls = self._count_collections()
        self.service._build_node_index(self.root)
        self.assertEqual(calls[0], 0)

    def test_rehydrated_index_matches_a_cold_build(self) -> None:
        """The whole contract in one assertion: same winners, same shadowed
        candidates in the same order, same edges both ways, same diagnostics."""
        self.service.create_project(self.universe, "Honorverse")
        self.service.open_project(self.root)
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.base, "seren", "Seren (base)")
        self._write_lore(self.root, "seren", "Seren (book)", refs=["harrington"])
        self._write_lore(self.universe, "harrington", "Harrington")

        cold = self.service._build_node_index(self.root)
        warm = self.service._build_node_index(self.root)

        self.assertEqual(warm.by_id.keys(), cold.by_id.keys())
        self.assertEqual(
            {node_id: [(e.title, e.source_layer_label) for e in entries] for node_id, entries in warm.candidates.items()},
            {node_id: [(e.title, e.source_layer_label) for e in entries] for node_id, entries in cold.candidates.items()},
        )
        self.assertEqual(warm.edges_by_layer_src, cold.edges_by_layer_src)
        self.assertEqual(warm.edges_by_src, cold.edges_by_src)
        self.assertEqual(warm.edges_by_dst, cold.edges_by_dst)
        self.assertEqual(warm.warnings, cold.warnings)
        self.assertEqual(warm.errors, cold.errors)

    def test_shadow_warnings_are_not_doubled(self) -> None:
        """`resolve()` derives them, so persisting them would emit each twice —
        and `validate_project` shows warnings to the user verbatim."""
        self.service.create_project(self.universe, "Honorverse")
        self.service.open_project(self.root)
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")

        cold = self.service._build_node_index(self.root)
        warm = self.service._build_node_index(self.root)
        shadow = [w for w in warm.warnings if "shadows" in w]

        self.assertEqual(len(shadow), 1)
        self.assertEqual(warm.warnings, cold.warnings)

    def test_candidate_order_survives_three_layers(self) -> None:
        """Innermost first, still. Entries are stored grouped by id, so replaying
        them through `add` — which front-inserts — inverts each group unless the
        group is reversed on the way in."""
        self.service.create_project(self.universe, "Honorverse")
        self.service.open_project(self.root)
        self._write_lore(self.base, "seren", "Seren (base)")
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")

        self.service._build_node_index(self.root)
        warm = self.service._build_node_index(self.root)

        self.assertEqual(
            [entry.title for entry in warm.candidates["seren"]],
            ["Seren (book)", "Seren (universe)", "Seren (base)"],
        )
        self.assertEqual(warm.by_id["seren"].title, "Seren (book)")


class StalenessTests(SnapshotTestCase):
    def _rebuilt(self) -> bool:
        calls = self._count_collections()
        self.service._build_node_index(self.root)
        rebuilt = calls[0] > 0
        self.service._collect_layer_entries = ProjectService._collect_layer_entries.__get__(self.service)
        return rebuilt

    def test_edited_file_rebuilds(self) -> None:
        path = self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)
        self._write_lore(self.root, "seren", "Seren, renamed")
        self.assertTrue(path.exists())
        self.assertTrue(self._rebuilt())

    def test_deleted_file_rebuilds(self) -> None:
        path = self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)
        path.unlink()
        self.assertTrue(self._rebuilt())

    def test_added_file_rebuilds(self) -> None:
        """The case a stat-sweep over known paths cannot see: a file dropped
        into an ancestor's `lore/` from Explorer, or arriving via `git pull`."""
        self.service._build_node_index(self.root)
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self.assertTrue(self._rebuilt())

    def test_untouched_project_does_not_rebuild(self) -> None:
        self._write_lore(self.root, "seren", "Seren")
        self.service._build_node_index(self.root)
        self.assertFalse(self._rebuilt())

    def test_schema_file_appearing_at_a_layer_rebuilds(self) -> None:
        """It carries no id and is not a node, but it decides what every node's
        fields mean — and therefore which edges exist."""
        self.service._build_node_index(self.root)
        (self.universe / "metadata.schema.yaml").write_text("version: 1\n", encoding="utf-8")
        self.assertTrue(self._rebuilt())

    def test_schema_file_appearing_ABOVE_the_chain_rebuilds(self) -> None:
        """The case no per-file fingerprint can see.

        A stray `metadata.schema.yaml` above the outer bound *lengthens* the
        chain (`_metadata_schema_base_folder`'s widening, #337): no recorded
        file changes, no indexed folder gains one, and yet the index gains a
        whole layer. What catches it is the layer-chain comparison — the walk's
        output, not its inputs — which is why the snapshot stores the folders
        the walk yielded.
        """
        self._set_base_folder(self.universe)
        before = self.service.collect_layers(self.root, include_machine=True)
        self.service._build_node_index(self.root)
        (self.base / "metadata.schema.yaml").write_text("version: 1\n", encoding="utf-8")
        # Pin the premise: if the widening ever stops lengthening the chain this
        # test would pass for the wrong reason, having asserted nothing.
        after = self.service.collect_layers(self.root, include_machine=True)
        self.assertGreater(len(after), len(before))
        self.assertTrue(self._rebuilt())

    def test_a_layer_appearing_rebuilds(self) -> None:
        """Same mechanism, stated directly: the chain the walk yields is part of
        the snapshot's identity, not merely of its content."""
        self.service._build_node_index(self.root)
        self.service.create_project(self.universe, "Honorverse")
        self.service.open_project(self.root)
        self.assertTrue(self._rebuilt())

    def test_project_manifest_edit_rebuilds(self) -> None:
        """`project.yaml` is what routes the extent rule, so it is an input to
        the chain's shape and not only to a layer's content."""
        self.service._build_node_index(self.root)
        self._set_base_folder(self.universe)
        self.assertTrue(self._rebuilt())


class SnapshotIntegrityTests(SnapshotTestCase):
    def _rebuilds(self) -> bool:
        calls = self._count_collections()
        self.service._build_node_index(self.root)
        rebuilt = calls[0] > 0
        self.service._collect_layer_entries = ProjectService._collect_layer_entries.__get__(self.service)
        return rebuilt

    def test_corrupt_payload_rebuilds(self) -> None:
        self.service._build_node_index(self.root)
        snapshot.snapshot_path(self.root).write_text("{not json", encoding="utf-8")
        self.assertTrue(self._rebuilds())

    def test_wrong_shape_rebuilds(self) -> None:
        """Parses, passes every header check, and is still not what we wrote."""
        self.service._build_node_index(self.root)
        payload = self._snapshot_payload()
        payload["entries"] = [{"id": "seren"}]
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_format_version_mismatch_rebuilds_and_unlinks(self) -> None:
        self.service._build_node_index(self.root)
        payload = self._snapshot_payload()
        payload["format_version"] = snapshot.SNAPSHOT_FORMAT_VERSION + 1
        self._write_payload(payload)
        calls = self._count_collections()
        self.service._build_node_index(self.root)
        self.assertGreater(calls[0], 0)
        self.assertEqual(self._snapshot_payload()["format_version"], snapshot.SNAPSHOT_FORMAT_VERSION)

    def test_copied_project_folder_rebuilds(self) -> None:
        """Users copy book folders. Without the `root` key the copy reads the
        original's cache — every path in it pointing at the original."""
        self.service._build_node_index(self.root)
        payload = self._snapshot_payload()
        payload["root"] = str(self.universe / "book99")
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_tampered_layer_chain_rebuilds(self) -> None:
        """Entries name their layer by **position** in the walk, so a payload
        whose chain differs cannot be interpreted at all — the index would be
        read off the wrong folders or off the end of the list.

        In practice a real chain change also moves the manifest (every layer
        contributes recorded keys, present or absent), so this guard is
        unreachable from the outside. It is pinned here on the payload directly
        because it guards the interpretability of the data structure, not a
        user behaviour: without it, "positions still mean what they meant" is an
        assumption rather than a check.
        """
        self.service._build_node_index(self.root)
        payload = self._snapshot_payload()
        payload["layer_folders"] = [*payload["layer_folders"], str(self.root / "invented")]
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_layer_ids_are_derived_not_trusted(self) -> None:
        """`layers.py` states layer ids are never persisted — a path hash
        survives neither a moved folder nor a re-resolved symlink. The payload
        must therefore not carry one to be believed."""
        self.service._build_node_index(self.root)
        payload = self._snapshot_payload()
        blob = json.dumps(payload)
        for layer in self.service.collect_layers(self.root, include_machine=True):
            self.assertNotIn(layer.id, blob)

    def test_unwritable_cache_does_not_break_the_build(self) -> None:
        """The snapshot is derived; a project folder we cannot write must cost
        the next open its speed and nothing else."""
        original = self.service._atomic_write

        def failing(path: Path, text: str) -> None:
            if path == snapshot.snapshot_path(self.root):
                raise OSError("read-only")
            original(path, text)

        self.service._atomic_write = failing  # type: ignore[method-assign]
        self._write_lore(self.root, "seren", "Seren")
        index = self.service._build_node_index(self.root)
        self.assertEqual(index.by_id["seren"].title, "Seren")


class ManifestUnitTests(unittest.TestCase):
    def test_absence_round_trips_as_a_key(self) -> None:
        """A recorded absence is not the same as an unrecorded path: one means
        "there was no schema file here", the other means "we never looked"."""
        stored = {"a.md": (1, 2), "schema.yaml": None}
        self.assertEqual(snapshot.diff_manifests(stored, dict(stored)), [])
        self.assertEqual(snapshot.diff_manifests(stored, {"a.md": (1, 2)}), ["schema.yaml"])
        self.assertEqual(
            snapshot.diff_manifests(stored, {"a.md": (1, 2), "schema.yaml": (9, 9)}),
            ["schema.yaml"],
        )

    def test_an_older_mtime_is_still_a_change(self) -> None:
        """Recency is the wrong comparison — a file restored from a backup or
        extracted from an archive lands changed content with an older stamp."""
        self.assertEqual(snapshot.diff_manifests({"a.md": (500, 10)}, {"a.md": (100, 10)}), ["a.md"])

    def test_same_mtime_different_size_is_a_change(self) -> None:
        self.assertEqual(snapshot.diff_manifests({"a.md": (500, 10)}, {"a.md": (500, 11)}), ["a.md"])

    def test_missing_file_fingerprints_as_absent(self) -> None:
        self.assertIsNone(snapshot.fingerprint_for(Path("nope") / "missing.md"))


if __name__ == "__main__":
    unittest.main()
