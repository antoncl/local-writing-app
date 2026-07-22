"""Scene-snapshot request/response models (ADR-0043, #401 slice 1).

These describe the **sidecar**, not the stored body: the `.md` beside it is a
byte-for-byte copy of the scene file and is never modelled, because modelling it
is the round trip through a serializer that restore exists to avoid.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# `thinned | kept`, not a boolean: `thinned` is subject to the keep-five policy,
# `kept` is not, and the field will plausibly grow a third case (ADR-0043).
Retention = Literal["thinned", "kept"]


class Snapshot(BaseModel):
    """One snapshot's own record. `id` is the snapshot's, never the source's."""

    id: str
    snapshot_of: str
    captured_at: str
    retention: Retention
    # The schema version in force at capture. Snapshots are immutable, so a
    # restore that crosses a version boundary runs the ladder over that one body
    # on the way out — the stored record is never rewritten (ADR-0043).
    schema_version: int


class SnapshotList(BaseModel):
    """Oldest first — the order the strip lays out left to right."""

    snapshots: list[Snapshot]


class SnapshotDetail(BaseModel):
    """A snapshot parsed for reading. The live buffer is untouched underneath;
    this is what the read-only overlay renders (ADR-0044 §G)."""

    snapshot: Snapshot
    title: str
    body: str
