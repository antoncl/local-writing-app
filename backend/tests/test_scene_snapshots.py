"""Scene snapshots: capture · list · view · restore (ADR-0043, #401 slice 1).

The pinning tests #395 asked to ship with the slice live here, alongside the
parts of ADR-0043's own test surface that do not need the witness (that is slice
3). They are pinning tests rather than coverage: each one names an invariant
that as-implemented must not drift away from without a red build.

**The gap is simulated by backdating the scene file's mtime, not by waiting.**
That is the rule under test rather than a stand-in for it: the capture trigger
reads mtime and nothing else, so `os.utime` is the only way to exercise it
without a 30-minute test.
"""

from __future__ import annotations

import os
import time
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateStructureNodeRequest, SaveSceneRequest
from app.services.migrations import (
    CURRENT_VERSION,
    migrate_project,
    write_project_version,
)
from app.services.project.scene_snapshots import AUTOMATIC_KEEP, SESSION_GAP_MINUTES


class SnapshotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # `.resolve()` because Windows hands back the 8.3 short form and the
        # layer walk canonicalises (#356).
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Snapshot Tests")
        self.client = TestClient(app)
        response = self.client.post("/api/scenes", json={"title": "The Tide"})
        self.assertEqual(response.status_code, 200, response.text)
        self.scene_id = response.json()["id"]
        self.scene_path = self.service._path_for_node_id(self.scene_id, "scene")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ----- helpers ----------------------------------------------------------

    def _save(self, body: str) -> None:
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(title="The Tide", body=body, status="draft", entry_type="scene:scene"),
        )
        # The scene file may have been renamed by the save; re-resolve.
        self.scene_path = self.service._path_for_node_id(self.scene_id, "scene")

    def _age_past_the_gap(self) -> None:
        """Make the last save look like it happened before the session gap."""
        stale = time.time() - (SESSION_GAP_MINUTES + 1) * 60
        os.utime(self.scene_path, (stale, stale))

    def _snapshots(self) -> list:
        return self.service.list_snapshots(self.scene_id).snapshots

    def _store(self) -> Path:
        return self.root / "snapshots" / self.scene_id

    def _structure_node_for_scene(self) -> str:
        """The manuscript node wrapping this scene. A fresh project puts scenes
        at the root, so there is no chapter to reach for by index."""
        for node in self.service.read_structure().root.children:
            if node.scene_id == self.scene_id:
                return node.id
        raise AssertionError("the scene is not in the manuscript")


class CaptureTriggerTests(SnapshotTestCase):
    """ADR-0043 Amendment 2: on a save, if the last save to this scene was more
    than N minutes ago, capture the pre-save state first."""

    def test_two_saves_inside_the_gap_produce_one_automatic_snapshot(self) -> None:
        self._age_past_the_gap()
        self._save("The tide went out.")
        self._save("The tide went out further.")
        records = self._snapshots()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].retention, "thinned")

    def test_two_saves_either_side_of_the_gap_produce_two(self) -> None:
        self._age_past_the_gap()
        self._save("The tide went out.")
        self._age_past_the_gap()
        self._save("The tide went out further.")
        self.assertEqual(len(self._snapshots()), 2)

    def test_a_save_within_the_gap_captures_nothing_at_all(self) -> None:
        # The scene was created moments ago, so this is the same sitting.
        self._save("Still the same sitting.")
        self.assertEqual(self._snapshots(), [])
        self.assertFalse(self._store().exists())

    def test_the_captured_bytes_are_the_pre_save_state(self) -> None:
        """The point is *what this looked like when I sat down* — so the capture
        is taken from the file on disk before the new body is written."""
        self._save("Morning words.")
        before = self.scene_path.read_bytes()
        self._age_past_the_gap()
        self._save("Afternoon words.")

        records = self._snapshots()
        self.assertEqual(len(records), 1)
        stored = (self._store() / f"{records[0].id}.md").read_bytes()
        self.assertEqual(stored, before)
        self.assertIn(b"Morning words.", stored)
        self.assertNotIn(b"Afternoon words.", stored)


class ContentTimeIsItsOwnFactTests(SnapshotTestCase):
    """#458 — a record carries **two** times: when it was made (`captured_at`,
    unchanged) and when its bytes were written (`content_written_at`).

    Not a redefinition of `captured_at`, which the last test here is the reason
    for: content time ties where creation time cannot, so the store's total order
    still needs the creation stamp. ADR-0044's strip lays out by the content
    stamp, which is the difference between the time surface telling the truth and
    telling a plausible lie.

    The whole class drives real captures rather than asserting the field
    directly: the claim is about what the record says relative to the file, and a
    test that read the stamp back out of the code that wrote it could not fail.
    """

    def _content_time(self, record) -> datetime:
        return datetime.fromisoformat(record.content_written_at)

    def _mtime(self) -> datetime:
        return datetime.fromtimestamp(self.scene_path.stat().st_mtime, UTC)

    def test_an_automatic_snapshot_is_dated_when_its_content_was_written(self) -> None:
        """The bug in one test. The capture fires on the first save of a new
        sitting, and the bytes are the previous sitting's — so the record must
        carry the previous sitting's time, not this one's."""
        self._save("Morning words.")
        wrote_the_content_at = self._mtime()

        # A fortnight passes, then one keystroke.
        stale = time.time() - 14 * 24 * 60 * 60
        os.utime(self.scene_path, (stale, stale))
        self._save("A fortnight later.")

        records = self._snapshots()
        self.assertEqual(len(records), 1)
        dated = self._content_time(records[0])
        self.assertLess(
            dated,
            wrote_the_content_at,
            "an automatic snapshot dated 'now' claims a fortnight-old body is fresh",
        )
        self.assertLess(
            abs((dated - datetime.fromtimestamp(stale, UTC)).total_seconds()),
            2,
            "it should carry the mtime of the bytes it copied",
        )
        self.assertGreater(
            datetime.fromisoformat(records[0].captured_at),
            dated,
            "the record was still created now — the two facts must not be conflated",
        )

    def test_an_explicit_snapshot_dates_the_content_it_photographs(self) -> None:
        """The camera has the same two times as the automatic tier, and they can
        be as far apart: an author who parks, reads, and presses the camera on a
        scene untouched for a fortnight gets a record made now of prose written
        then.

        Aged deliberately. On a freshly-saved file all three timestamps sit
        inside any tolerance worth writing, so the version of this test that
        saved and immediately captured stayed green with the fix deleted.
        """
        self._save("A fortnight ago.")
        stale = time.time() - 14 * 24 * 60 * 60
        os.utime(self.scene_path, (stale, stale))

        record = self.service.capture_snapshot(self.scene_id)
        self.assertLess(
            abs((self._content_time(record) - datetime.fromtimestamp(stale, UTC)).total_seconds()),
            2,
            "the camera dates the bytes it photographed, not the shutter",
        )
        self.assertGreater(
            datetime.fromisoformat(record.captured_at),
            self._content_time(record),
            "the record was still made now — the two facts must not be conflated",
        )

    def test_the_two_tiers_mean_the_same_thing_on_one_track(self) -> None:
        """The actual defect ADR-0044 suffers: a notch's position is its
        content's age, and that has to hold for both tiers or the track means
        two different things at once."""
        self._save("Shared content.")
        fresh_source = self._mtime()
        explicit = self.service.capture_snapshot(self.scene_id)

        self._age_past_the_gap()
        aged_source = self._mtime()
        self._save("A new sitting.")
        automatic = [r for r in self._snapshots() if r.retention == "thinned"][0]

        # The explicit one was taken from unaged content; the automatic one from
        # content backdated past the gap. Each must date its own source.
        self.assertLess(
            abs((self._content_time(explicit) - fresh_source).total_seconds()), 2
        )
        self.assertLess(
            abs((self._content_time(automatic) - aged_source).total_seconds()), 2
        )
        self.assertLess(
            self._content_time(automatic),
            self._content_time(explicit),
            "the automatic notch holds older content and must sit further left",
        )

    def test_repeated_captures_of_unchanged_content_share_a_content_time(self) -> None:
        """Why this is a second field and not a redefinition.

        Content time is **not** monotonic: three captures with no edit between
        them read one mtime. Stamping `captured_at` from it made the listing's
        total order collapse onto the random `id`, and "oldest first" — which is
        also how `_thin` picks what to drop — became arbitrary. Creation time
        still separates them.
        """
        self._save("Unchanged.")
        records = [self.service.capture_snapshot(self.scene_id) for _ in range(3)]
        self.assertEqual(len({r.content_written_at for r in records}), 1)
        self.assertEqual(len({r.captured_at for r in records}), 3)
        self.assertEqual(
            [r.id for r in self._snapshots()],
            [r.id for r in records],
            "creation order still decides the listing",
        )

    def test_a_snapshot_from_before_this_field_falls_back_to_captured_at(self) -> None:
        """Additive field, defensive read, no migration — and the ADR forbids
        rewriting a stored snapshot anyway. An old record must keep showing
        exactly what it always showed."""
        record = self.service.capture_snapshot(self.scene_id)
        sidecar = self._store() / f"{record.id}.yaml"
        stored = self.service._read_yaml(sidecar)
        stored.pop("content_written_at")
        self.service._write_yaml(sidecar, stored)

        reread = self._snapshots()[0]
        self.assertEqual(reread.content_written_at, reread.captured_at)


class IdentityAndStoreTests(SnapshotTestCase):
    def test_snapshot_id_is_never_the_sources_and_snapshot_of_round_trips(self) -> None:
        record = self.service.capture_snapshot(self.scene_id)
        self.assertNotEqual(record.id, self.scene_id)
        self.assertEqual(record.snapshot_of, self.scene_id)
        self.assertEqual(self.service.read_scene(record.snapshot_of).id, self.scene_id)

    def test_the_stored_body_is_a_byte_for_byte_copy_including_front_matter(self) -> None:
        self._save("The tide went out further than she had ever seen it.")
        record = self.service.capture_snapshot(self.scene_id)
        stored = (self._store() / f"{record.id}.md").read_bytes()
        self.assertEqual(stored, self.scene_path.read_bytes())
        # It therefore still carries the *source* node's id. That is correct:
        # it is a photograph of that file, not a second node.
        self.assertIn(f"id: {self.scene_id}".encode(), stored)

    def test_the_sidecar_records_the_schema_version_in_force_at_capture(self) -> None:
        record = self.service.capture_snapshot(self.scene_id)
        self.assertEqual(record.schema_version, CURRENT_VERSION)

    def test_an_explicit_capture_is_kept(self) -> None:
        self.assertEqual(self.service.capture_snapshot(self.scene_id).retention, "kept")


class RetentionTests(SnapshotTestCase):
    def test_seven_automatic_captures_keep_five_and_drop_the_oldest_two(self) -> None:
        explicit_id: str | None = None
        automatic_ids: list[str] = []
        for i in range(7):
            self._age_past_the_gap()
            self._save(f"Sitting {i}.")
            automatic_ids.append(self._snapshots()[-1].id)
            if i == 1:
                # Interleaved, and deliberately old: an explicit snapshot
                # survives regardless of age.
                explicit_id = self.service.capture_snapshot(self.scene_id).id

        records = self._snapshots()
        thinned = [record.id for record in records if record.retention == "thinned"]
        self.assertEqual(len(thinned), AUTOMATIC_KEEP)
        self.assertEqual(thinned, automatic_ids[2:])
        # The two dropped are the oldest, and they are gone from disk — not
        # merely absent from the listing.
        for dropped in automatic_ids[:2]:
            self.assertNotIn(dropped, thinned)
            self.assertFalse((self._store() / f"{dropped}.md").exists())
            self.assertFalse((self._store() / f"{dropped}.yaml").exists())
        self.assertIn(explicit_id, [record.id for record in records])

    def test_explicit_snapshots_do_not_count_against_the_automatic_budget(self) -> None:
        for _ in range(3):
            self.service.capture_snapshot(self.scene_id)
        for i in range(AUTOMATIC_KEEP):
            self._age_past_the_gap()
            self._save(f"Sitting {i}.")
        records = self._snapshots()
        self.assertEqual(len([r for r in records if r.retention == "kept"]), 3)
        self.assertEqual(len([r for r in records if r.retention == "thinned"]), AUTOMATIC_KEEP)

    def test_snapshots_are_listed_oldest_first(self) -> None:
        ids = [self.service.capture_snapshot(self.scene_id).id for _ in range(3)]
        self.assertEqual([record.id for record in self._snapshots()], ids)
        stamps = [record.captured_at for record in self._snapshots()]
        self.assertEqual(stamps, sorted(stamps))
        # Parseable, and UTC — the strip positions notches by age.
        self.assertLessEqual(datetime.fromisoformat(stamps[0]), datetime.now(UTC))


class ViewTests(SnapshotTestCase):
    def test_reading_a_snapshot_returns_its_body_and_leaves_the_scene_alone(self) -> None:
        self._save("The tide went out.")
        record = self.service.capture_snapshot(self.scene_id)
        self._save("The tide came back in.")

        detail = self.service.read_snapshot(self.scene_id, record.id)
        self.assertEqual(detail.snapshot.id, record.id)
        self.assertEqual(detail.title, "The Tide")
        self.assertEqual(detail.body.strip(), "The tide went out.")
        self.assertEqual(self.service.read_scene(self.scene_id).body.strip(), "The tide came back in.")

    def test_reading_an_unknown_snapshot_is_a_404(self) -> None:
        response = self.client.get(f"/api/scenes/{self.scene_id}/snapshots/snap_nope")
        self.assertEqual(response.status_code, 404, response.text)


class RestoreTests(SnapshotTestCase):
    def test_snapshot_change_nothing_restore_is_byte_identical(self) -> None:
        self._save("The tide went out further than she had ever seen it.")
        before = self.scene_path.read_bytes()
        record = self.service.capture_snapshot(self.scene_id)

        self.service.restore_snapshot(self.scene_id, record.id)
        self.assertEqual(self.service._path_for_node_id(self.scene_id, "scene").read_bytes(), before)

    def test_restore_puts_the_snapshot_back_over_a_changed_scene(self) -> None:
        self._save("The tide went out.")
        record = self.service.capture_snapshot(self.scene_id)
        self._save("Something else entirely.")

        restored = self.service.restore_snapshot(self.scene_id, record.id)
        self.assertEqual(restored.body.strip(), "The tide went out.")
        self.assertEqual(self.service.read_scene(self.scene_id).body.strip(), "The tide went out.")

    def test_restore_captures_first_so_the_author_can_change_their_mind(self) -> None:
        """Acceptance 5. Restore is reversible *because* it captures first —
        which is what justifies there being no confirmation gate."""
        self._save("The morning draft.")
        morning = self.service.capture_snapshot(self.scene_id).id
        self._save("The afternoon rewrite.")

        self.service.restore_snapshot(self.scene_id, morning)
        self.assertEqual(self.service.read_scene(self.scene_id).body.strip(), "The morning draft.")

        # The afternoon rewrite is on the strip, unasked for, and restoring it
        # puts the author back where they were.
        automatic = [record for record in self._snapshots() if record.retention == "thinned"]
        self.assertEqual(len(automatic), 1)
        self.service.restore_snapshot(self.scene_id, automatic[-1].id)
        self.assertEqual(self.service.read_scene(self.scene_id).body.strip(), "The afternoon rewrite.")

    def test_restores_own_capture_is_thinned_and_can_evict_the_oldest(self) -> None:
        """Stated in ADR-0043 rather than defended against: restoring costs the
        author their oldest automatic snapshot when five are already held."""
        for i in range(AUTOMATIC_KEEP):
            self._age_past_the_gap()
            self._save(f"Sitting {i}.")
        automatic = [record.id for record in self._snapshots() if record.retention == "thinned"]
        self.assertEqual(len(automatic), AUTOMATIC_KEEP)
        target = self.service.capture_snapshot(self.scene_id).id

        self.service.restore_snapshot(self.scene_id, target)

        remaining = [record.id for record in self._snapshots() if record.retention == "thinned"]
        self.assertEqual(len(remaining), AUTOMATIC_KEEP)
        self.assertNotIn(automatic[0], remaining)

    def test_restoring_an_earlier_title_reaches_the_manuscript_tree(self) -> None:
        record = self.service.capture_snapshot(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(title="A Different Title", body="x", status="draft", entry_type="scene:scene"),
        )
        node_id = self._structure_node_for_scene()
        self.assertEqual(
            [n.title for n in self.service.read_structure().root.children if n.id == node_id],
            ["A Different Title"],
        )

        self.service.restore_snapshot(self.scene_id, record.id)

        self.assertEqual(
            [n.title for n in self.service.read_structure().root.children if n.id == node_id],
            ["The Tide"],
        )


class DeletionTests(SnapshotTestCase):
    def _chapter_id(self) -> str:
        for node in self.service.read_structure().root.children:
            if node.type == "scene:chapter":
                return node.id
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter One", entry_type="scene:chapter")
        )
        return self._chapter_id()

    def test_deleting_a_scene_leaves_no_residue_under_snapshots(self) -> None:
        for _ in range(3):
            self.service.capture_snapshot(self.scene_id)
        self.assertTrue(self._store().is_dir())

        self.service.delete_scene(self.scene_id)

        self.assertFalse(self._store().exists())
        self.assertEqual(list((self.root / "snapshots").rglob("*")), [])

    def test_deleting_a_container_cascades_to_its_scenes_snapshots(self) -> None:
        """The other delete path: `delete_structure_node` unlinks each
        descendant scene itself rather than calling `delete_scene`, so the
        cascade has to be on both or one of them leaves residue."""
        self.service.move_structure_node(self._structure_node_for_scene(), self._chapter_id(), 0)
        self.service.capture_snapshot(self.scene_id)
        self.assertTrue(self._store().is_dir())

        self.service.delete_structure_node(self._chapter_id())

        self.assertFalse(self._store().exists())
        self.assertEqual(list((self.root / "snapshots").rglob("*")), [])


class IndexAndMigrationTests(SnapshotTestCase):
    def test_a_migration_run_leaves_every_stored_snapshot_byte_identical(self) -> None:
        """Snapshots are immutable at rest: migration happens at restore, over
        the one body, on the way out. Rewriting a witness destroys what makes it
        a witness."""
        ids = [self.service.capture_snapshot(self.scene_id).id for _ in range(3)]
        before = {path.name: path.read_bytes() for path in sorted(self._store().iterdir())}

        write_project_version(self.root, 0)
        applied = migrate_project(self.root)
        self.assertTrue(applied)

        after = {path.name: path.read_bytes() for path in sorted(self._store().iterdir())}
        self.assertEqual(after, before)
        self.assertEqual(len(ids) * 2, len(after))

    def test_the_migration_backup_does_not_carry_the_snapshot_store(self) -> None:
        """`SKIP_FROM_BACKUP` covers `snapshots/`, or the three retained backups
        each carry a full copy of the project's history."""
        self.service.capture_snapshot(self.scene_id)
        write_project_version(self.root, 0)
        applied = migrate_project(self.root)
        self.assertTrue(applied)
        archives = sorted((self.root / ".migration-backups").glob("*.zip"))
        self.assertTrue(archives)
        with zipfile.ZipFile(archives[-1]) as archive:
            names = archive.namelist()
        self.assertFalse([name for name in names if name.startswith("snapshots/")], names)

    def test_no_resolver_read_touches_the_snapshot_store(self) -> None:
        """ADR-0043: the witness is never consulted by the resolver. There is no
        witness yet (slice 3), so what is pinned here is the stronger and more
        durable half — nothing on the resolution path opens the store at all."""
        self._save("The tide went out.")
        for _ in range(3):
            self.service.capture_snapshot(self.scene_id)

        reads: list[Path] = []
        real_read_text = Path.read_text
        real_read_bytes = Path.read_bytes

        def spy_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            reads.append(self)
            return real_read_text(self, *args, **kwargs)

        def spy_bytes(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            reads.append(self)
            return real_read_bytes(self, *args, **kwargs)

        Path.read_text = spy_text  # type: ignore[method-assign]
        Path.read_bytes = spy_bytes  # type: ignore[method-assign]
        try:
            self.service._build_node_index()
            self.service.effective_state("nobody", self.scene_id)
            self.service.read_scene(self.scene_id)
        finally:
            Path.read_text = real_read_text  # type: ignore[method-assign]
            Path.read_bytes = real_read_bytes  # type: ignore[method-assign]

        touched = [path for path in reads if "snapshots" in path.parts]
        self.assertEqual(touched, [], touched)


class RouteTests(SnapshotTestCase):
    """The HTTP surface the strip drives: capture · list · view · restore."""

    def test_capture_list_view_restore_over_http(self) -> None:
        base = f"/api/scenes/{self.scene_id}/snapshots"
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(title="The Tide", body="The tide went out.", status="draft", entry_type="scene:scene"),
        )

        captured = self.client.post(base)
        self.assertEqual(captured.status_code, 200, captured.text)
        snapshot_id = captured.json()["id"]
        self.assertEqual(captured.json()["retention"], "kept")

        listed = self.client.get(base)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()["snapshots"]], [snapshot_id])

        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(title="The Tide", body="Rewritten.", status="draft", entry_type="scene:scene"),
        )
        viewed = self.client.get(f"{base}/{snapshot_id}")
        self.assertEqual(viewed.status_code, 200, viewed.text)
        self.assertEqual(viewed.json()["body"].strip(), "The tide went out.")

        restored = self.client.post(f"{base}/{snapshot_id}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["body"].strip(), "The tide went out.")

    def test_listing_a_scene_with_no_snapshots_is_an_empty_list(self) -> None:
        response = self.client.get(f"/api/scenes/{self.scene_id}/snapshots")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"snapshots": []})


# ----- slice 4: pin · delete · description (#468) ---------------------------
#
# These name the invariants the author's three new gestures rest on. The load-
# bearing one throughout: pin and description mutate the sidecar's **authorial**
# half (`retention`, `description`); the **evidentiary** half — the `.md` body
# and the `witness` — is frozen, because a witness describes the bytes it
# accompanies and rewriting it destroys what makes it a witness.


class PinTests(SnapshotTestCase):
    def _automatic(self, body: str) -> str:
        """Drive one automatic (thinned) capture and return its id."""
        self._age_past_the_gap()
        self._save(body)
        return self._snapshots()[-1].id

    def test_pinning_makes_an_automatic_survive_thinning(self) -> None:
        """Acceptance 1 — proven by driving capture past the budget, not by
        reading the field back. Pin the oldest automatic, then push two more
        through: without the pin the two oldest would both evict, so the pinned
        one surviving while its next-oldest neighbour is dropped is the pin."""
        ids = [self._automatic(f"Sitting {i}.") for i in range(AUTOMATIC_KEEP)]
        self.service.pin_snapshot(self.scene_id, ids[0])

        self._automatic("One more sitting.")
        self._automatic("And another sitting.")

        remaining = {record.id for record in self._snapshots()}
        self.assertIn(ids[0], remaining)
        self.assertTrue((self._store() / f"{ids[0]}.md").exists())
        # The next-oldest thinned record — younger than the pinned one — was the
        # one thinning dropped, so ids[0] can only be present because it is kept.
        self.assertNotIn(ids[1], remaining)

    def test_pinning_frees_an_automatic_slot(self) -> None:
        """The budget is a window over the *thinned* set, and pinning removes a
        member from it — so one more automatic fits than before."""
        ids = [self._automatic(f"Sitting {i}.") for i in range(AUTOMATIC_KEEP)]
        self.service.pin_snapshot(self.scene_id, ids[0])
        # The remaining four thinned plus one more makes five — at a full budget
        # that sixth automatic would have evicted the oldest, but the pin took
        # ids[0] out of the thinned set, so none of ids[1:] is dropped.
        self._automatic("A fresh sitting.")
        thinned = [r.id for r in self._snapshots() if r.retention == "thinned"]
        self.assertEqual(len(thinned), AUTOMATIC_KEEP)
        for surviving in ids[1:]:
            self.assertIn(surviving, thinned)

    def test_pinning_is_idempotent_and_one_directional(self) -> None:
        """An explicit snapshot is already `kept`, so pinning it is a no-op; and
        there is no unpin — the gesture only ever promotes."""
        explicit = self.service.capture_snapshot(self.scene_id)
        self.assertEqual(self.service.pin_snapshot(self.scene_id, explicit.id).retention, "kept")

        automatic = self._automatic("Morning.")
        self.assertEqual(self.service.pin_snapshot(self.scene_id, automatic).retention, "kept")

    def test_pinning_an_unknown_snapshot_is_a_404(self) -> None:
        response = self.client.post(f"/api/scenes/{self.scene_id}/snapshots/snap_nope/pin")
        self.assertEqual(response.status_code, 404, response.text)


class DeleteSnapshotTests(SnapshotTestCase):
    def _automatic(self, body: str) -> str:
        self._age_past_the_gap()
        self._save(body)
        return self._snapshots()[-1].id

    def test_delete_removes_both_files_and_returns_what_remains(self) -> None:
        """Acceptance 2 — both files go, the listing drops it, nothing is left
        behind under the store."""
        keep = self.service.capture_snapshot(self.scene_id).id
        gone = self.service.capture_snapshot(self.scene_id).id

        remaining = self.service.delete_snapshot(self.scene_id, gone)

        self.assertEqual([record.id for record in remaining.snapshots], [keep])
        self.assertFalse((self._store() / f"{gone}.md").exists())
        self.assertFalse((self._store() / f"{gone}.yaml").exists())
        # No residue: exactly the kept snapshot's two files remain.
        self.assertEqual(
            sorted(path.name for path in self._store().iterdir()),
            sorted([f"{keep}.md", f"{keep}.yaml"]),
        )
        self.assertEqual([record.id for record in self._snapshots()], [keep])

    def test_thinning_is_unaffected_by_the_gap_a_delete_leaves(self) -> None:
        """Deleting a thinned record just gives the next capture one more slot
        before it evicts — the same keep-five window over a smaller set."""
        ids = [self._automatic(f"Sitting {i}.") for i in range(AUTOMATIC_KEEP)]
        self.service.delete_snapshot(self.scene_id, ids[2])

        self._automatic("One more.")
        self._automatic("And another.")

        thinned = [record for record in self._snapshots() if record.retention == "thinned"]
        self.assertEqual(len(thinned), AUTOMATIC_KEEP)

    def test_deleting_the_last_snapshot_takes_the_directory_too(self) -> None:
        """"No residue" has to mean the store is back to how it was before the
        first capture — otherwise every scene ever snapshotted and then cleared
        leaves an empty folder behind."""
        only = self.service.capture_snapshot(self.scene_id).id
        self.assertTrue(self._store().is_dir())

        self.service.delete_snapshot(self.scene_id, only)

        self.assertFalse(self._store().exists())
        self.assertEqual(list((self.root / "snapshots").rglob("*")), [])
        # And the store rebuilds cleanly on the next capture.
        self.assertTrue(self.service.capture_snapshot(self.scene_id).id)
        self.assertEqual(len(self._snapshots()), 1)

    def test_deleting_an_unknown_snapshot_is_a_404(self) -> None:
        response = self.client.delete(f"/api/scenes/{self.scene_id}/snapshots/snap_nope")
        self.assertEqual(response.status_code, 404, response.text)


class DescriptionTests(SnapshotTestCase):
    def test_a_description_round_trips(self) -> None:
        """Acceptance 4 — read back off disk, not out of the response object."""
        record = self.service.capture_snapshot(self.scene_id)
        updated = self.service.set_snapshot_description(
            self.scene_id, record.id, "Before the flashback rewrite"
        )
        self.assertEqual(updated.description, "Before the flashback rewrite")
        self.assertEqual(self._snapshots()[0].description, "Before the flashback rewrite")

    def test_a_description_is_never_confused_with_the_title(self) -> None:
        """Acceptance 4 — original data, not a copy of the front-matter title.
        The byte-copy carries none of it; it exists only in the sidecar."""
        self._save("The tide went out.")
        record = self.service.capture_snapshot(self.scene_id)
        self.service.set_snapshot_description(self.scene_id, record.id, "A note, not a name")

        detail = self.service.read_snapshot(self.scene_id, record.id)
        self.assertEqual(detail.title, "The Tide")
        self.assertEqual(detail.snapshot.description, "A note, not a name")
        self.assertNotIn(b"A note, not a name", (self._store() / f"{record.id}.md").read_bytes())

    def test_a_description_survives_the_restore_of_another_snapshot(self) -> None:
        """Acceptance 4 — a restore of a *different* notch captures and overwrites
        the scene; the described snapshot's sidecar is never touched."""
        self._save("First.")
        described = self.service.capture_snapshot(self.scene_id)
        self.service.set_snapshot_description(self.scene_id, described.id, "Keep me")
        self._save("Second.")
        other = self.service.capture_snapshot(self.scene_id)

        self.service.restore_snapshot(self.scene_id, other.id)

        again = next(r for r in self._snapshots() if r.id == described.id)
        self.assertEqual(again.description, "Keep me")

    def test_a_description_is_collapsed_to_one_line(self) -> None:
        record = self.service.capture_snapshot(self.scene_id)
        updated = self.service.set_snapshot_description(self.scene_id, record.id, "  two\nlines  ")
        self.assertEqual(updated.description, "two lines")

    def test_a_description_can_be_cleared(self) -> None:
        record = self.service.capture_snapshot(self.scene_id)
        self.service.set_snapshot_description(self.scene_id, record.id, "temporary")
        cleared = self.service.set_snapshot_description(self.scene_id, record.id, "")
        self.assertEqual(cleared.description, "")
        self.assertEqual(self._snapshots()[0].description, "")


class SidecarMutabilityTests(SnapshotTestCase):
    """Acceptance 6/7 — the authorial half of a sidecar moves; the evidentiary
    half does not. A witness describes the bytes it accompanies."""

    def test_pin_and_describe_freeze_the_body_and_the_witness(self) -> None:
        self._age_past_the_gap()
        self._save("Morning.")
        self._age_past_the_gap()
        self._save("Afternoon.")  # captures an automatic of "Morning."

        record = self._snapshots()[-1]
        self.assertEqual(record.retention, "thinned")
        body_file = self._store() / f"{record.id}.md"
        sidecar = self._store() / f"{record.id}.yaml"
        body_before = body_file.read_bytes()
        witness_before = self.service._read_yaml(sidecar).get("witness")
        # The freeze is only meaningful if there is a witness to freeze.
        self.assertIsInstance(witness_before, dict)

        self.service.pin_snapshot(self.scene_id, record.id)
        self.service.set_snapshot_description(self.scene_id, record.id, "pinned and described")

        self.assertEqual(body_file.read_bytes(), body_before)
        after = self.service._read_yaml(sidecar)
        self.assertEqual(after.get("witness"), witness_before)
        # The authorial half is exactly what moved, and only it.
        self.assertEqual(after.get("retention"), "kept")
        self.assertEqual(after.get("description"), "pinned and described")


class Slice4RouteTests(SnapshotTestCase):
    """The HTTP surface for pin · delete · description."""

    def test_pin_over_http_flips_retention(self) -> None:
        self._age_past_the_gap()
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(title="The Tide", body="Morning.", status="draft", entry_type="scene:scene"),
        )
        self._age_past_the_gap()
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(title="The Tide", body="Afternoon.", status="draft", entry_type="scene:scene"),
        )
        auto = self._snapshots()[-1]
        self.assertEqual(auto.retention, "thinned")

        base = f"/api/scenes/{self.scene_id}/snapshots"
        response = self.client.post(f"{base}/{auto.id}/pin")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["retention"], "kept")

    def test_description_over_http_round_trips(self) -> None:
        record = self.service.capture_snapshot(self.scene_id)
        base = f"/api/scenes/{self.scene_id}/snapshots"
        response = self.client.put(
            f"{base}/{record.id}/description", json={"description": "A note"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["description"], "A note")
        listed = self.client.get(base).json()["snapshots"]
        self.assertEqual(listed[0]["description"], "A note")

    def test_delete_over_http_returns_the_remaining_list(self) -> None:
        keep = self.service.capture_snapshot(self.scene_id).id
        gone = self.service.capture_snapshot(self.scene_id).id
        base = f"/api/scenes/{self.scene_id}/snapshots"

        response = self.client.delete(f"{base}/{gone}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()["snapshots"]], [keep])
        self.assertEqual([item["id"] for item in self.client.get(base).json()["snapshots"]], [keep])
