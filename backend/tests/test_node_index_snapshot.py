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

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.services.project import node_index_snapshot as snapshot
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate
from app.services.project_service import ProjectService


class SnapshotTestCase(unittest.TestCase):
    """A book under a universe under the configured base folder."""

    def _open_index(self) -> object:
        """Build the index as a *fresh open* would (#392).

        This suite pins the on-disk snapshot layer — staleness detection,
        integrity, patch-vs-rebuild — which runs only on a fresh open, when the
        in-memory memo is empty. Each build here models such an open, so it drops
        the memo first. The memo's own behaviour (a warm hit does no disk work;
        an external edit mid-session is not seen until the next open) is pinned
        separately, in test_node_index_memo.py.
        """
        node_index_gate.invalidate()
        return self.service._build_node_index(self.root)

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: on Windows `TemporaryDirectory()` hands back the 8.3 short
        # form while the layer walk canonicalises (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.root = self.universe / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self._set_base_folder(self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set_base_folder(self, folder: Path) -> None:
        declare_full_chain(self.service, self.root, folder)

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
        self._open_index()
        self.assertTrue(snapshot.snapshot_path(self.root).exists())

    def test_second_build_reads_it_instead_of_reparsing(self) -> None:
        self._write_lore(self.root, "seren", "Seren")
        self._open_index()
        calls = self._count_collections()
        self._open_index()
        self.assertEqual(calls[0], 0)

    def test_rehydrated_index_matches_a_cold_build(self) -> None:
        """The whole contract in one assertion: same winners, same shadowed
        candidates in the same order, same edges both ways, same diagnostics."""
        self.service = ProjectService.created_at(self.universe, "Honorverse")
        self.service = ProjectService.opened_at(self.root)
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.base, "seren", "Seren (base)")
        self._write_lore(self.root, "seren", "Seren (book)", refs=["harrington"])
        self._write_lore(self.universe, "harrington", "Harrington")

        cold = self._open_index()
        warm = self._open_index()

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
        self.service = ProjectService.created_at(self.universe, "Honorverse")
        self.service = ProjectService.opened_at(self.root)
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")

        cold = self._open_index()
        warm = self._open_index()
        shadow = [w for w in warm.warnings if "shadows" in w]

        self.assertEqual(len(shadow), 1)
        self.assertEqual(warm.warnings, cold.warnings)

    def test_candidate_order_survives_three_layers(self) -> None:
        """Innermost first, still. Entries are stored grouped by id, so replaying
        them through `add` — which front-inserts — inverts each group unless the
        group is reversed on the way in."""
        self.service = ProjectService.created_at(self.universe, "Honorverse")
        self.service = ProjectService.opened_at(self.root)
        self._write_lore(self.base, "seren", "Seren (base)")
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self._write_lore(self.root, "seren", "Seren (book)")

        self._open_index()
        warm = self._open_index()

        self.assertEqual(
            [entry.title for entry in warm.candidates["seren"]],
            ["Seren (book)", "Seren (universe)", "Seren (base)"],
        )
        self.assertEqual(warm.by_id["seren"].title, "Seren (book)")


class StalenessTests(SnapshotTestCase):
    """A changed input must never be served from a stale snapshot.

    ⚠ These assert **the change is visible**, never *how* it became visible.
    Whether a full rebuild or #307's incremental patch produced it is an
    implementation choice; the first version of these tests counted
    `_collect_layer_entries` calls and duly broke when the patch started
    collecting single files instead of folders — measuring the mechanism, not
    the guarantee. The patch/rebuild split is asserted where it *is* the point,
    in `test_node_index_patch.py`.
    """

    def _rebuilt(self) -> bool:
        calls = self._count_collections()
        self._open_index()
        rebuilt = calls[0] > 0
        self.service._collect_layer_entries = ProjectService._collect_layer_entries.__get__(self.service)
        return rebuilt

    def test_edited_file_is_not_served_from_the_snapshot(self) -> None:
        path = self._write_lore(self.root, "seren", "Seren")
        self._open_index()
        self._write_lore(self.root, "seren", "Seren, renamed")
        self.assertTrue(path.exists())
        self.assertEqual(self._open_index().by_id["seren"].title, "Seren, renamed")

    def test_deleted_file_is_not_served_from_the_snapshot(self) -> None:
        """A delete re-collects nothing — there is no file to parse — so this
        asserts the observable outcome rather than the mechanism."""
        path = self._write_lore(self.root, "seren", "Seren")
        self._open_index()
        path.unlink()
        self.assertNotIn("seren", self._open_index().by_id)

    def test_added_file_is_not_served_from_the_snapshot(self) -> None:
        """The case a stat-sweep over known paths cannot see: a file dropped
        into an ancestor's `lore/` from Explorer, or arriving via `git pull`."""
        self._open_index()
        self._write_lore(self.universe, "seren", "Seren (universe)")
        self.assertIn("seren", self._open_index().by_id)

    def test_untouched_project_does_not_rebuild(self) -> None:
        self._write_lore(self.root, "seren", "Seren")
        self._open_index()
        self.assertFalse(self._rebuilt())

    def test_schema_file_appearing_at_a_layer_rebuilds(self) -> None:
        """It carries no id and is not a node, but it decides what every node's
        fields mean — and therefore which edges exist."""
        self._open_index()
        (self.universe / "metadata.schema.yaml").write_text("version: 1\n", encoding="utf-8")
        self.assertTrue(self._rebuilt())

    def test_schema_file_appearing_ABOVE_the_chain_changes_nothing(self) -> None:
        """The inverse of what this test asserted before #337.

        A stray `metadata.schema.yaml` above the outer bound used to *lengthen*
        the chain — no recorded file changed, no indexed folder gained one, and
        yet the index gained a whole layer, so the snapshot had to rebuild. With
        the widening gone the walk stops where the setting says, so the file is
        simply outside the project's world: the chain is unchanged and there is
        nothing to rebuild.

        The mechanism that caught the old case is still worth having, and
        `test_a_layer_appearing_rebuilds` below is what exercises it now — a
        chain that grows for a legitimate reason still invalidates the snapshot.
        """
        self._set_base_folder(self.universe)
        before = self.service.collect_layers(self.root, include_machine=True)
        self._open_index()
        (self.base / "metadata.schema.yaml").write_text("version: 1\n", encoding="utf-8")
        after = self.service.collect_layers(self.root, include_machine=True)

        self.assertEqual(len(after), len(before))
        self.assertFalse(self._rebuilt())

    def test_a_layer_appearing_rebuilds(self) -> None:
        """Same mechanism, stated directly: the chain the walk yields is part of
        the snapshot's identity, not merely of its content."""
        self._open_index()
        self.service = ProjectService.created_at(self.universe, "Honorverse")
        self.service = ProjectService.opened_at(self.root)
        self.assertTrue(self._rebuilt())

    def test_project_manifest_edit_rebuilds(self) -> None:
        """`project.yaml` is what routes the extent rule, so it is an input to
        the chain's shape and not only to a layer's content."""
        self._open_index()
        self._set_base_folder(self.universe)
        self.assertTrue(self._rebuilt())


class SnapshotIntegrityTests(SnapshotTestCase):
    def _rebuilds(self) -> bool:
        calls = self._count_collections()
        self._open_index()
        rebuilt = calls[0] > 0
        self.service._collect_layer_entries = ProjectService._collect_layer_entries.__get__(self.service)
        return rebuilt

    def test_corrupt_payload_rebuilds(self) -> None:
        self._open_index()
        snapshot.snapshot_path(self.root).write_text("{not json", encoding="utf-8")
        self.assertTrue(self._rebuilds())

    def test_undecodable_bytes_rebuild_rather_than_raising(self) -> None:
        """A snapshot truncated by a power cut is *bytes* that will not decode,
        which `read_text` raises before any JSON handling sees it. Uncaught it
        escapes the build and 500s every endpoint that touches the index —
        a derived, self-healing file making the project unopenable."""
        self._open_index()
        snapshot.snapshot_path(self.root).write_bytes(b'{"format_version": 1, \xff\xfe\x00 truncated')
        self.assertTrue(self._rebuilds())

    def test_unparseable_manifest_value_rebuilds_rather_than_raising(self) -> None:
        """The manifest is payload *body*, so it must be decoded inside the same
        guard as the rest. Decoded above it, one non-numeric fingerprint raised
        straight out of the build — 500ing every endpoint that touches the
        index, for a file that exists to be thrown away."""
        self._open_index()
        payload = self._snapshot_payload()
        payload["manifest"][sorted(payload["manifest"])[0]] = ["notanint", "alsonot"]
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_warnings_of_the_wrong_shape_rebuild(self) -> None:
        """`list("boom")` is four warnings, one per character — and
        `validate_project` shows warnings to the user verbatim."""
        self._open_index()
        payload = self._snapshot_payload()
        payload["warnings"] = "boom"
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_negative_layer_position_rebuilds(self) -> None:
        """`layers[-1]` is not an error in Python, so a negative position would
        silently re-stamp entries onto the innermost layer — a wrong
        `source_layer` on a node, which is what ADR-0042's layer picker reads."""
        self._write_lore(self.root, "seren", "Seren")
        self._open_index()
        payload = self._snapshot_payload()
        payload["entries"][0]["layer"] = -1
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_wrong_shape_rebuilds(self) -> None:
        """Parses, passes every header check, and is still not what we wrote."""
        self._open_index()
        payload = self._snapshot_payload()
        payload["entries"] = [{"id": "seren"}]
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_format_version_mismatch_rebuilds_and_unlinks(self) -> None:
        self._open_index()
        payload = self._snapshot_payload()
        payload["format_version"] = snapshot.SNAPSHOT_FORMAT_VERSION + 1
        self._write_payload(payload)
        calls = self._count_collections()
        self._open_index()
        self.assertGreater(calls[0], 0)
        self.assertEqual(self._snapshot_payload()["format_version"], snapshot.SNAPSHOT_FORMAT_VERSION)

    def test_copied_project_folder_rebuilds(self) -> None:
        """Users copy book folders. Without the `root` key the copy reads the
        original's cache — every path in it pointing at the original."""
        self._open_index()
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
        self._open_index()
        payload = self._snapshot_payload()
        payload["layer_folders"] = [*payload["layer_folders"], str(self.root / "invented")]
        self._write_payload(payload)
        self.assertTrue(self._rebuilds())

    def test_layer_ids_are_derived_not_trusted(self) -> None:
        """`layers.py` states layer ids are never persisted — a path hash
        survives neither a moved folder nor a re-resolved symlink. The payload
        must therefore not carry one to be believed."""
        self._open_index()
        payload = self._snapshot_payload()
        blob = json.dumps(payload)
        for layer in self.service.collect_layers(self.root, include_machine=True):
            self.assertNotIn(layer.id, blob)

    def test_stale_snapshot_under_an_open_handle_does_not_break_the_build(self) -> None:
        """The read path must not delete anything.

        An earlier version unlinked on a version mismatch — the branch that runs
        for *every* project on the first open after a format bump. On Windows one
        open handle (a scanner, a backup agent, a second instance) turns that
        into a `PermissionError` raised out of the read path, 500ing every index
        consumer. The rebuild overwrites the file moments later regardless.
        """
        self._open_index()
        payload = self._snapshot_payload()
        payload["build_identity"] = "0" * 16
        self._write_payload(payload)
        with snapshot.snapshot_path(self.root).open(encoding="utf-8"):
            index = self._open_index()
        self.assertIn("project", {entry.kind for entry in index.by_id.values()})

    def test_non_canonical_root_still_hits_the_cache(self) -> None:
        """`..` in the path would otherwise never match the stored `root`, so
        every call would miss *and* rewrite the snapshot — strictly worse than
        no cache, and silent. No caller does this today; #307 adds callers.

        The detour goes through a folder that **exists**: POSIX resolves a path
        component by component, so `nonexistent/..` is ENOENT there and would
        fail this for a reason that has nothing to do with the cache. Windows
        normalises `..` lexically and would have let that pass — which is what
        the first version of this test did, green locally and red on Linux CI.
        """
        self._open_index()
        detour = self.universe.parent / self.universe.name / ".." / self.universe.name / self.root.name
        calls = self._count_collections()
        self.service._build_node_index(detour)
        self.assertEqual(calls[0], 0)

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
        index = self._open_index()
        self.assertEqual(index.by_id["seren"].title, "Seren")


class DegradedBuildTests(SnapshotTestCase):
    """A build can degrade for reasons that are nothing to do with the files.

    Persisting one of those is the nastiest failure this design can have: the
    files it failed to read are unchanged, so the manifest matches on every
    later open and the crippled index is served as fresh — forever, or until the
    user edits something unrelated. Restarting the app does not clear it.
    """

    def _with_failing_schema_read(self, exc: Exception) -> None:
        def failing(*args: object, **kwargs: object) -> None:
            raise exc

        self.service.read_metadata_schema = failing  # type: ignore[method-assign]

    def test_unreadable_schema_is_not_cached(self) -> None:
        """An OSError costs the whole project its reference edges."""
        self._write_lore(self.root, "sphinx", "Sphinx")
        self._write_lore(self.root, "hero", "Hero", refs=["sphinx"])
        real = self.service.read_metadata_schema
        self._with_failing_schema_read(OSError("locked by a scanner"))
        degraded = self._open_index()
        self.assertEqual(degraded.edges_by_src, {})
        self.assertFalse(snapshot.snapshot_path(self.root).exists())

        self.service.read_metadata_schema = real  # type: ignore[method-assign]
        recovered = self._open_index()
        self.assertIn("hero", recovered.edges_by_src)

    def test_malformed_schema_IS_cached(self) -> None:
        """The counter-case, and the reason this is not just "never cache an
        error". Bad content is deterministic — the same files give the same
        index — and fixing it moves that file's mtime, so the cache self-heals.
        Refusing to cache it would mean a project with one typo never caches."""
        self._with_failing_schema_read(ProjectServiceError("metadata.schema.yaml is not valid YAML"))
        index = self._open_index()
        self.assertTrue(index.errors)
        self.assertTrue(snapshot.snapshot_path(self.root).exists())

    def test_unreadable_chat_is_not_cached(self) -> None:
        chats = self.root / "chats"
        chats.mkdir(parents=True, exist_ok=True)
        (chats / "chat_1.yaml").write_text("id: chat_1\ntitle: Talk\n", encoding="utf-8")
        real = self.service._read_yaml

        def failing(path: Path, *args: object, **kwargs: object) -> object:
            if path.suffix == ".yaml" and path.parent.name == "chats":
                raise OSError("not hydrated")
            return real(path, *args, **kwargs)

        self.service._read_yaml = failing  # type: ignore[method-assign]
        degraded = self._open_index()
        self.assertNotIn("chat_1", degraded.by_id)
        self.assertFalse(snapshot.snapshot_path(self.root).exists())


class BuildIdentityTests(SnapshotTestCase):
    """The manifest answers "have the files changed". Nothing else answers
    "would this code still produce the same index"."""

    def test_snapshot_built_by_different_code_is_rebuilt(self) -> None:
        """Ship a release that adds an `entity_ref` field to a built-in entry
        type and every project file is byte-identical — the new edges would
        never appear until the user edited something unrelated."""
        self._open_index()
        payload = self._snapshot_payload()
        payload["build_identity"] = "0" * 16
        self._write_payload(payload)
        calls = self._count_collections()
        self._open_index()
        self.assertGreater(calls[0], 0)

    def test_identity_tracks_the_source_that_decides_a_build(self) -> None:
        """Globbed, not listed, so a module added to those trees is covered
        without anyone remembering to add it here."""
        covered = {"references.py", "layers.py", "node_index.py", "default_schema.py", "schema.py"}
        found = {path.name for path in snapshot.source_files()}
        self.assertTrue(covered <= found, f"not covered: {sorted(covered - found)}")

    def test_a_payload_missing_a_newer_key_is_a_quiet_version_reject(self) -> None:
        """Ordering, pinned. `_rehydrate` reads payload keys directly, so a
        snapshot written before a key existed would `KeyError` → `corrupt` → a
        warning that says "this is a bug" — on every user's first open after any
        upgrade that adds a key. The identity check catches it first, and only
        because this module is inside `_SOURCE_ROOTS`."""
        self._open_index()
        payload = self._snapshot_payload()
        # What an upgrade actually leaves behind: written by older code (so the
        # identity differs) *and* missing the key that code never wrote.
        del payload["has_unparsed_nodes"]
        payload["build_identity"] = "0" * 16
        self._write_payload(payload)

        with self.assertRaises(snapshot.SnapshotUnusable) as caught:
            snapshot.load(
                json.dumps(payload),
                root=self.root,
                layers=self.service.collect_layers(self.root, include_machine=True),
                manifest=self.service._build_index_manifest(
                    self.service.collect_layers(self.root, include_machine=True)
                ),
            )
        self.assertEqual(caught.exception.reason, "version")

    def test_identity_actually_digests_those_files(self) -> None:
        """The first version resolved its package root one level too high, so
        both globs matched nothing and the digest was a constant over zero
        files — stable, plausible, and protecting nothing."""
        self.assertGreater(len(snapshot.source_files()), 10)
        digest = hashlib.sha256()
        for path in snapshot.source_files():
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        self.assertEqual(snapshot.build_identity(), digest.hexdigest()[:16])


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
