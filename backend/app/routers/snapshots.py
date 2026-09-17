"""Scene-snapshot routes: capture · list · view · restore (ADR-0043, #401).

Its own router rather than lines in `scenes.py`: the snapshot store is a new
subsystem with a per-scene sub-resource of its own, and ADR-0043's sequencing
note asks the touch points into existing files to stay thin.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CaptureSnapshotRequest,
    Scene,
    SetSnapshotDescriptionRequest,
    Snapshot,
    SnapshotDetail,
    SnapshotDrift,
    SnapshotDriftRequest,
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
def capture_snapshot(
    project: CurrentProject, scene_id: str, request: CaptureSnapshotRequest | None = None
) -> Snapshot:
    """The camera: an explicit capture, never thinned.

    The body is optional, and its absence is meaningful: no body means the
    dynamic context was **not observed**, which the witness records as two
    sources rather than three. A caller with a prose editor behind it sends the
    detected set; one without says nothing rather than claiming emptiness.
    """
    with translate_errors():
        return project.capture_snapshot(
            scene_id, request.dynamic_context if request is not None else None
        )


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
    "/api/scenes/{scene_id}/snapshots/{snapshot_id}/drift", response_model=SnapshotDrift
)
def snapshot_drift(
    project: CurrentProject, scene_id: str, snapshot_id: str, live: SnapshotDriftRequest
) -> SnapshotDrift:
    """The drift report alone — the frozen witness against the world now (#583).

    Once the content diff (runs + fields + title) is computed client-side, this
    is the one half that stays on the server: building the "now" witness needs
    resolved entity state the client does not have. It carries the dynamic
    context the editor observed plus the scene's unsaved buffer (#581), so the
    now-witness resolves the same "now" the client-side field flip does.
    """
    with translate_errors():
        return project.snapshot_drift(
            scene_id,
            snapshot_id,
            live.dynamic_context,
            buffer_metadata=live.metadata,
            buffer_body=live.body,
        )


@router.post("/api/scenes/{scene_id}/snapshots/{snapshot_id}/pin", response_model=Snapshot)
def pin_snapshot(project: CurrentProject, scene_id: str, snapshot_id: str) -> Snapshot:
    """Flip `retention` from `thinned` to `kept` — make an automatic snapshot
    survive thinning without re-capturing it (ADR-0043 Amendment 1).

    Idempotent: pinning an already-`kept` snapshot returns it unchanged. Touches
    only the sidecar's authorial half — never the body, never the witness.
    """
    with translate_errors():
        return project.pin_snapshot(scene_id, snapshot_id)


@router.put(
    "/api/scenes/{scene_id}/snapshots/{snapshot_id}/description", response_model=Snapshot
)
def set_snapshot_description(
    project: CurrentProject,
    scene_id: str,
    snapshot_id: str,
    request: SetSnapshotDescriptionRequest,
) -> Snapshot:
    """Set (or clear) the snapshot's one-line description (#468).

    Original data the author owns, not the denormalized `title`. A sidecar
    write to the authorial half; the body and witness are frozen.
    """
    with translate_errors():
        return project.set_snapshot_description(scene_id, snapshot_id, request.description)


@router.delete("/api/scenes/{scene_id}/snapshots/{snapshot_id}", response_model=SnapshotList)
def delete_snapshot(project: CurrentProject, scene_id: str, snapshot_id: str) -> SnapshotList:
    """Remove one snapshot — the feature's only irreversible gesture, which is
    why the surface confirms it and restore does not (ADR-0043 Amendment 1).

    Both files go; returns what remains so the strip re-lists in one call.
    """
    with translate_errors():
        return project.delete_snapshot(scene_id, snapshot_id)


# ----- node-scoped routes: any node kind (ADR-0087 / #1981) -----------------
#
# The same store, addressed by node id for any kind. Each route resolves and
# authorises the node's kind via `node_snapshot_kind` (fail-closed: 404 unknown,
# 422 unsupported kind or inherited/built-in node) and hands it to the shared
# service method, whose `kind` default leaves the scene routes above unchanged.
# The record format and on-disk layout are identical; only the store root (the
# node's owning layer) and the witness (scene-only) vary by kind. A scene
# reaches the exact same store through either route.


def _node_kind(project: CurrentProject, node_id: str) -> str:
    """The node's snapshot-eligible kind, or a refusal. The store fails closed on
    kinds and layers S1 does not support — an unindexed id is a 404, an
    unsupported kind or an inherited/built-in node a 422 (see the service's
    `node_snapshot_kind`). Called inside `translate_errors`, so its
    `ProjectServiceError` becomes the HTTP status."""
    return project.node_snapshot_kind(node_id)


@router.get("/api/nodes/{node_id}/snapshots", response_model=SnapshotList)
def list_node_snapshots(project: CurrentProject, node_id: str) -> SnapshotList:
    """Every snapshot of this node, oldest first (ADR-0087)."""
    with translate_errors():
        return project.list_snapshots(node_id, kind=_node_kind(project, node_id))


@router.post("/api/nodes/{node_id}/snapshots", response_model=Snapshot)
def capture_node_snapshot(
    project: CurrentProject, node_id: str, request: CaptureSnapshotRequest | None = None
) -> Snapshot:
    """The camera for any node. `dynamic_context` is a scene concern; a
    non-scene caller sends no body and captures the bytes and record without a
    witness (ADR-0087 §5)."""
    with translate_errors():
        return project.capture_snapshot(
            node_id,
            request.dynamic_context if request is not None else None,
            kind=_node_kind(project, node_id),
        )


@router.get("/api/nodes/{node_id}/snapshots/{snapshot_id}", response_model=SnapshotDetail)
def read_node_snapshot(project: CurrentProject, node_id: str, snapshot_id: str) -> SnapshotDetail:
    """The stored body, parsed for the read-only overlay. Reading a snapshot
    never touches the live node."""
    with translate_errors():
        return project.read_snapshot(node_id, snapshot_id, kind=_node_kind(project, node_id))


@router.post("/api/nodes/{node_id}/snapshots/{snapshot_id}/restore")
def restore_node_snapshot(project: CurrentProject, node_id: str, snapshot_id: str):
    """Capture-then-restore in one call, for any node. No `response_model`: the
    restored node returns in its own shape (Scene, ResearchNote, …), which
    FastAPI cannot pick a single model for — mirrors `GET /api/nodes/{id}`."""
    with translate_errors():
        return project.restore_snapshot(node_id, snapshot_id, kind=_node_kind(project, node_id))


@router.post("/api/nodes/{node_id}/snapshots/{snapshot_id}/pin", response_model=Snapshot)
def pin_node_snapshot(project: CurrentProject, node_id: str, snapshot_id: str) -> Snapshot:
    """Flip `retention` from `thinned` to `kept` (ADR-0043 Amendment 1)."""
    with translate_errors():
        return project.pin_snapshot(node_id, snapshot_id, kind=_node_kind(project, node_id))


@router.put(
    "/api/nodes/{node_id}/snapshots/{snapshot_id}/description", response_model=Snapshot
)
def set_node_snapshot_description(
    project: CurrentProject,
    node_id: str,
    snapshot_id: str,
    request: SetSnapshotDescriptionRequest,
) -> Snapshot:
    """Set (or clear) the snapshot's one-line description (#468)."""
    with translate_errors():
        return project.set_snapshot_description(
            node_id, snapshot_id, request.description, kind=_node_kind(project, node_id)
        )


@router.delete("/api/nodes/{node_id}/snapshots/{snapshot_id}", response_model=SnapshotList)
def delete_node_snapshot(project: CurrentProject, node_id: str, snapshot_id: str) -> SnapshotList:
    """Remove one snapshot; returns what remains so the strip re-lists in one
    call. The feature's only irreversible gesture."""
    with translate_errors():
        return project.delete_snapshot(node_id, snapshot_id, kind=_node_kind(project, node_id))
