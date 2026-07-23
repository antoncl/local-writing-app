"""Scene snapshots: capture, list, view, restore (ADR-0043, #401 slice 1).

A snapshot is a **witness** — prose restored byte-exact, context captured and
only reported when it has drifted. Slice 1 is the prose half; the witness and
its drift report are slice 3, and the sidecar deliberately leaves room for it
rather than guessing its shape here.

**Two files per snapshot, under `snapshots/<source-node-id>/`:**

- `<snapshot-id>.md` — a byte-for-byte copy of the scene file *including front
  matter*, so it still carries the **source** node's id. That is correct: it is
  a photograph of that file, not a second node. Restore copies these bytes back;
  it never re-serializes, because a round trip through a serializer is the one
  risk not worth taking on the feature whose job is not losing words.
- `<snapshot-id>.yaml` — the snapshot's own record. Its `id` is its own, never
  the source's; `snapshot_of` points back.

The store is at the project root and contributes **nothing** to the node index —
excluded at the index, once, never filtered per consumer (ADR-0043; pinned by
`backend/tests/test_snapshots_not_indexed.py`, which landed ahead of this file).

Every method here takes `root` from the caller rather than reading
`self._require_project()` itself: a capture is a write, so it is a unit of work
with a resolution scope it carries explicitly (ADR-0045, same reasoning as
`_manuscript_tree`).
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.models import Snapshot, SnapshotDetail, SnapshotList, Witness
from app.models.snapshots import UNREADABLE_WITNESS_VERSION
from app.services.migrations import CURRENT_VERSION
from app.services.project.errors import ProjectServiceError

if TYPE_CHECKING:
    from app.models import Scene

SNAPSHOTS_DIRNAME = "snapshots"

# How long a pause makes the next save a new sitting. On a save, if the last
# save to this scene was longer ago than this, the **pre-save** bytes are
# captured first — "what did this look like when I sat down" (ADR-0043
# Amendment 2, settled on #395).
#
# 30 minutes: long enough that lunch does not split a sitting, short enough that
# a morning and an evening are separate. It is a constant and not a setting
# because a wrong value cannot lose work — it only makes automatic snapshots
# sparser or denser than ideal — and "how many minutes constitutes a new
# session?" is unanswerable without knowing how capture, thinning and pinning
# interact. The author already has controls in both directions that need no
# knowledge of this rule at all: press the camera, pin what should survive.
#
# Watch for the sprinter case — short bursts with sub-N gaps collapse a day into
# one snapshot. If that shows up in real use the answer is a second trigger
# (accumulated change since the last snapshot), not a smaller N: it adapts on
# its own instead of asking the author to tune it.
SESSION_GAP_MINUTES = 30

# Automatic snapshots keep the last five per scene; explicit ones are never
# thinned. Five because the automatic tier is a prosthetic for the author's own
# recall of recent states, and that is roughly the depth a person holds. A
# considered default, not a measured optimum.
AUTOMATIC_KEEP = 5


def _read_body_and_content_time(path: Path) -> tuple[bytes, str]:
    """The bytes to copy, and when those bytes were **written** — from one file.

    The timestamp is what the strip lays out by. `captured_at` is right for the
    camera and wrong for every automatic capture: `maybe_capture_session_
    boundary` fires *before* the save, so the file still holds what the previous
    sitting wrote — that is the whole point, and
    `test_the_captured_bytes_are_the_pre_save_state` pins it. The record then
    claimed "just now" about prose last touched a fortnight ago (#458).

    Not cosmetic: ADR-0044's strip lays notches out **by age**, so the one surface
    built for navigating time was the surface misreporting it — and because
    explicit captures *were* dated correctly, automatic and explicit notches on
    the same track meant different things with nothing to tell them apart.

    **Why this is a second field rather than a redefinition of `captured_at`.**
    Stamping `captured_at` from the mtime was the first attempt and it broke the
    total order the store depends on. Two explicit captures with no edit between
    them read the *same* mtime, so they tie; `_snapshot_records` then falls back
    to the random `id`, and "oldest first" — the listing contract, and the basis
    on which `_thin` drops "the oldest" — becomes arbitrary. Creation time is
    monotonic and content time is not, so they are genuinely two facts and the
    record keeps both.

    Read as "when this content was last written to the scene file", which stays
    honest after a restore: restoring old prose writes it now, so a later
    snapshot of it is dated now, because that is when those bytes became the
    file's contents.

    **One open handle, read then `fstat`** — not `stat()` beside `read_bytes()`.
    Scene routes are `def`, so FastAPI runs them in a threadpool and two panes on
    one scene interleave; a write landing between two separate calls would pair
    one version's bytes with the other version's time, baking #458 in miniature
    into a record ADR-0043 forbids rewriting. Every writer here replaces the file
    atomically, so the handle pins the version that was read and `fstat` cannot
    describe anything else.

    No `OSError` fallback: this **is** the read, so a failure here is exactly the
    failure `read_bytes` already raised, and it belongs to the caller that owns
    "a capture is never the reason a save fails" (`maybe_capture_session_
    boundary`, which returns early on a missing file).

    Microseconds are pinned for the same reason `captured_at` pins them: an
    `isoformat` that omits them on the exact second makes two stamps compare as
    strings of different shapes.
    """
    with path.open("rb") as handle:
        body = handle.read()
        written = datetime.fromtimestamp(os.fstat(handle.fileno()).st_mtime, UTC)
    return body, written.isoformat(timespec="microseconds")


class SceneSnapshotsMixin:
    """Composed onto `ProjectService`; the project IO helpers it uses
    (`_atomic_write`, `_read_yaml`, `_write_yaml`, `_new_id`,
    `_read_markdown_with_front_matter`, `_path_for_node_id`,
    `_node_id_for_path`, `_update_scene_title_in_structure`,
    `_remove_missing_scene_todo_anchors`, `read_scene`) resolve via MRO."""

    # ----- store layout -----------------------------------------------------

    def _snapshots_dir(self, root: Path, node_id: str) -> Path:
        """The store for one scene. The *directory* name is the source node id —
        load-bearing and never renamed, which is a deliberate departure from
        "filenames are cosmetic": ids are stable and titles are not.

        The directory listing **is** the lookup table (ADR-0043). There is no
        index to build, invalidate or repair, and the answer survives any cache
        corruption because it is the storage.
        """
        return root / SNAPSHOTS_DIRNAME / node_id

    # ----- reading ----------------------------------------------------------

    def _read_snapshot_record(self, sidecar: Path) -> Snapshot:
        data = self._read_yaml(sidecar)
        retention = data.get("retention")
        if retention not in ("thinned", "kept"):
            raise ProjectServiceError(
                f"Snapshot {sidecar.stem} has an unreadable retention value.", 422
            )
        captured_at = str(data.get("captured_at") or "")
        return Snapshot(
            id=str(data.get("id") or sidecar.stem),
            snapshot_of=str(data.get("snapshot_of") or ""),
            captured_at=captured_at,
            # Falls back to `captured_at` on every snapshot taken before #458,
            # which is exactly what those records have always displayed. An
            # additive field with a defensive read, not a migration — and the
            # ADR forbids rewriting a stored snapshot in any case.
            content_written_at=str(data.get("content_written_at") or captured_at),
            retention=retention,
            schema_version=int(data.get("schema_version") or 0),
        )

    def read_snapshot_witness(self, root: Path, node_id: str, snapshot_id: str) -> Witness | None:
        """The witness stored beside one snapshot, or `None` when there isn't one.

        Read here and **not** carried on `Snapshot`. The strip refetches the list
        on every scene open and after every capture and restore, and a witness
        holds up to 200 entities of resolved lore state — putting it on the
        listing model shipped ~1.5 MB per refresh to a client with no field to
        read it into. Only the comparison wants it, and it wants exactly one.

        A witness that is present but will not parse is **not** reported as
        absent. Absent means "this snapshot predates the witness — there is
        nothing to compare"; a corrupt one is a witness *recorded under a shape
        this build cannot read*, which is what `comparable=False` says. Those
        used to produce byte-identical payloads, so the corrupt case rendered
        nothing at all — no report, no note, no sign a comparison had been tried.

        Never raises for the witness's sake. It is evidence about the world, not
        part of the record that makes a snapshot restorable: refusing to restore
        because a sidecar's advisory half will not parse would let it break the
        half that holds the words.
        """
        sidecar = self._snapshots_dir(root, node_id) / f"{snapshot_id}.yaml"
        try:
            raw = self._read_yaml(sidecar).get("witness")
        except (ProjectServiceError, OSError):
            return None
        if not isinstance(raw, dict):
            return None
        try:
            return Witness.model_validate(raw)
        except ValidationError:
            return Witness(version=UNREADABLE_WITNESS_VERSION)

    def _snapshot_records(self, root: Path, node_id: str) -> list[Snapshot]:
        """Every snapshot of `node_id`, oldest first.

        Sorted by `(captured_at, id)` rather than `captured_at` alone so the
        order is total: thinning drops "the oldest", and an order with ties has
        no such thing.
        """
        folder = self._snapshots_dir(root, node_id)
        if not folder.is_dir():
            return []
        records = [self._read_snapshot_record(sidecar) for sidecar in sorted(folder.glob("*.yaml"))]
        records.sort(key=lambda record: (record.captured_at, record.id))
        return records

    def list_snapshots(self, scene_id: str) -> SnapshotList:
        root = self._require_project()
        node_id = self._snapshot_source_id(scene_id)
        return SnapshotList(snapshots=self._snapshot_records(root, node_id))

    def read_snapshot(self, scene_id: str, snapshot_id: str) -> SnapshotDetail:
        """The stored body, parsed for display. Reading is not restoring — the
        byte-copy is parsed here so a pane can render it, while restore stays a
        file copy."""
        root = self._require_project()
        node_id = self._snapshot_source_id(scene_id)
        record = self._require_snapshot(root, node_id, snapshot_id)
        front_matter, body = self._read_markdown_with_front_matter(
            self._snapshots_dir(root, node_id) / f"{snapshot_id}.md"
        )
        return SnapshotDetail(
            snapshot=record,
            title=str(front_matter.get("title") or node_id),
            body=body,
        )

    def _require_snapshot(self, root: Path, node_id: str, snapshot_id: str) -> Snapshot:
        sidecar = self._snapshots_dir(root, node_id) / f"{snapshot_id}.yaml"
        body = self._snapshots_dir(root, node_id) / f"{snapshot_id}.md"
        if not sidecar.exists() or not body.exists():
            raise ProjectServiceError(f"Snapshot {snapshot_id} does not exist.", 404)
        return self._read_snapshot_record(sidecar)

    def _snapshot_source_id(self, scene_id: str) -> str:
        """The id the store is keyed by: the scene file's front-matter id, which
        is canonical identity. A route may be reached with the structure node's
        id instead, and the two are not always the same."""
        path = self._path_for_node_id(scene_id, "scene")
        return self._node_id_for_path(path)

    # ----- capture ----------------------------------------------------------

    def capture_snapshot(self, scene_id: str, dynamic_context: list[str] | None = None) -> Snapshot:
        """The camera: an explicit, never-thinned capture of the current state."""
        root = self._require_project()
        path = self._path_for_node_id(scene_id, "scene")
        node_id = self._node_id_for_path(path)
        return self._capture(root, node_id, path, retention="kept", dynamic_context=dynamic_context)

    def _capture(
        self,
        root: Path,
        node_id: str,
        path: Path,
        *,
        retention: str,
        dynamic_context: list[str] | None = None,
    ) -> Snapshot:
        """Copy `path`'s bytes into the store and write the sidecar beside them.

        The `.md` is written with `write_bytes`, not through the front-matter
        writer: the record must be what the file *was*, not what a serializer
        would make of it.

        **The bytes are read before the witness is built**, and the order is the
        invariant rather than an accident: *a witness describes the bytes it
        accompanies*. Building the witness first — which is what passing it in as
        an argument did — opened a window of the witness's own build time (tens
        of milliseconds, plus the mutations index) in which another writer could
        land, leaving the `.md` holding post-write bytes and the sidecar
        describing the world before them.

        `content_written_at` is not a second read for the same reason: it comes
        off the handle the bytes came from, so no write can slip between the two
        and leave the record dating one version's bytes by another's clock.

        The witness is written once, here, and never rewritten: letting a later
        save land a fresh context set in an existing sidecar would leave the body
        at the start of the session and the witness at its end.

        `dynamic_context` keeps `None` ("not observed") distinct from `[]`
        ("observed and empty") all the way down.
        """
        folder = self._snapshots_dir(root, node_id)
        folder.mkdir(parents=True, exist_ok=True)
        snapshot_id = self._new_id("snap")
        # One read, so the timestamp describes the bytes beside it even if the
        # file is rewritten a moment later — the same invariant the witness gets
        # from following this line, stated in the docstring below.
        body, content_written_at = _read_body_and_content_time(path)
        witness = self.build_witness(node_id, dynamic_context)
        record: dict[str, Any] = {
            "id": snapshot_id,
            "snapshot_of": node_id,
            # When the RECORD was made. Monotonic across captures, so it is what
            # the listing sorts by and what `_thin` calls "the oldest".
            #
            # Microseconds are pinned rather than left to `isoformat`, which
            # omits them on the exact second — two captures in one second would
            # then be compared as strings of different shapes, and the sort that
            # decides which snapshot is "the oldest" would rest on where "+"
            # falls against "." in ASCII.
            "captured_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            # When the CONTENT was written. What the strip lays out by (#458).
            "content_written_at": content_written_at,
            "retention": retention,
            "schema_version": CURRENT_VERSION,
        }
        # `None` means the build failed, and then no witness is written at all.
        # Storing an empty one instead made the comparison accept it as real and
        # answer "nothing changed" — an affirmative all-clear from a build that
        # saw nothing.
        if witness is not None:
            record["witness"] = witness.model_dump(mode="json")
        # Body first: a sidecar with no body beside it is a listing entry that
        # cannot be viewed or restored, which is worse than an orphan .md that
        # nothing lists.
        (folder / f"{snapshot_id}.md").write_bytes(body)
        self._write_yaml(folder / f"{snapshot_id}.yaml", record)
        if retention == "thinned":
            self._thin(root, node_id)
        return self._read_snapshot_record(folder / f"{snapshot_id}.yaml")

    def _thin(self, root: Path, node_id: str) -> None:
        """Keep the last `AUTOMATIC_KEEP` automatic snapshots; `kept` ones are
        never thinned, and never count toward the budget."""
        thinned = [record for record in self._snapshot_records(root, node_id) if record.retention == "thinned"]
        folder = self._snapshots_dir(root, node_id)
        for record in thinned[: max(0, len(thinned) - AUTOMATIC_KEEP)]:
            (folder / f"{record.id}.md").unlink(missing_ok=True)
            (folder / f"{record.id}.yaml").unlink(missing_ok=True)

    def maybe_capture_session_boundary(
        self, root: Path, node_id: str, path: Path, dynamic_context: list[str] | None = None
    ) -> None:
        """Called from the save path **before** the new body is written.

        The rule (ADR-0043 Amendment 2): on a save, if the last save to this
        scene was longer ago than `SESSION_GAP_MINUTES`, capture the pre-save
        state first. The backend needs nothing new for this — it already has the
        file, its modification time and the save.

        *Last save is the file's mtime.* It needs no new state, and the two
        things that could have made it lie do not: a rename preserves mtime, and
        structure writes touch `manuscript.structure.yaml`, not the scene. What
        does refresh it — a marker rewrite, an embedded-todo edit, a schema-driven
        metadata rewrite — are all writes to this scene's own file, so counting
        them as a save is right rather than merely tolerable.

        A missing file is not an error here: a capture is never the reason a
        save fails.

        **One imprecision, accepted deliberately.** The bytes are the pre-edit
        state, but `dynamic_context` is the set the editor holds *now* — it
        describes the body about to be written, since the author has been typing
        for up to one save interval before this fires. Exact agreement would need
        the backend to retain the previous session's last set across the gap and
        across restarts. The error is bounded by one save rather than by the
        session, and it is self-correcting.
        """
        if not path.exists():
            return
        last_save = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if (datetime.now(UTC) - last_save).total_seconds() <= SESSION_GAP_MINUTES * 60:
            return
        self._capture(root, node_id, path, retention="thinned", dynamic_context=dynamic_context)

    # ----- restore ----------------------------------------------------------

    def restore_snapshot(self, scene_id: str, snapshot_id: str) -> Scene:
        """Capture the current state, then put the snapshot back — one
        operation, never a client-side capture-then-restore.

        Restore is reversible *because* it captures first (ADR-0043 Amendment
        1), which is what justifies there being no confirmation gate. The
        capture is a `thinned` one, so on a scene already holding five it evicts
        the oldest: the state about to be overwritten is worth more than a
        five-sittings-old one. That is intended, and is not defended against.

        The failure ordering is deliberate. Capture precedes the overwrite, so a
        failure between them leaves an extra snapshot and an untouched scene —
        never the reverse.
        """
        root = self._require_project()
        path = self._path_for_node_id(scene_id, "scene")
        node_id = self._node_id_for_path(path)
        self._require_snapshot(root, node_id, snapshot_id)

        # No dynamic context: this route has no prose editor behind it, so the
        # implicit set is *not observed* rather than empty. The witness records
        # two sources, and a later comparison narrows membership to what both
        # sides saw instead of reporting every detected entity as removed.
        self._capture(root, node_id, path, retention="thinned")

        stored = self._snapshots_dir(root, node_id) / f"{snapshot_id}.md"
        self._atomic_write_bytes(path, stored.read_bytes())

        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        # The filename stays as it is — it is cosmetic, and reads resolve by id.
        # The structure title is not: it is what the manuscript tree renders, so
        # a restore that changed the title has to reach it.
        self._update_scene_title_in_structure(node_id, str(front_matter.get("title") or node_id))
        self._remove_missing_scene_todo_anchors(node_id, body)
        return self.read_scene(node_id)

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        """`_atomic_write` for bytes. Restore must not go through the text
        writer: encoding, newline translation and the front-matter writer's
        normalisation are each a way for "byte-for-byte" to stop being true."""
        temp_path = path.with_name(f"{path.name}.restore-tmp")
        temp_path.write_bytes(data)
        temp_path.replace(path)

    # ----- deletion ---------------------------------------------------------

    def delete_scene_snapshots(self, root: Path, node_id: str) -> None:
        """A scene and its snapshots are one unit of deletion (ADR-0043).

        Keeping them would leave exactly the unreachable residue that ADR
        rejects: the directory is named by node id, the author knows scenes by
        title, and once the scene is gone there is no node left to hang an
        affordance on.
        """
        shutil.rmtree(self._snapshots_dir(root, node_id), ignore_errors=True)
