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

The store is **node-scoped, not scene-scoped** (ADR-0087, #1981). The same
two-file store keys on any node's canonical id; the public methods take a
`kind` — defaulting to `"manuscript"`, so every scene call is unchanged — and
resolve the store root from the node's *owning layer* (a scene's owning layer
is always the open project, so its store path stays byte-identical). A witness
(the resolved lore-context, ADR-0087 §5) is built only for a scene; other kinds
capture the bytes and the record without one.
"""

from __future__ import annotations

import os
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.models import SaveSceneRequest, Snapshot, SnapshotDetail, SnapshotList, Witness
from app.models.snapshots import UNREADABLE_WITNESS_VERSION
from app.services import migrations
from app.services.atomic_io import atomic_write_bytes
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate
from app.services.project.overrides import OVERRIDES_FOLDER

if TYPE_CHECKING:
    from app.models import LoreEntry, ResearchNote, Scene
    from app.services.project.node_index import IndexLayer

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

# A description is a one-liner (ADR-0044 §L). This caps a paste, not the
# author's intent — long enough that no real note is truncated, short enough
# that the sidecar cannot be made unbounded through this field.
SNAPSHOT_DESCRIPTION_MAX = 280

# The kinds the node-scoped routes accept today. Scenes reach the store through
# the /api/scenes routes; research (S1, #1981), lore (S2, #1983), tag (S4, #1988),
# prompt (S5a, #1990) and plot (S5b, #1992) are proven. A plot node byte-restores
# like lore/tag and heals nothing out of its own file: its beat_links/causal_links
# are denormalised onto the card and healed on READ (`_normalise_card_metadata`),
# the plot board is an opaque per-project layout recomputed from live nodes, and
# nothing else holds card membership — so the byte-write plus the index re-fold is
# the whole restore, with no owned-file rewrite (§4). Stale-on-disk links after a
# restore are the same transient state ordinary editing leaves until the next save.
NODE_SNAPSHOT_KINDS = frozenset({"manuscript", "research", "lore", "tag", "prompt", "plot"})


# Kinds whose restore reconciles correctly at ANY writable layer, so an inherited
# (ancestor-owned) base is snapshottable — not only one owned by the open project.
# lore heals nothing out of the index (§4): the byte-write plus the index re-fold
# is the whole restore. scene and research instead keep the node title in a
# separate structure document their healer rewrites in the OPEN project only
# (`_update_scene_title_in_structure` / `_update_research_title_in_structure`, both
# rooted at `_require_project()`), so restoring an ancestor-owned one would leave
# the ANCESTOR's own tree desynced from the file the restore just rewrote. Both
# stay open-project-only until that healer is owning-layer-aware — and research IS
# authored at ancestors (it is walked cross-layer), so this is a live refusal, not
# a dead branch. (Scenes are root-scoped regardless.) tag joins lore here: a tag is
# layered and heals nothing on restore — its `merged_into`/`canonical_id` re-resolve
# from the restored bytes at index-build time (§4), the reference sweep is never
# replayed — so an ancestor-owned tag restores as safely as an ancestor lore base.
# prompt joins them: it is layered and heals nothing on restore (its overrides
# re-fold at index-build time exactly like lore's), so an ancestor-owned prompt
# base is admitted.
# plot is deliberately NOT here. It is layered (a plotline/card/arc/template is
# walked cross-layer and IS readable from an ancestor), but its writes are
# book-local (`_reject_inherited_book_local` / `_reject_inherited_library_write`
# refuse editing or deleting an inherited plot node). A base restore byte-writes
# the OWNING layer's file, so admitting an inherited plot node here would let a
# downstream book rewrite the ancestor's plot canon — the write the book-local
# guard forbids. `node_snapshot_kind` refuses an inherited plot node for exactly
# this reason, keeping plot snapshots open-project-only.
ANCESTOR_RESTORE_SAFE_KINDS = frozenset({"lore", "tag", "prompt"})

# The kinds whose *overrides* (nearer-layer delta files, ADR-0087 §3b) the node
# routes can snapshot when addressed by (entity id + authoring layer). lore (S3,
# #1986) and prompt (S5a, #1990) — both override-aware; a prompt override is a
# metadata-only delta byte-identical in shape to lore's (a prompt locks its body,
# so an override never carries body bytes). An override is a sparse delta, not an
# index node, so it needs its own resolver/guard — see
# `node_override_snapshot_kind` / `_resolve_override_snapshot_target`.
OVERRIDE_SNAPSHOT_KINDS = frozenset({"lore", "prompt"})

# The reserved scope at the authoring layer that override snapshot stores nest
# under: `<authoring-layer>/.overrides/snapshots/<entity_id>/`, NOT the layer's
# plain `snapshots/<entity_id>/`. A base store is `<owning-layer>/snapshots/
# <entity_id>/`; were an override to use the plain `snapshots/`, the two would
# become the SAME directory the instant a fork or promote moved the entity's
# ownership into the authoring layer — and then a base restore would byte-write a
# delta over the base file (or an override restore a full entry over a delta),
# silent corruption. The `.overrides` scope keeps the base and override lanes
# structurally distinct for all time; like every snapshot store it is excluded
# from the index (it is not a family folder, so the node walk never globs it).
OVERRIDE_STORE_SCOPE = ".overrides"


def _owning_layer_is_writable(layer: IndexLayer | None) -> bool:
    """Whether a restore may byte-write this owning layer's file at all.

    Restore byte-writes the owning-layer file (ADR-0087 §2/§4) — structurally what
    a normal "Editing at: <layer>" save already does — so any real project layer
    qualifies: the open project or a writable ancestor. What it must never write is
    a file with no author-facing write path: the built-in Library (read-only,
    ADR-0049 #689) or the machine config layer. `layer_by_id` already drops both to
    `None` under its default flags; the explicit clauses keep the guard closed even
    if a caller widens `include_library`/`include_machine`. This is the writability
    *floor* — kind-independent; whether an inherited node of a given *kind* may be
    restored at an ancestor is the separate `ANCESTOR_RESTORE_SAFE_KINDS` gate.
    """
    return layer is not None and not layer.is_library and not layer.is_machine


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
    `_node_id_for_path`, `layer_by_id`, `_update_scene_title_in_structure`,
    `_remove_missing_scene_todo_anchors`, `_update_research_title_in_structure`,
    `read_scene`, `read_research_note`, `read_node`) resolve via MRO."""

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
            # Authorial half, absent on every snapshot taken before #468 and on
            # every one the author never annotated — the common case (ADR-0044
            # §L). Empty string, never `None`, so the field is uniform.
            description=str(data.get("description") or ""),
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

    def list_snapshots(
        self, scene_id: str, *, kind: str = "manuscript", layer_id: str | None = None
    ) -> SnapshotList:
        root, node_id, _ = self._resolve_snapshot_target(scene_id, kind, layer_id=layer_id)
        return SnapshotList(snapshots=self._snapshot_records(root, node_id))

    def read_snapshot(
        self,
        scene_id: str,
        snapshot_id: str,
        *,
        kind: str = "manuscript",
        layer_id: str | None = None,
    ) -> SnapshotDetail:
        """The stored body and normalised front-matter state, parsed for display.
        Reading is not restoring — the byte-copy is parsed here so a pane can
        render it, while restore stays a file copy.

        `title`/`status`/`metadata` come off `_snapshot_state` — the *same*
        normalisation the live side gets from `read_scene` — so the client field
        flip (#583) diffs like against like. Reusing it rather than re-deriving
        the title here keeps the was-side to one pipeline."""
        root, node_id, _ = self._resolve_snapshot_target(scene_id, kind, layer_id=layer_id)
        record = self._require_snapshot(root, node_id, snapshot_id)
        snapshots_dir = self._snapshots_dir(root, node_id)
        front_matter, body = self._read_markdown_with_front_matter(
            snapshots_dir / f"{snapshot_id}.md"
        )
        state = self._snapshot_state(front_matter, node_id, snapshots_dir)
        return SnapshotDetail(
            snapshot=record,
            title=state["title"],
            status=state["status"],
            metadata=state["metadata"],
            body=body,
        )

    def _require_snapshot(self, root: Path, node_id: str, snapshot_id: str) -> Snapshot:
        sidecar = self._snapshots_dir(root, node_id) / f"{snapshot_id}.yaml"
        body = self._snapshots_dir(root, node_id) / f"{snapshot_id}.md"
        if not sidecar.exists() or not body.exists():
            raise ProjectServiceError(f"Snapshot {snapshot_id} does not exist.", 404)
        return self._read_snapshot_record(sidecar)

    def _snapshot_store_root(self, node_id: str) -> Path:
        """The owning layer's folder — the root the snapshot store lives under.

        A snapshot freezes the *owning layer's* file, so an inherited node's
        snapshots co-locate with the layer that owns that file rather than with
        the open project (ADR-0087 §3). For a manuscript scene — always
        collected at the open project — and for any node authored in the open
        project, the owning layer *is* the open project, so this returns the
        open-project root and the store path is byte-identical to before.
        """
        root = self._require_project()
        index = self._build_node_index(root)
        # By the node's OWN id, never the merge-survivor's `canonical_id`: a
        # snapshot lives under the layer that owns *this* file. A merged (redirect)
        # tag's snapshots stay at its own layer — canonicalizing here would relocate
        # them onto the survivor's layer and strand/mis-reap the store (S4 review).
        entry = index.by_id.get(node_id)
        if entry is None or not entry.source_layer_id:
            return root
        layer = self.layer_by_id(root, entry.source_layer_id)
        return layer.folder if layer is not None else root

    def _resolve_snapshot_target(
        self, ref: str, kind: str, *, layer_id: str | None = None
    ) -> tuple[Path, str, Path | None]:
        """`(store root, canonical node id, node file path)` for a snapshot op.

        `ref` may be a structure node's id; `_path_for_node_id` normalises it to
        the file and `_node_id_for_path` to that file's front-matter id — the id
        the store is keyed by, which are not always the same. `kind` selects the
        family the id is resolved in (a node route knows the kind from the index;
        the scene routes default to `"manuscript"`). The one resolver every
        public method shares, replacing the manuscript-only source-id lookup and
        the `_require_project()` root each method used to take on its own (one
        traversal, not six).

        When `layer_id` is given the target is a *book override* delta (§3b),
        addressed by (entity id + authoring layer) rather than by an index node —
        `_resolve_override_snapshot_target`; `path` is then `None` when no
        override exists at that layer yet.
        """
        if layer_id is not None:
            return self._resolve_override_snapshot_target(ref, layer_id)
        path = self._path_for_node_id(ref, kind)
        node_id = self._node_id_for_path(path)
        return self._snapshot_store_root(node_id), node_id, path

    def _resolve_override_snapshot_target(
        self, entity_id: str, layer_id: str
    ) -> tuple[Path, str, Path | None]:
        """`(store root, entity id, override delta path | None)` for an override
        snapshot op (ADR-0087 §3b).

        A book override is a sparse delta file, deliberately **not** a node in the
        index, so it cannot be reached by id. It is addressed by the same
        coordinates the "Editing at" save uses — the entity's canonical id + the
        authoring layer. The store roots at the **authoring** layer's folder (not
        the base entity's owning layer), keyed by the entity id, so the book's
        override history sits under the book, apart from the series base's own
        (§3). `path` is `_override_file_for_target` — `None` when no override
        exists at this layer (a capture then has nothing to photograph; a restore
        recreates it).
        """
        root = self._require_project()
        layer = self.layer_by_id(root, layer_id)
        if layer is None:
            raise ProjectServiceError("Unknown authoring layer.", 422)
        node_id = self._build_node_index(root).canonical_id(entity_id)
        # Store root = the authoring layer's reserved `.overrides` scope, so the
        # override lane never aliases the base lane at the same layer (see
        # OVERRIDE_STORE_SCOPE). The delta file itself lives at the real layer
        # folder's `overrides/`, resolved here from `layer.folder`.
        store_root = layer.folder / OVERRIDE_STORE_SCOPE
        return store_root, node_id, self._override_file_for_target(layer.folder, node_id)

    def node_snapshot_kind(self, node_id: str) -> str:
        """Resolve a node id to its kind for the node-scoped routes, or refuse.

        The node routes **fail closed** on two axes the scene-only predecessor
        never had to guard, because a scene is always root-scoped and writable:

        - **Kind.** Only the kinds the store is proven for are accepted; each
          remaining kind opens in a later slice, together with the cross-layer
          write semantics its restore needs (ADR-0087 rollout).
        - **Owning layer.** Two gates, because restore byte-writes the
          owning-layer file in place. First it must be author-*writable* — the
          open project or a writable ancestor (`_owning_layer_is_writable`); a
          built-in Library (read-only, ADR-0049 #689) or machine node is refused.
          Then an *inherited* node (owned by an ancestor) is admitted only for a
          kind whose restore reconciles at that ancestor
          (`ANCESTOR_RESTORE_SAFE_KINDS`): lore heals nothing (§4), but a
          scene/research restore rewrites only the open project's structure tree,
          which would desync the ancestor's — so those stay open-project-only
          until their healer is owning-layer-aware. (A book *override* — a delta
          file, not an index node — is S3; this guard sees only base index nodes.)
        """
        root = self._require_project()
        index = self._build_node_index(root)
        # By the node's OWN id, never the merge-survivor's `canonical_id`: a
        # snapshot op addresses this node's own file/history/layer (a merged tag is
        # snapshotted at its own layer, not the survivor's — S4 review).
        entry = index.by_id.get(node_id)
        if entry is None:
            raise ProjectServiceError(f"Node {node_id} does not exist.", 404)
        if entry.kind not in NODE_SNAPSHOT_KINDS:
            raise ProjectServiceError(
                f"Snapshots are not available for {entry.kind} nodes yet.", 422
            )
        layer = self.layer_by_id(root, entry.source_layer_id)
        if not _owning_layer_is_writable(layer):
            raise ProjectServiceError(
                "Snapshots of a built-in or machine node are not supported.", 422
            )
        if not layer.is_root and entry.kind not in ANCESTOR_RESTORE_SAFE_KINDS:
            raise ProjectServiceError(
                f"Snapshots of an inherited {entry.kind} node are not supported yet.",
                422,
            )
        return entry.kind

    def node_override_snapshot_kind(self, entity_id: str, layer_id: str) -> str:
        """Resolve `(entity, authoring layer)` to the entity's kind for the
        override snapshot routes (ADR-0087 §3b), or refuse.

        The override's kind is the **base entity's** kind, read from its index
        node (the entity is always an index node even when a nearer layer
        overrides it, §3b) — `lore` (S3) and `prompt` (S5a). Writability is checked on the
        **authoring** layer, because that is the layer whose delta file a restore
        byte-writes (not the base's owning layer, which an ancestor holds). The
        authoring layer must be strictly *below* the owning layer — a layer at or
        above it does not override the entry, it authors or inherits it — so a
        built-in Library / machine layer (never a valid override layer) and the
        owning layer itself are refused.
        """
        root = self._require_project()
        index = self._build_node_index(root)
        entry = index.by_id.get(index.canonical_id(entity_id))
        if entry is None:
            raise ProjectServiceError(f"Node {entity_id} does not exist.", 404)
        if entry.kind not in OVERRIDE_SNAPSHOT_KINDS:
            raise ProjectServiceError(
                f"Override snapshots are not available for {entry.kind} nodes yet.", 422
            )
        layer = self.layer_by_id(root, layer_id)
        if not _owning_layer_is_writable(layer):
            raise ProjectServiceError(
                "Snapshots at a built-in or machine layer are not supported.", 422
            )
        owning = self.layer_by_id(root, entry.source_layer_id)
        if owning is None or layer.rank <= owning.rank:
            raise ProjectServiceError("That layer does not override this entry.", 422)
        return entry.kind

    # ----- capture ----------------------------------------------------------

    def capture_snapshot(
        self,
        scene_id: str,
        dynamic_context: list[str] | None = None,
        *,
        kind: str = "manuscript",
        layer_id: str | None = None,
    ) -> Snapshot:
        """The camera: an explicit, never-thinned capture of the current state."""
        root, node_id, path = self._resolve_snapshot_target(scene_id, kind, layer_id=layer_id)
        if path is None:
            # An override target (§3b) with no delta at this layer: there is no
            # authored file to photograph. Override a field first, then snapshot it.
            raise ProjectServiceError("There is no override at this layer to snapshot.", 404)
        return self._capture(
            root, node_id, path, retention="kept", dynamic_context=dynamic_context, kind=kind
        )

    def _capture(
        self,
        root: Path,
        node_id: str,
        path: Path,
        *,
        retention: str,
        dynamic_context: list[str] | None = None,
        kind: str = "manuscript",
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
        # The witness is scene-only (ADR-0087 §5): it resolves lore-context from
        # scene-shaped inputs (entity_ref fields, in-prose mutation markers, the
        # editor's detected set). Another kind has nothing to witness, so no
        # `witness` key is written and a later comparison reports none rather
        # than an all-clear from a build that saw nothing.
        witness = self.build_witness(node_id, dynamic_context) if kind == "manuscript" else None
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
            "schema_version": migrations.CURRENT_VERSION,
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
        self,
        ref: str,
        *,
        kind: str = "manuscript",
        layer_id: str | None = None,
        dynamic_context: list[str] | None = None,
    ) -> None:
        """Called from a save path **before** the new body is written.

        The rule (ADR-0043 Amendment 2): on a save, if the last save to this
        node was longer ago than `SESSION_GAP_MINUTES`, capture the pre-save
        state first. The backend needs nothing new for this — it already has the
        file, its modification time and the save.

        The target is resolved through the same `(ref, kind, layer_id)` surface
        the explicit camera uses (`_resolve_snapshot_target`), so a base node, an
        inherited node owned by an ancestor, and a book override delta all reach
        the right store with one traversal — the auto-camera and the camera share
        their aim. `kind` is forwarded to `_capture`, so a witness is built only
        for a scene (`kind == "manuscript"`); every other kind has nothing
        scene-shaped to witness. An override target with no delta at this layer
        yet resolves to a `path` of `None` (the first override of a field):
        there is nothing to photograph, so this returns — the silent no-op a
        missing file gets, not the 404 the explicit camera raises.

        *Last save is the file's mtime.* It needs no new state. The writes that
        could make it lie were audited and do not: a rename preserves mtime, and
        structure writes touch the structure YAML, not the node file. What does
        refresh it — a marker rewrite, an embedded-todo edit, a schema-driven
        metadata rewrite — are writes to this node's own file, so counting them
        as a save is right rather than merely tolerated. The **one** refresher
        that is not an author save is the reference sweep a tag delete/merge runs
        (`_purge_references_to` / `_rewrite_references_from_to`), which rewrites a
        carrier node's own front matter in place. That bumps mtime without an
        author edit, so the *next* genuine session-boundary save may find a fresh
        mtime and skip its capture. It fails safe — the file is intact, only the
        "what it looked like when I sat down" photo is missed, never a spurious
        or empty one — and a scene has always carried the same exposure.

        A missing file is not an error here: a capture is never the reason a
        save fails.

        **One imprecision, accepted deliberately.** The bytes are the pre-edit
        state, but `dynamic_context` (a scene's witness input) is the set the
        editor holds *now* — it describes the body about to be written, since the
        author has been typing for up to one save interval before this fires.
        Exact agreement would need the backend to retain the previous session's
        last set across the gap and across restarts. The error is bounded by one
        save rather than by the session, and it is self-correcting.
        """
        store_root, node_id, path = self._resolve_snapshot_target(ref, kind, layer_id=layer_id)
        if path is None or not path.exists():
            return
        last_save = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if (datetime.now(UTC) - last_save).total_seconds() <= SESSION_GAP_MINUTES * 60:
            return
        self._capture(
            store_root, node_id, path, retention="thinned", dynamic_context=dynamic_context, kind=kind
        )

    # ----- restore ----------------------------------------------------------

    def restore_snapshot(
        self,
        scene_id: str,
        snapshot_id: str,
        *,
        kind: str = "manuscript",
        layer_id: str | None = None,
    ) -> Scene | ResearchNote | LoreEntry:
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
        root, node_id, path = self._resolve_snapshot_target(scene_id, kind, layer_id=layer_id)
        record = self._require_snapshot(root, node_id, snapshot_id)

        if layer_id is not None:
            # A book override (§3b): write the delta back and re-fold, not the
            # base-file byte-write-plus-structural-patch below.
            return self._restore_override(root, node_id, snapshot_id, path, kind)

        # No dynamic context: this route has no prose editor behind it, so the
        # implicit set is *not observed* rather than empty. The witness records
        # two sources, and a later comparison narrows membership to what both
        # sides saw instead of reporting every detected entity as removed.
        stored = self._snapshots_dir(root, node_id) / f"{snapshot_id}.md"
        # Read the frozen snapshot BEFORE the capture-first below: that capture is
        # `thinned` and runs `_thin`, which can evict this very snapshot when it is
        # one of the oldest automatic ones — reading after would raise on a restore
        # of an old thinned snapshot and lose it.
        if record.schema_version == migrations.CURRENT_VERSION:
            # ADR-0043: prose is restored byte-exact when the snapshot is already
            # at the current schema (the common case).
            frozen_bytes = stored.read_bytes()
            migrated = None
        else:
            # ADR-0071 §7: the snapshot predates the current schema — migrate its
            # body over one document on the way out, leaving the immutable stored
            # record untouched. Today the document subladder is empty, so this
            # branch is unreachable in practice; it is wired for the first
            # post-gateway content migration, with no new call-site to remember.
            front_matter, body = self._read_markdown_with_front_matter(stored, strict=True)
            migrated = migrations.migrate_document(
                migrations.MigratableDocument(front_matter, body), record.schema_version
            )

        self._capture(root, node_id, path, retention="thinned", kind=kind)

        if migrated is None:
            self._atomic_write_bytes(path, frozen_bytes)
        else:
            self._write_markdown_with_front_matter(path, migrated.front_matter, migrated.body)
        # (unchanged below) — the explicit structural index write still runs for
        # both branches; the byte branch bypassed the write hook, the migrate
        # branch's `_write_markdown_with_front_matter` also went through it, and
        # re-running the structural patch is idempotent.
        #
        # `_atomic_write_bytes` deliberately bypasses the text writer, so it also
        # bypasses the change-gate hook on `_atomic_write` — a restore that
        # changed the scene's title, entry_type, or a reference field would
        # otherwise leave the in-memory node index describing the pre-restore
        # state (#392). Restore is always structural (the content is replaced).
        self._apply_index_write((path,), structural=True)

        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        # The filename stays as it is — it is cosmetic, and reads resolve by id.
        # The structure title is not: it is what the manuscript tree renders, so
        # a restore that changed the title has to reach it.
        self._heal_after_restore(kind, node_id, str(front_matter.get("title") or node_id), body)
        return self._read_restored_node(kind, node_id)

    def _heal_after_restore(self, kind: str, node_id: str, title: str, body: str) -> None:
        """Re-sync the out-of-index structure a restore may have changed.

        A restore replaces the file's bytes, which can change the node's title
        (and, for a scene, drop an embedded todo anchor). Only two kinds keep a
        copy of the node title in a *separate* structure document the index
        write does not touch — a scene (`manuscript.structure.yaml`) and a
        research note (`research.structure.yaml`); lore/prompt/tag/plot keep no
        such duplicate and heal nothing beyond the structural index write
        (ADR-0087 §4). Dispatched by kind rather than always calling the scene
        healers, which would look up a manuscript tree a research restore has no
        node in.
        """
        if kind == "manuscript":
            self._update_scene_title_in_structure(node_id, title)
            self._remove_missing_scene_todo_anchors(node_id, body)
        elif kind == "research":
            self._update_research_title_in_structure(node_id, title)

    def _read_restored_node(self, kind: str, node_id: str) -> Scene | ResearchNote:
        """Read the just-restored node back in its own shape.

        `read_node` (node_ops) dispatches every kind *except* research, so a
        research restore reads through `read_research_note` directly; a scene
        keeps its own `read_scene` so the scene route's `Scene` response model
        is unchanged. Any other kind (S2+) falls through to the unified reader.
        """
        if kind == "manuscript":
            return self.read_scene(node_id)
        if kind == "research":
            return self.read_research_note(node_id)
        return self.read_node(node_id)

    def _restore_override(
        self, root: Path, node_id: str, snapshot_id: str, path: Path | None, kind: str
    ) -> LoreEntry:
        """Restore a book-override delta (ADR-0087 §3b): write the frozen delta
        back and return the re-folded composite the book shows.

        Captures-first when a current delta exists — a reverted-to-canon override
        has none, and there is nothing to lose. An override delta carries no
        schema_version and no migration ladder, so it is always restored
        byte-exact. The write opts out of incremental indexing (an override-bearing
        chain rebuilds cold), so the memo is invalidated rather than structurally
        patched, and the next read re-folds the composite (§4). No heal, no
        witness: lore heals nothing, and a delta has nothing scene-shaped to
        witness.
        """
        stored = self._snapshots_dir(root, node_id) / f"{snapshot_id}.md"
        # Read the frozen bytes BEFORE the capture-first: that capture is `thinned`
        # and runs `_thin`, which can evict this very snapshot when it is one of the
        # oldest automatic ones (the read-after-thin footgun the base path shares).
        frozen = stored.read_bytes()
        if path is not None:
            self._capture(root, node_id, path, retention="thinned", kind=kind)
            target = path
        else:
            # Reverted-to-canon since capture (no current delta ⇒ no capture-first
            # ran, so `stored` still exists); recreate the delta at the authoring
            # layer before writing the frozen bytes back.
            target = self._recreate_override_path(root, stored)
        self._atomic_write_bytes(target, frozen)
        node_index_gate.invalidate()
        return self.read_node(node_id)

    def _recreate_override_path(self, store_root: Path, stored: Path) -> Path:
        """Mint a delta-file path when restoring an override reverted-to-canon
        since capture. The filename is cosmetic — the `target` front-matter key is
        the join — so it derives from the frozen snapshot's own title, the shape
        `_write_override_file` mints. The delta lives at the real layer folder's
        `overrides/`, which is the parent of the override store scope (`store_root`
        = `<layer>/.overrides`).
        """
        front_matter, _ = self._read_markdown_with_front_matter(stored, strict=True)
        title = str(front_matter.get("title") or "override")
        return self._filepath_for_new_node(store_root.parent / OVERRIDES_FOLDER, title)

    def finalize_scene(
        self, scene_id: str, body: str, dynamic_context: list[str] | None = None
    ) -> Scene:
        """Project a roleplay scene to its finished prose (ADR-0070 S3), in place.

        Like `restore_snapshot`, this captures FIRST and overwrites second, in one
        operation — a failure between the two leaves an extra snapshot and an
        untouched scene, never the reverse. The projection is destructive (the
        scene is the only record of the beats + interiority; there is no node
        holding a richer copy), so the snapshot is the safety net.

        The capture is `kept`, not `thinned`: a finalize is a deliberate,
        once-per-scene act, and its safety net must never be evicted by the
        keep-last-five policy the way an ordinary session snapshot can be.

        `body` is the AI-produced clean prose; everything else on the scene
        (title, status, entry_type, metadata — including `pov`) is preserved. The
        write goes through `save_scene`, so front matter, the manuscript title,
        the node index and TODO anchors update exactly as an ordinary save.
        """
        root = self._require_project()
        path = self._path_for_node_id(scene_id, "manuscript")
        node_id = self._node_id_for_path(path)
        current = self.read_scene(node_id)
        # Safety net BEFORE the destructive projection (see docstring).
        self._capture(root, node_id, path, retention="kept", dynamic_context=dynamic_context)
        return self.save_scene(
            scene_id,
            SaveSceneRequest(
                title=current.title,
                body=body,
                status=current.status,
                entry_type=current.entry_type,
                metadata=current.metadata,
                dynamic_context=dynamic_context,
            ),
        )

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        """`_atomic_write` for bytes. Restore must not go through the text
        writer: encoding, newline translation and the front-matter writer's
        normalisation are each a way for "byte-for-byte" to stop being true.
        Durable (#480): a restore replaces the live scene, and a snapshot is
        "the only durable before the app has" — so the bytes must survive a
        power cut, not just reach the page cache. Skips the change-gate hook
        `_atomic_write` carries; the caller notifies the index explicitly."""
        atomic_write_bytes(path, data)

    # ----- author gestures: pin · describe (ADR-0043 Amdt 1/4, #468) --------
    #
    # A snapshot's sidecar has two halves. The **evidentiary** half — the
    # `witness`, `captured_at`, `content_written_at`, `schema_version`, `id`,
    # `snapshot_of` — is frozen, because a witness describes the bytes it
    # accompanies and rewriting it destroys what makes it a witness. The
    # **authorial** half — `retention` and `description` — is the author's
    # control over the record, and `_mutate_sidecar` is the only place it moves.
    # Neither gesture opens the `.md`; the byte-copy is never touched.

    def _mutate_sidecar(
        self, root: Path, node_id: str, snapshot_id: str, **changes: Any
    ) -> Snapshot:
        """Rewrite only the named authorial keys of one sidecar.

        Every other key — the `witness` among them — is read and written back
        unchanged, so its content survives whole (`_write_yaml` is
        `sort_keys=False`, so the frozen block keeps its shape as well as its
        meaning). The scene body is never opened. This is the boundary ADR-0043
        Amendment 4 draws made mechanical: the method physically cannot alter
        anything but the keys it is handed, and it is only ever handed
        `retention` and `description`.
        """
        self._require_snapshot(root, node_id, snapshot_id)
        sidecar = self._snapshots_dir(root, node_id) / f"{snapshot_id}.yaml"
        data = self._read_yaml(sidecar)
        data.update(changes)
        self._write_yaml(sidecar, data)
        return self._read_snapshot_record(sidecar)

    def pin_snapshot(
        self, scene_id: str, snapshot_id: str, *, kind: str = "manuscript", layer_id: str | None = None
    ) -> Snapshot:
        """Flip `retention` from `thinned` to `kept` — the third case the enum
        was chosen for (ADR-0043 Amendment 1).

        An automatic snapshot the author notices is worth keeping does not have
        to be re-captured to become permanent. One-directional: there is no
        unpin, because `kept` is exactly "not subject to thinning" and there is
        no distinct 'this was captured explicitly' state to fall back to —
        letting a `kept` record become `thinned` again would put an explicit
        capture at risk of the very thinning the tier exists to escape.

        Pinning an already-`kept` snapshot is a no-op, so the gesture is
        idempotent and a double click cannot error.

        **Pinning frees an automatic slot, and that is intended, not a leak.**
        `_thin` keeps the last `AUTOMATIC_KEEP` *thinned* records and `kept`
        ones never count, so pinning the oldest automatic makes room for one
        more automatic on the next capture. The budget is a window over a set
        the author can now take things out of.
        """
        root, node_id, _ = self._resolve_snapshot_target(scene_id, kind, layer_id=layer_id)
        record = self._require_snapshot(root, node_id, snapshot_id)
        if record.retention == "kept":
            return record
        return self._mutate_sidecar(root, node_id, snapshot_id, retention="kept")

    def set_snapshot_description(
        self,
        scene_id: str,
        snapshot_id: str,
        description: str,
        *,
        kind: str = "manuscript",
        layer_id: str | None = None,
    ) -> Snapshot:
        """Set (or clear, with `""`) the one-line description (#468).

        Collapsed to a single line and trimmed: it is a one-liner by contract
        (ADR-0044 §L), and a stored newline would break the tooltip and the
        actions-row label that render it. Capped so a paste cannot make the
        sidecar unbounded.
        """
        root, node_id, _ = self._resolve_snapshot_target(scene_id, kind, layer_id=layer_id)
        cleaned = " ".join(description.split())[:SNAPSHOT_DESCRIPTION_MAX]
        return self._mutate_sidecar(root, node_id, snapshot_id, description=cleaned)

    # ----- deletion ---------------------------------------------------------

    def delete_snapshot(
        self, scene_id: str, snapshot_id: str, *, kind: str = "manuscript", layer_id: str | None = None
    ) -> SnapshotList:
        """Remove one snapshot — the only irreversible gesture in the feature.

        Both files go, or the leftover is exactly the unreachable residue
        ADR-0043 rejects: a `.md` nothing lists, or a sidecar with no body to
        view or restore. Returns what remains, so the strip re-lists in one call.

        Thinning is untouched by the gap this leaves. `_thin` counts the
        *thinned* records that exist at capture time, so removing one now simply
        means the next automatic capture has one more slot before it evicts —
        the same window, over a smaller set. There is no undelete: scene and
        lore deletes are already hard deletes, and a feature that quietly
        retained data after a delete would be the only such thing in the project.
        """
        root, node_id, _ = self._resolve_snapshot_target(scene_id, kind, layer_id=layer_id)
        self._require_snapshot(root, node_id, snapshot_id)
        folder = self._snapshots_dir(root, node_id)
        (folder / f"{snapshot_id}.md").unlink(missing_ok=True)
        (folder / f"{snapshot_id}.yaml").unlink(missing_ok=True)
        remaining = self._snapshot_records(root, node_id)
        if not remaining:
            # The last one goes with its directory. "Both files go" has to mean
            # the store is back to how it was before the first capture, or every
            # scene the author ever snapshotted and then cleared leaves an empty
            # folder behind — the residue ADR-0043 rejects, in miniature.
            # `rmdir` refuses a non-empty directory, so an unexpected file is
            # left in place rather than swept up with the record.
            with suppress(OSError):
                folder.rmdir()
        return SnapshotList(snapshots=remaining)

    def delete_scene_snapshots(self, root: Path, node_id: str) -> None:
        """A scene and its snapshots are one unit of deletion (ADR-0043).

        Keeping them would leave exactly the unreachable residue that ADR
        rejects: the directory is named by node id, the author knows scenes by
        title, and once the scene is gone there is no node left to hang an
        affordance on.
        """
        shutil.rmtree(self._snapshots_dir(root, node_id), ignore_errors=True)

    def delete_override_snapshots(self, layer_folder: Path, entity_id: str) -> None:
        """Reap a layer's override snapshot store for an entity (ADR-0087 §3b) —
        the override-lane twin of `delete_scene_snapshots`.

        Called only where an override lane becomes *permanently* unreachable: a
        fork-to-here moves ownership onto this layer, so `node_override_snapshot_kind`
        refuses (authoring == owning) and `<layer>/.overrides/snapshots/<E>` can no
        longer be listed or restored. Reaping it keeps ADR-0043's "a node and its
        snapshots are one unit" honest on the override lane. It is **not** called on
        a revert-to-canon (that store is the restore-after-revert recovery path) or
        on promotion (the lane stays reachable and is re-written), which is why the
        reap lives at the ownership-transfer site and not in the shared
        `_drop_layer_overrides_for_target` those transitions also route through.

        The override lane is keyed by the entity's *canonical* id — the same key its
        writer uses (`_resolve_override_snapshot_target`), and unlike the base lane,
        which keys by the node's own id — so canonicalise to match, or a reap by a
        raw id would `rmtree` nothing and leave the real store behind.
        """
        canonical = self._build_node_index().canonical_id(entity_id)
        self.delete_scene_snapshots(layer_folder / OVERRIDE_STORE_SCOPE, canonical)
