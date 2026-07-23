"""Scene-snapshot routes: capture · list · view · restore (ADR-0043, #401).

Its own router rather than lines in `scenes.py`: the snapshot store is a new
subsystem with a per-scene sub-resource of its own, and ADR-0043's sequencing
note asks the touch points into existing files to stay thin.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    Scene,
    Snapshot,
    SnapshotDetail,
    SnapshotDiff,
    SnapshotDiffRequest,
    SnapshotList,
)
from app.runtime import CurrentProject, translate_errors

router = APIRouter()


@router.get("/api/scenes/{scene_id}/snapshots", response_model=SnapshotList)
def list_snapshots(project: CurrentProject, scene_id: str) -> SnapshotList:
    """Every snapshot of this scene, oldest first."""
    with translate_errors():
        return project.list_snapshots(scene_id)


@router.post("/api/scenes/{scene_id}/snapshots", response_model=Snapshot)
def capture_snapshot(project: CurrentProject, scene_id: str) -> Snapshot:
    """The camera: an explicit capture, never thinned. No request body — the
    description is slice 4, and guessing its shape here would fix it."""
    with translate_errors():
        return project.capture_snapshot(scene_id)


@router.get("/api/scenes/{scene_id}/snapshots/{snapshot_id}", response_model=SnapshotDetail)
def read_snapshot(project: CurrentProject, scene_id: str, snapshot_id: str) -> SnapshotDetail:
    """The stored body, parsed for the read-only overlay. Reading a snapshot
    never touches the live buffer."""
    with translate_errors():
        return project.read_snapshot(scene_id, snapshot_id)


@router.post("/api/scenes/{scene_id}/snapshots/{snapshot_id}/restore", response_model=Scene)
def restore_snapshot(project: CurrentProject, scene_id: str, snapshot_id: str) -> Scene:
    """Capture the current state and restore, in one call.

    One endpoint rather than two calls, deliberately: a client-side
    capture-then-restore can half-fail into a snapshot nobody asked for and an
    author who cannot tell whether it worked (#395).
    """
    with translate_errors():
        return project.restore_snapshot(scene_id, snapshot_id)


@router.post(
    "/api/scenes/{scene_id}/snapshots/{snapshot_id}/diff", response_model=SnapshotDiff
)
def diff_snapshot(
    project: CurrentProject, scene_id: str, snapshot_id: str, live: SnapshotDiffRequest
) -> SnapshotDiff:
    """Provenance-tagged runs between the snapshot and the live state.

    POST, and the live state travels in the request: autosave lags the buffer by
    up to six seconds, and parking on a notch is a *reading* gesture that must
    not write. One call, at the discrete moment the author parks — the runs carry
    all the text, so Both, Now and Snapshot are three filters over one payload
    (ADR-0044 §G).
    """
    with translate_errors():
        return project.diff_snapshot(scene_id, snapshot_id, live)
