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


# ----- the witness (ADR-0043, #439 slice 3) ----------------------------------
#
# `docs/design/snapshots-and-the-witness.md` is the reasoning; this is its shape.
# A witness records the scene's **immediate context** — the entities whose state
# the prose depends on — and is never restored, never authoritative, and never
# read by the resolver.

# Bumped when the recorded shape changes in a way that makes an older witness
# uncomparable. A snapshot carrying a different version degrades **coarsely**:
# the drift report says so rather than comparing fields whose meaning has moved.
WITNESS_VERSION = 1

# The version stamped on a witness that is present on disk but will not parse.
#
# A witness we cannot read **is** "recorded under a shape this build cannot
# read" — that is what `comparable=False` means — so it takes the same route as
# a version mismatch rather than being reported as *absent*. Absent and corrupt
# used to produce byte-identical payloads, which left the corrupt case rendering
# nothing at all: no report, no note, no sign that a comparison was attempted
# and failed. Never a real version, so it can never collide with one.
UNREADABLE_WITNESS_VERSION = 0

# What `revision` *is*. Compared as an opaque token and never inspected, but the
# token's provenance is recorded so that a redefinition (#314 makes `revision` a
# composite hash) reports the inheritance axis as **unknown** on older witnesses
# rather than as **unchanged** — ADR-0043's "degrade coarsely, never corrupt".
REVISION_KIND = "sha256_file"


class WitnessFieldType(BaseModel):
    """The type and constraints a recorded value was read through — drift axis 3.

    Scoped to **only the fields the witness recorded**, never the merged schema:
    a whole-schema hash fires on every schema edit, including the additions and
    deletions the sparse storage model already absorbs, and a detector that cries
    wolf trains the dismissal that makes the report worthless (ADR-0043).

    `label` is the field's author-facing name, carried so the report can speak
    the author's vocabulary without re-reading a schema that may since have
    dropped the field.
    """

    label: str = ""
    type: str = ""
    options: list[str] = Field(default_factory=list)


class WitnessEntity(BaseModel):
    """One entity's state as of the snapshotted scene.

    `state` is the **resolved** view — the entry's stored values with the live
    mutation overrides applied — which is what "the world that gave this prose
    its meaning" actually means. `overrides` names the subset that came from a
    mutation, so the report can attribute a change to a marker rather than to an
    edit. The body is deliberately absent: it is unbounded, and a body edit still
    reports at the floor through `revision`.
    """

    id: str
    # The entity's **effective** name at this scene (a rename mutation wins), so
    # a removed entity can still be named in the report after its file is gone.
    # Derived from `state["title"]`, never computed a second way: the two
    # spellings drifted apart the moment `title` was retyped to a collection.
    title: str = ""
    # Why this entity is in the witness: "mutation" | "entity_ref" | "dynamic".
    # Recorded rather than derived — the report distinguishes "this scene no
    # longer references Chicago" from "Chicago's entry changed".
    #
    # **Empty means "not a member of this scene's context, but resolved anyway"**
    # — the state is carried so that an entity which dropped out can still have
    # its field values compared. Membership keys on this list, not on presence.
    sources: list[str] = Field(default_factory=list)
    # Opaque change token (axis 2). `None` means it could not be read, which the
    # report must show as **unknown**, never as unchanged.
    revision: str | None = None
    revision_kind: str = REVISION_KIND
    # Axis 5: which layer the entry resolved from. Scope visibility is a property
    # of the resolved index, not of any file, so no hash over bytes can see it —
    # including the composite `revision` #314 introduces.
    #
    # The **label**, never the layer id. `_layer_id_for_folder` is a hash of the
    # resolved folder path, and `layers.py` states the invariant this would
    # break: "the cache is safe only because layer ids are never persisted… a
    # path-hash id survives neither a moved project folder nor a re-resolved
    # symlink". Storing one would make axis 5 fire on every witnessed entity of
    # every existing snapshot the first time the project folder moved.
    source_layer_label: str = ""
    state: dict[str, Any] = Field(default_factory=dict)
    overrides: list[str] = Field(default_factory=list)
    field_types: dict[str, WitnessFieldType] = Field(default_factory=dict)


class Witness(BaseModel):
    """The context captured beside one snapshot's bytes.

    A witness **describes the bytes it accompanies** and is frozen at capture —
    it is never rewritten, because a witness that drifted to the end of a session
    while the body stayed at the start would report drift the snapshotted prose
    never had.
    """

    version: int = WITNESS_VERSION
    # The entity cap fired. Reported rather than hidden: a silently truncated
    # witness reads as "nothing else changed", which is the claim it cannot make.
    truncated: bool = False
    # Which of the three sources actually contributed — "mutation",
    # "entity_ref", "dynamic".
    #
    # Load-bearing, not bookkeeping. The dynamic set only exists where a prose
    # editor supplied it, so a capture from a route that has none (the pre-restore
    # capture) records two sources, not three. Comparing that against a
    # three-source witness would otherwise report every implicitly-detected entity
    # as *removed* — a wolf cried on a scene nobody touched. Membership drift is
    # computed only over the sources **both** sides observed.
    sources_recorded: list[str] = Field(default_factory=list)
    entities: list[WitnessEntity] = Field(default_factory=list)


class Snapshot(BaseModel):
    """One snapshot's own record. `id` is the snapshot's, never the source's."""

    id: str
    snapshot_of: str
    # When the RECORD was made. Monotonic across captures, so it is what the
    # listing sorts by and what thinning calls "the oldest".
    captured_at: str
    # When the CONTENT was written — the scene file's mtime at capture.
    #
    # **The strip lays out by this one** (#458). An automatic capture fires
    # before the save, so its bytes are the previous sitting's; dating the notch
    # by `captured_at` put a fortnight-old body at "just now", and since explicit
    # captures were dated correctly the two tiers meant different things on one
    # age-laid-out track.
    #
    # Not a redefinition of `captured_at`, because the two are different facts:
    # repeated explicit captures with no edit between them share an mtime, so
    # content time ties where creation time cannot. Ordering needs the monotonic
    # one; the surface needs the honest one.
    content_written_at: str = ""
    retention: Retention
    # The author's one-line note on this snapshot (ADR-0043 Amendment 1, #468).
    #
    # Original data that exists nowhere else — deliberately **not** the
    # denormalized `title` an earlier draft carried and removed: a title is a
    # copy of something in the byte-copy's front matter, a description is the
    # author's own. Same file, opposite reasoning.
    #
    # Part of the sidecar's **mutable, authorial half** (ADR-0043 Amendment 4),
    # with `retention`. The evidentiary half — the `.md` body and the `witness`
    # — is frozen: a witness describes the bytes it accompanies, and rewriting it
    # destroys what makes it a witness. Setting a description never touches
    # either.
    description: str = ""
    # The schema version in force at capture. Snapshots are immutable, so a
    # restore that crosses a version boundary runs the ladder over that one body
    # on the way out — the stored record is never rewritten (ADR-0043).
    schema_version: int

    # **The witness is deliberately NOT a field here.** `Snapshot` is the element
    # type of `SnapshotList`, of `SnapshotDetail.snapshot` and of
    # `SnapshotDiff.snapshot`, and the strip refetches the list on every scene
    # open and after every capture and restore. Carrying the witness on that
    # model shipped up to 200 entities of resolved lore state per notch to a
    # client with no field to read it into — measured at 1.5 MB and ~1.2 s for a
    # scene with ten kept snapshots, all of it discarded.
    #
    # The witness is read from the sidecar only where it is consumed, by
    # `_read_snapshot_witness`, which touches exactly one file.


class SnapshotList(BaseModel):
    """Oldest first — the order the strip lays out left to right."""

    snapshots: list[Snapshot]


class CaptureSnapshotRequest(BaseModel):
    """The camera's request body.

    Optional in every sense: the route accepts no body at all, and an absent body
    means the dynamic context was **not observed** rather than observed-empty.
    That distinction is what stops a capture from a caller with no prose editor
    behind it from reporting every implicitly-detected entity as removed later.

    The description field is set through its own route, not here: it is the
    author's annotation of an *existing* record, not part of taking one.
    """

    dynamic_context: list[str] | None = None


class SetSnapshotDescriptionRequest(BaseModel):
    """Set (or clear, with `""`) a snapshot's one-line description (#468).

    Touches only the sidecar's authorial half — never the `.md` body and never
    the `witness` (ADR-0043 Amendment 4). A description is original data; a
    title is a copy, and this is not that.
    """

    description: str = ""


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


# ----- the drift report (ADR-0043, #439 slice 3) -----------------------------


class WitnessFieldDrift(BaseModel):
    """One field's value then versus now — drift axis 1, and the field-level
    detail for a direct edit.

    Not `FieldDiff`: that one carries the scene's own front matter through the
    compare view. This one names an **entity's** field, and carries the label and
    the attribution the report needs to say *Tom's eye colour changed from green
    to blue* rather than *a value changed*.
    """

    field_id: str
    label: str = ""
    was: Any = None
    now: Any = None
    # The value on at least one side came from a live mutation marker rather than
    # from the entry's stored value — the difference between "someone edited Tom"
    # and "a marker in another scene changed what Tom is here".
    from_mutation: bool = False


class FieldReinterpretation(BaseModel):
    """A recorded value's *meaning* moved under it — drift axis 3."""

    field_id: str
    label: str = ""
    type_was: str = ""
    type_now: str = ""
    options_was: list[str] = Field(default_factory=list)
    options_now: list[str] = Field(default_factory=list)


class EntityDrift(BaseModel):
    """Everything that changed about one entity, across the axes.

    An entity appears here only when something actually fired. An entity that
    participated in **neither** version is never manufactured into the report,
    and an entity present in both with nothing to say about it is omitted — under
    an advisory model a report that lists the unchanged trains the dismissal that
    makes it worthless.
    """

    entity_id: str
    # The author's vocabulary. For a removed entity this is the name recorded at
    # capture, which may be all that survives of it.
    title: str = ""
    # Axis 4, both directions. `present` = in both witnesses.
    membership: Literal["added", "removed", "present"] = "present"
    # Which of the three sources put it in the witness, on the side it exists.
    sources: list[str] = Field(default_factory=list)
    # Axis 2, as a tristate. `unknown` where the tokens cannot be compared
    # meaningfully — a missing token, or one computed under a different
    # definition. Never collapsed into `no`.
    entry_changed: Literal["yes", "no", "unknown"] = "no"
    fields: list[WitnessFieldDrift] = Field(default_factory=list)
    reinterpreted: list[FieldReinterpretation] = Field(default_factory=list)
    # Axis 5, populated only when the resolved layer actually moved.
    layer_was: str = ""
    layer_now: str = ""


class SnapshotDrift(BaseModel):
    """What has changed underneath a snapshot since it was taken.

    Advisory: no gate, no acknowledgement, no restore this declines to perform.

    Three states, deliberately distinguishable — `available=False` (the snapshot
    predates the witness, so there is nothing to compare), `comparable=False`
    (the witness was recorded under a shape this build cannot read), and a real
    comparison whose `entities` may legitimately be empty.
    """

    available: bool = False
    comparable: bool = True
    # Either side hit the entity cap, so "nothing else changed" is not a claim
    # this report is making.
    truncated: bool = False
    entities: list[EntityDrift] = Field(default_factory=list)


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
    #
    # `None` is "not sent", which is NOT the same as "no status". Defaulting to
    # `""` made an omitted field indistinguishable from a cleared one, so a
    # caller that simply did not send it was told the author had cleared the
    # status — a claim the compare view then displayed.
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # The lore entries the editor detected in the prose — the *dynamic context*.
    # It travels from the frontend because the frontend owns the matcher: there
    # must be exactly one implementation of alias matching, and it should be the
    # one whose results the author can see underlined. A backend rescan would
    # mean two matchers that must agree, and every disagreement between them
    # would surface as drift on a scene nobody touched.
    #
    # Always the **full set**, never a delta: a delta cannot express *Chicago is
    # gone*, which is precisely the absence-is-not-a-claim trap axis 4 exists to
    # avoid. Capped at the service, not trusted to be small.
    #
    # **`None` is "not observed", `[]` is "observed and empty"**, and the type
    # carries the distinction because the service's behaviour turns on it.
    # Defaulting to `[]` collapsed the two: `JSON.stringify` drops an omitted
    # key, so a caller with no prose editor behind it was read as one that had
    # looked and found nothing — and every implicitly-detected entity in the
    # stored witness was then reported as *removed* on a scene nobody touched.
    dynamic_context: list[str] | None = None


class SnapshotDiff(BaseModel):
    """One response serving all three view states — Both, Now and Snapshot are
    three filters over this payload, not three requests (§G)."""

    snapshot: Snapshot
    runs: list[DiffRun]
    fields: dict[str, FieldDiff]
    title_was: str
    title_now: str
    # Drift rides on the diff rather than on a route of its own. A restore is
    # only reachable from a parked notch, and parking is what fetches this — so
    # ADR-0043's "restore reports drift" is satisfied by one synchronous request
    # instead of two, and the report is already on screen when the author decides.
    drift: SnapshotDrift = Field(default_factory=SnapshotDrift)
