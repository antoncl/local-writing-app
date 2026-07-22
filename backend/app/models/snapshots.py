"""Scene-snapshot request/response models (ADR-0043, #401 slice 1).

These describe the **sidecar**, not the stored body: the `.md` beside it is a
byte-for-byte copy of the scene file and is never modelled, because modelling it
is the round trip through a serializer that restore exists to avoid.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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


# ----- the compare view (ADR-0044 §F/§G, #409) -------------------------------


class DiffRun(BaseModel):
    """One provenance-tagged fragment of markdown, in reading order.

    `equal` belongs to both states; `now` exists only in the scene as it is;
    `was` exists only in the snapshot. Warm and cool respectively — the colour
    says which version the text belongs to, and everything else falls out of
    that one rule.

    Amendment 1: the text is always a **complete markdown fragment**, and the
    run is either inline-within-one-block or block-spanning, never both.
    """

    kind: Literal["equal", "now", "was"]
    text: str
    # The run spans block boundaries, so no inline element can wrap it: the
    # frontend wraps it around the *rendered* output instead of injecting a
    # wrapper into the source. §F's stacked layout, carried by the run.
    stacked: bool = False


class FieldDiff(BaseModel):
    """One field's two values. Deliberately not a diff — a field value is
    atomic, so §F has fields flip rather than interleave."""

    was: Any = None
    now: Any = None


class SnapshotDiffRequest(BaseModel):
    """The live state, sent rather than read from disk.

    Autosave lags the buffer by up to six seconds, so the file is not reliably
    what the author is looking at; and parking on a notch is a *reading*
    gesture, which must not write. §G's "the endpoint takes two node states",
    read literally.
    """

    body: str = ""
    title: str = ""
    # `status` travels beside `metadata` because that is how the scene file
    # stores it — top-level in front matter, not inside the field map — while
    # the rail renders it as one field row among the others. The flip has to
    # cover what the rail shows.
    status: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SnapshotDiff(BaseModel):
    """One response serving all three view states — Both, Now and Snapshot are
    three filters over this payload, not three requests (§G)."""

    snapshot: Snapshot
    runs: list[DiffRun]
    fields: dict[str, FieldDiff]
    title_was: str
    title_now: str
