"""Mid-scene lore mutations slice of ProjectService (GH #33, #50; ADR-0095).

Since ADR-0095, a mutation is a `mutation_set` node row joined at the scene
anchor that places it — the scene keeps only a one-line comment at the point
of change:

    <!-- mutate:set=<set-id>;id=<anchor-id> -->

and a matching close, ending the anchor's changes wholesale or one row of them
(`row=`):

    <!-- mutate:close;ref=<anchor-id>[;row=<row-id>];id=<close-id> -->

The grammar itself (`MUTATION_ANCHOR_PATTERN` / `MUTATION_ANCHOR_CLOSE_PATTERN`)
lives in `mutation_anchors.py`, shared with the legacy→sets-and-anchors
converter. This module joins each anchor with its set (`_SetView`, read once
per index build) into one `MutationMarker` record per row — the resolved
record `(anchor id, row id)` identity ADR-0095 §3 describes.

The RETIRED single-line/carrier inline grammar (ADR-0001/ADR-0016) is no
longer read here — `legacy_mutation_markers.py` is now its only reader, for
the migration and for restoring a pre-ADR-0095 snapshot (§11, §12).

Unlike embedded todos an anchor wraps **no prose** — it is a point marker
whose position within the scene body is semantically load-bearing (prose before
it sees the old value, prose after it the new; ADR-0003). The scene is
authoritative and the anchor travels with the prose, so moving/deleting a scene
moves/deletes its anchors with it — no orphan management for the *anchor*
(ADR-0001); the *set* stays, staged, until its last anchor is gone (ADR-0095 §7).

This mixin owns the anchor scan, the set join and the resolver. The project-wide
index and the effective-state resolver live here (#51); `ProjectService`
composes this mixin, and shared helpers (`read_scene`, `_path_for_node_id`,
`_write_scene_file`, `_build_node_index`) resolve via MRO.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from app.models import (
    MutationMarker,
    MutationMarkerList,
    MutationSetRow,
    Scene,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.lore_mutation_items import (
    ItemRecord,
    KeyedList,
    fold_keyed_items,
    keyed_lists_from,
    list_record,
    member_record,
    split_member_path,
)
from app.services.project.markers import MarkerMixin
from app.services.project.mutation_anchors import (
    MUTATION_ANCHOR_CLOSE_PATTERN,
    MUTATION_ANCHOR_PATTERN,
)
from app.services.project.node_index import NodeIndex
from app.services.tree_structure import TreeStructureService

# Field types whose values are collections; these accept add/remove ops (#58).
COLLECTION_FIELD_TYPES = frozenset({"multi_select", "entity_ref_list"})

# Scalar text types that accept an additive `add` (append) op: the effective
# value is the base (or latest live replace) with live adds concatenated in
# start order — a space between text fragments, a paragraph break for
# long_text. `remove` stays collection-only; every other type is replace-only.
TEXT_APPEND_FIELD_TYPES = frozenset({"text", "long_text"})

# Sentinel position: resolve at end of scene (every in-scene marker counts as
# live). Only the inline handler's `selection` destination passes a real cursor
# offset; every other surface resolves at end-of-scene (ADR-0003).
END_OF_SCENE: int | None = None

# Node-intrinsic fields a mutation may target that are not schema fields: the
# entry's own title/body. Free text, so no value constraints to validate.
INTRINSIC_MUTABLE_FIELDS = frozenset({"title", "body"})


def _split_collection_value(value: str) -> list[str]:
    """Split a whole-collection `replace` marker value (comma-joined, mirroring
    the frontend's `String(array)` serialization) into its elements."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_str_list(value: object) -> list[str]:
    """Coerce a stored base field value to a list of non-empty strings — a real
    list (multi_select/tags/entity_ref_list base) or a comma-joined string."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return _split_collection_value(value)
    return []


def _last_replace_index(live: list[MutationMarker]) -> int:
    """Index of the latest `replace` in a manuscript-ordered live-record list, or
    -1 if none. A replace resets the base and moots every earlier add/remove, so
    resolution only applies the records after this index."""
    for i in range(len(live) - 1, -1, -1):
        if live[i].op == "replace":
            return i
    return -1


@dataclass
class MutationClose:
    """A parsed close anchor (#59, ADR-0095 §1) — ends the record(s) `ref`
    names at this prose point. Manuscript position is resolved during index
    build. `row` "" ends every row of the anchor's set; a given `row` ends
    only the record `f"{ref}.{row}"` (ADR-0095 §3)."""

    close_id: str
    ref: str
    scene_id: str
    row: str = ""
    offset: int = 0
    line: int = 1


@dataclass
class MutationsIndex:
    """Project-wide mutation index (#51). Rebuildable from scene files; each
    entity's list is pre-ordered by manuscript position then prose offset, so
    the resolver slices O(applicable) rather than re-scanning. `version` changes
    whenever any marker changes, letting the AI cache layer key volatile lore on
    it instead of the (now-insufficient) lore file revision (ADR-0006).

    `closes_by_start` maps a start marker id → the (manuscript-position, offset)
    of the governing close for it (#59), so the resolver can bound each record's
    interval without re-scanning."""

    version: str = ""
    by_entity: dict[str, list[MutationMarker]] = dc_field(default_factory=dict)
    scene_order: dict[str, int] = dc_field(default_factory=dict)
    closes_by_start: dict[str, tuple[int, int]] = dc_field(default_factory=dict)


@dataclass
class _Fold:
    """Working state of one `effective_state` call: the result under
    construction plus the lazily-read base values, field types and
    reference-keyed lists, and the item records set aside for the per-key
    fold (ADR-0089 §3)."""

    entity_id: str
    idx: MutationsIndex
    field_types: dict[str, str] | None
    effective: dict[str, str | list[str] | list[dict[str, Any]]] = dc_field(default_factory=dict)
    base: dict[str, object] | None = None
    keyed: dict[str, KeyedList] | None = None
    item_records: dict[str, list[ItemRecord]] = dc_field(default_factory=dict)


@dataclass
class _SetView:
    """A `mutation_set` node's read, resolved once per index build (ADR-0095
    §2/§5) — the join target for every anchor naming it. `usable` is False for
    a set with no pin, or a dead pin (names no existing lore entry): an anchor
    to either contributes nothing (§5)."""

    set_id: str
    entity_id: str  # the pin (`target_entity`); "" when unpinned
    title: str
    target_entry_type: str
    rows: list[MutationSetRow]
    revision: str
    pin_missing: bool
    usable: bool


class LoreMutationsMixin(MarkerMixin):
    def _scan_scene_mutations(self, scene: Scene) -> Iterator[MutationMarker]:
        """Yield every resolved mutation record in one scene body, in prose
        order — the single per-scene scan the index (#51) walks. Builds its
        own set lookup; callers resolving many scenes should build one with
        `_mutation_set_views` and call `_iter_body_mutations` directly."""
        sets = self._mutation_set_views(self._build_node_index())
        yield from self._iter_body_mutations(scene.body, scene.id, sets)

    def _iter_body_closes(self, body: str, scene_id: str) -> Iterator[MutationClose]:
        """Regex-walk one raw body for close anchors (#59, ADR-0095 §1)."""
        return self._scan_body_markers(
            body,
            MUTATION_ANCHOR_CLOSE_PATTERN,
            lambda match, line: MutationClose(
                close_id=match.group("id"),
                ref=match.group("ref"),
                scene_id=scene_id,
                row=match.group("row") or "",
                offset=match.start(),
                line=line,
            ),
        )

    def _mutation_set_views(self, index: NodeIndex) -> dict[str, _SetView]:
        """Every `mutation_set` node belonging to the OPEN project layer, read
        once per index build (ADR-0095 §2/§5/§10). A set found only in an
        ancestor layer is not in this lookup — `index.by_id` resolves to the
        winning (innermost) entry per id, so its path lives outside the open
        project's `mutation-sets/` folder, and it never joins here; an anchor
        naming it is therefore missing, as an anchor across layers must be
        (§10)."""
        root = self._require_project()
        folder = (root / "mutation-sets").resolve()
        views: dict[str, _SetView] = {}
        for entry in index.by_id.values():
            if entry.kind != "mutation_set" or entry.path.parent != folder:
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            target_entity = self._mutation_set_target_entity(front_matter)
            pin_missing = self._mutation_set_pin_missing(index, target_entity)
            views[entry.id] = _SetView(
                set_id=entry.id,
                entity_id=target_entity,
                title=str(front_matter.get("title") or ""),
                target_entry_type=str(front_matter.get("target_entry_type") or ""),
                rows=self._parse_mutation_set_rows(front_matter.get("rows")),
                revision=self._revision(entry.path),
                pin_missing=pin_missing,
                usable=bool(target_entity) and not pin_missing,
            )
        return views

    def _iter_body_mutations(
        self, body: str, scene_id: str, sets: dict[str, _SetView]
    ) -> Iterator[MutationMarker]:
        """Regex-walk one raw body for anchors (ADR-0095 §1), yielding one
        record per row of the anchored set, in prose order. Split from
        `_scan_scene_mutations` so validation (#53) and drift checks can scan
        a body they already read against a set lookup they already built,
        without re-scanning the node index per scene.

        An anchor whose set is not in `sets` (missing, or only in another
        layer, §10) or not `usable` (no pin, or a dead pin, §2) contributes no
        records. Duplicate-anchor-id suppression (§3) is a whole-project
        concern and is applied by `build_mutations_index`, not here — this
        method yields every anchor's records regardless of repeats."""
        for match in MUTATION_ANCHOR_PATTERN.finditer(body):
            view = sets.get(match.group("set_id"))
            if view is None or not view.usable:
                continue
            anchor_id = match.group("id")
            line = body[: match.start()].count("\n") + 1
            for row in view.rows:
                yield MutationMarker(
                    marker_id=f"{anchor_id}.{row.id}",
                    entity_id=view.entity_id,
                    field=row.field,
                    op=row.op,
                    value=row.value,
                    name=view.title,
                    unit_id=anchor_id,
                    unit_name=view.title,
                    anchor_id=anchor_id,
                    set_id=view.set_id,
                    row_id=row.id,
                    scene_id=scene_id,
                    offset=match.start(),
                    line=line,
                )

    # ----- value coercion (#53) -----------------------------------------

    def _coerce_mutation_value(self, value: str, field_type: str) -> object:
        """Coerce a marker's url-decoded string to the field's native type so the
        base-value validator sees what it expects. Uncoercible input is left as
        the string, letting the validator flag it (e.g. "must be a number").

        For a collection field this is the field-type-aware boundary that splits
        a whole-`replace` marker's comma-joined value back into a `list[str]`
        (ADR-0009) — the resolver returns collection add/remove results as lists
        directly, but can't classify a pure-replace field without the schema, so
        the split happens here where the type is known."""
        if value == "":
            return value
        if field_type in COLLECTION_FIELD_TYPES:
            return _split_collection_value(value)
        if field_type == "number":
            try:
                return int(value) if re.fullmatch(r"-?\d+", value) else float(value)
            except ValueError:
                return value
        if field_type == "boolean":
            lowered = value.strip().lower()
            if lowered in {"true", "false"}:
                return lowered == "true"
            return value
        return value

    # ----- index + resolver (#51) ----------------------------------------

    def _scene_order(self) -> dict[str, int]:
        """Map each scene id to its manuscript position (depth-first document
        order: act → chapter → scene). Scenes not linked into the manuscript
        tree have no manuscript position and are absent."""
        try:
            structure = self.read_structure()
        except ProjectServiceError:
            return {}
        order: dict[str, int] = {}
        for node in TreeStructureService.collect(structure.root):
            if node.scene_id and node.scene_id not in order:
                order[node.scene_id] = len(order)
        return order

    def _scene_body_for_scan(self, index: NodeIndex, scene_id: str) -> str | None:
        """The raw body of one manuscript scene, for the marker scan and nothing
        else (#440).

        Deliberately **not** `read_scene`. The scanner consumes the body and the
        id; `read_scene` additionally resolves computed metadata — which reads
        the whole structure *per scene*, making the index quadratic — and
        validates, which made a scene carrying a value its schema no longer
        allows drop out of the index silently, taking its close markers with it
        and changing resolved state across the rest of the manuscript.
        """
        entry = index.by_id.get(scene_id)
        if entry is not None and entry.kind == "manuscript":
            path = entry.path
        else:
            try:
                path = self._path_for_node_id(scene_id, "manuscript")
            except ProjectServiceError:
                return None
        try:
            _, body = self._read_markdown_with_front_matter(path)
        except OSError:
            return None
        return body

    def build_mutations_index(
        self, scene_body_overrides: dict[str, str] | None = None
    ) -> MutationsIndex:
        """Walk every manuscript scene in order, scanning its anchors, joining
        each with its set (ADR-0095 §5) into a per-entity list ordered by
        (manuscript position, prose offset). Rebuildable cache over scene
        files — mirrors `_build_node_index` (compute-on-demand); persist to
        `.cache/` only if it ever gets slow (§3.3).

        `scene_body_overrides` substitutes the given body for a scene's on-disk
        one — the buffer a caller already holds, for a scene whose autosave has
        not landed (#581, the snapshot-drift now-witness). A scene mapped to an
        override is scanned from that text; an empty override is a scene the
        author just cleared of markers, not a scene to read from disk, so it is
        honoured (not treated as "missing").

        An anchor id that repeats an earlier one (manuscript order: scene
        order, then offset) contributes nothing — the first resolves, later
        ones are duplicates (§3) — decided here, across every scene, not in
        the single-body `_iter_body_mutations`.
        """
        overrides = scene_body_overrides or {}
        scene_order = self._scene_order()
        scene_paths = self._scene_display_paths()
        index = self._build_node_index()
        sets = self._mutation_set_views(index)
        bodies: dict[str, str] = {}
        anchor_hits: list[tuple[int, int, str, str, str]] = []  # (pos, offset, scene_id, anchor_id, set_id)
        closes: list[MutationClose] = []
        for scene_id, pos in scene_order.items():
            body = overrides[scene_id] if scene_id in overrides else self._scene_body_for_scan(index, scene_id)
            if body is None:
                continue
            bodies[scene_id] = body
            for match in MUTATION_ANCHOR_PATTERN.finditer(body):
                anchor_hits.append((pos, match.start(), scene_id, match.group("id"), match.group("set_id")))
            closes.extend(self._iter_body_closes(body, scene_id))
        anchor_hits.sort(key=lambda hit: (hit[0], hit[1]))
        by_entity: dict[str, list[MutationMarker]] = {}
        seen_anchor_ids: set[str] = set()
        for _pos, offset, scene_id, anchor_id, set_id in anchor_hits:
            if anchor_id in seen_anchor_ids:
                continue
            seen_anchor_ids.add(anchor_id)
            view = sets.get(set_id)
            if view is None or not view.usable:
                continue
            line = bodies[scene_id][:offset].count("\n") + 1
            for row in view.rows:
                marker = MutationMarker(
                    marker_id=f"{anchor_id}.{row.id}",
                    entity_id=view.entity_id,
                    field=row.field,
                    op=row.op,
                    value=row.value,
                    name=view.title,
                    unit_id=anchor_id,
                    unit_name=view.title,
                    anchor_id=anchor_id,
                    set_id=set_id,
                    row_id=row.id,
                    scene_id=scene_id,
                    offset=offset,
                    line=line,
                    scene_path=scene_paths.get(scene_id, ""),
                )
                by_entity.setdefault(marker.entity_id, []).append(marker)
        for records in by_entity.values():
            records.sort(key=lambda m: (scene_order.get(m.scene_id, 0), m.offset))
        closes_by_start = self._resolve_closes(closes, by_entity, scene_order)
        return MutationsIndex(
            version=self._mutations_version(by_entity, closes_by_start, anchor_hits, sets),
            by_entity=by_entity,
            scene_order=scene_order,
            closes_by_start=closes_by_start,
        )

    @staticmethod
    def _resolve_closes(
        closes: list[MutationClose],
        by_entity: dict[str, list[MutationMarker]],
        scene_order: dict[str, int],
    ) -> dict[str, tuple[int, int]]:
        """Map each RECORD id → the (manuscript-position, offset) of its
        governing close: the earliest close positioned at/after the record's
        start (#59). A close before its start marks an empty interval, so it
        is ignored; a close whose scene isn't in the manuscript is dropped.

        A close without `row=` governs every record of its anchor
        (`ref == anchor_id`, ADR-0095 §1); with `row=`, only the one record
        `f"{ref}.{row}"`."""
        start_pos: dict[str, tuple[int, int]] = {}
        records_by_anchor: dict[str, list[str]] = {}
        for records in by_entity.values():
            for m in records:
                if m.scene_id not in scene_order:
                    continue
                start_pos[m.marker_id] = (scene_order[m.scene_id], m.offset)
                records_by_anchor.setdefault(m.anchor_id, []).append(m.marker_id)
        governing: dict[str, tuple[int, int]] = {}
        for close in closes:
            if close.scene_id not in scene_order:
                continue
            close_at = (scene_order[close.scene_id], close.offset)
            targets = [f"{close.ref}.{close.row}"] if close.row else records_by_anchor.get(close.ref, [])
            for record_id in targets:
                start = start_pos.get(record_id)
                if start is None or close_at < start:
                    continue
                current = governing.get(record_id)
                if current is None or close_at < current:
                    governing[record_id] = close_at
        return governing

    def entity_mutations(self, entity_id: str) -> MutationMarkerList:
        """The manuscript-ordered mutation timeline for one entity (#54) — the
        pre-ordered per-entity slice of the index, for the lore-card list."""
        index = self.build_mutations_index()
        return MutationMarkerList(items=list(index.by_entity.get(entity_id, [])))

    def effective_names(
        self, scene_id: str, index: MutationsIndex | None = None
    ) -> dict[str, list[str]]:
        """Each lore entry's **effective** name-set (title + aliases) as of the
        end of `scene_id` — the primitive the effective-name-aware matcher (#61)
        needs. A renamed entity resolves under its as-of-scene name; unmutated
        entries return their base names. Resolution is **scene-granular** (the
        end-of-scene name-set covers the whole scene; ADR-0008 amended).

        Pass a prebuilt `index` when the caller already has one. Building it is
        the expensive part (1.16 s on a 600-scene manuscript), and a request that
        both resolves names and resolves state would otherwise pay for it twice —
        count the re-derivations of a shared traversal before adding a consumer."""
        index = index if index is not None else self.build_mutations_index()
        names: dict[str, list[str]] = {}
        try:
            entries = self.list_lore_entries().entries
        except ProjectServiceError:
            return {}
        # The schema is identical across every entry — read it once and thread it
        # in, rather than re-parsing it inside each per-entry effective_state.
        field_types = self._mutation_field_types()
        for summary in entries:
            entity_id = getattr(summary, "id", "")
            if not entity_id:
                continue
            overrides = self.effective_state(
                entity_id, scene_id, index=index, field_types=field_types
            )
            # A live title mutation wins even when it blanks the name (an
            # intentional rename to empty); only fall back to the base title
            # when no title mutation is in play (`or` would swallow "").
            if "title" in overrides:
                title = str(overrides["title"] or "").strip()
            else:
                title = str(getattr(summary, "title", "") or "").strip()
            metadata = getattr(summary, "metadata", {}) or {}
            if "aliases" in overrides:
                aliases = _as_str_list(overrides["aliases"])
            else:
                aliases = _as_str_list(metadata.get("aliases"))
            name_set = [name for name in [title, *aliases] if name]
            if name_set:
                names[entity_id] = name_set
        return names

    def live_mutations(
        self,
        entity_id: str,
        scene_id: str,
        position: int | None = END_OF_SCENE,
        index: MutationsIndex | None = None,
    ) -> MutationMarkerList:
        """The entity's start records still **open** (live, not yet closed) at
        (scene, position) — the source for the `/mutate close` picker (#59). Base
        records have no marker id and aren't included (they're not closeable)."""
        idx = index or self.build_mutations_index()
        records = idx.by_entity.get(entity_id) or []
        target_pos = idx.scene_order.get(scene_id)
        if target_pos is None:
            return MutationMarkerList(items=[])
        live = [
            marker
            for marker in records
            if self._marker_is_live(
                marker,
                idx.scene_order,
                target_pos,
                position,
                idx.closes_by_start.get(marker.marker_id),
            )
        ]
        return MutationMarkerList(items=live)

    def effective_state(
        self,
        entity_id: str,
        scene_id: str,
        position: int | None = END_OF_SCENE,
        index: MutationsIndex | None = None,
        exclude: frozenset[str] | set[str] = frozenset(),
        field_types: dict[str, str] | None = None,
    ) -> dict[str, str | list[str] | list[dict[str, Any]]]:
        """Effective mutation overrides for `entity_id` as of (scene, position).

        Returns only the fields carrying a **live** mutation, each mapped to its
        winning value; the caller overlays these onto the entry's base field
        values (ADR-0003, ADR-0006). Scalar fields resolve to a **string** —
        among the records live at (scene, position), the latest-started replace
        wins. Collection fields (multi_select / entity_ref_list) resolve to a
        **`list[str]`** = `(base ∪ live adds) ∖ live removes`, remove-wins
        (ADR-0009); the datatype matches the field. Text fields (text /
        long_text, incl. intrinsic title/body) additionally accept `add` as
        **append**: base (or latest live replace) + live adds in start order,
        space-joined for text, paragraph-joined for long_text (ADR-0009
        amendment). A reference-keyed list (ADR-0089 §3) resolves to its
        **items**, a `list[dict]`: the records for the list field and for its
        `<field>.<target id>.<member>` paths fold into one value, positional per
        key, and the member paths never appear in the result.

        A record is live iff its start is at or before the resolution point in
        manuscript order — earlier scene always, same scene only if its marker
        sits at/before `position` (so prose before a marker sees the old value,
        prose after it the new). `position=END_OF_SCENE` counts every in-scene
        marker as live. Pass a prebuilt `index` to resolve many entries without
        re-scanning.

        `exclude` skips a record whose `marker_id` OR `anchor_id` is in it — the
        list-edit authoring baseline (ADR-0017): re-editing an anchor's set
        diffs against the effective value WITHOUT that anchor's own rows, so
        the diff cannot count itself (ADR-0095 §3).

        `field_types` (field id -> type) may be passed to resolve many entries
        without re-reading the schema per call (see `effective_names`); when
        omitted it is read lazily, once, on the first add/remove op or the first
        record that may address a list."""
        idx = index or self.build_mutations_index()
        records = idx.by_entity.get(entity_id)
        if not records:
            return {}
        target_pos = idx.scene_order.get(scene_id)
        if target_pos is None:
            # Scene not in the manuscript → no manuscript position → base only.
            return {}
        live_by_field = self._live_records_by_field(
            idx, records, target_pos, position, exclude
        )
        fold = _Fold(entity_id, idx, field_types)
        for field, live in live_by_field.items():
            if not self._take_item_records(fold, field, live):
                self._fold_flat_field(fold, field, live)
        self._fold_item_records(fold)
        return fold.effective

    def _take_item_records(self, fold: _Fold, field: str, live: list[MutationMarker]) -> bool:
        """Set aside the records that address a reference-keyed list — the list
        field's own `add`/`remove` (and an ignored whole-list replace) or a
        `<field>.<target id>.<member>` path — for the per-key fold. False when
        the field is anything else, so it resolves as a flat field."""
        if "." not in field and not any(m.op in {"add", "remove"} for m in live):
            # A replace-only field: only a `list` can still be a keyed list
            # (whose whole-list replace is ignored, §2); anything else is flat.
            if fold.field_types is None:
                fold.field_types = self._mutation_field_types()
            if fold.field_types.get(field) != "list":
                return False
        if fold.keyed is None:
            fold.keyed = self._keyed_lists()
        target = fold.keyed.get(field)
        if target is not None:
            fold.item_records.setdefault(field, []).extend(list_record(target, m) for m in live)
            return True
        path = split_member_path(field, fold.keyed) if "." in field else None
        if path is None:
            return False
        target, key, member = path
        fold.item_records.setdefault(target.field_id, []).extend(
            member_record(m, key, member) for m in live
        )
        return True

    def _fold_flat_field(self, fold: _Fold, field: str, live: list[MutationMarker]) -> None:
        """Resolve one scalar, text or flat-collection field (ADR-0009): a
        collection set-fold or a text append when an add/remove is live, else
        the latest-started replace — `live` is pre-sorted, so its last record."""
        if not any(m.op in {"add", "remove"} for m in live):
            fold.effective[field] = live[-1].value
            return
        # add/remove needs the entry's base value and the field's type
        # (collection set-resolve vs text append). Both read lazily, once,
        # only when such an op is in play.
        base = self._fold_base(fold)
        if fold.field_types is None:
            fold.field_types = self._mutation_field_types()
        field_type = fold.field_types.get(field, "text")
        if field_type in COLLECTION_FIELD_TYPES:
            fold.effective[field] = self._resolve_collection(field, live, base)
        else:
            fold.effective[field] = self._resolve_text_append(field, field_type, live, base)

    def _fold_item_records(self, fold: _Fold) -> None:
        """Fold every reference-keyed list's records onto its base items,
        positional per key (ADR-0089 §3), keys matched through the node
        index's `canonical_id` so a record written against a merged-away id
        still finds its item (§1)."""
        if not fold.item_records or fold.keyed is None:
            return
        base = self._fold_base(fold)
        for field_id, item_records in fold.item_records.items():
            item_records.sort(
                key=lambda r: (fold.idx.scene_order.get(r.marker.scene_id, 0), r.marker.offset)
            )
            fold.effective[field_id] = fold_keyed_items(
                base.get(field_id),
                fold.keyed[field_id],
                item_records,
                self._coerce_mutation_value,
                self._canonical_key,
            )

    def _fold_base(self, fold: _Fold) -> dict[str, object]:
        if fold.base is None:
            fold.base = self._entity_base_values(fold.entity_id)
        return fold.base

    def _keyed_lists(self) -> dict[str, KeyedList]:
        """The reference-keyed lists the (cached) schema declares; empty on a
        read failure, so their records then resolve as any unknown field's."""
        try:
            return keyed_lists_from(self.read_metadata_schema())
        except ProjectServiceError:
            return {}

    def _canonical_key(self, key: str) -> str:
        """An item key through the node index's `canonical_id`, so a record
        written against an id later merged away still finds its item
        (ADR-0089 §1); identity when no index can be read."""
        try:
            return self._build_node_index().canonical_id(key)
        except ProjectServiceError:
            return key

    def _live_records_by_field(
        self,
        idx: MutationsIndex,
        records: list[MutationMarker],
        target_pos: int,
        position: int | None,
        exclude: frozenset[str] | set[str],
    ) -> dict[str, list[MutationMarker]]:
        """Group the records live at the resolution point by field. `records`
        is pre-sorted ascending, so each field's last entry is the latest
        started (the replace winner). A record is excluded when its
        `anchor_id` OR its `marker_id` is in `exclude` (ADR-0095 §3): a caller
        re-editing a unit at a stop excludes the whole anchor, wherever the
        set is otherwise addressed by record id."""
        live_by_field: dict[str, list[MutationMarker]] = {}
        for marker in records:
            if marker.marker_id in exclude or marker.anchor_id in exclude:
                continue
            close = idx.closes_by_start.get(marker.marker_id)
            if self._marker_is_live(marker, idx.scene_order, target_pos, position, close):
                live_by_field.setdefault(marker.field, []).append(marker)
        return live_by_field

    def _mutation_field_types(self) -> dict[str, str]:
        """field id -> type for mutation resolution: the schema's fields plus
        the intrinsic title (text) / body (long_text). Empty schema on a read
        failure — unknown fields then resolve as plain text."""
        types = {"title": "text", "body": "long_text"}
        try:
            schema = self.read_metadata_schema()
        except ProjectServiceError:
            return types
        for field_id, field in (getattr(schema, "fields", None) or {}).items():
            types[field_id] = getattr(field, "type", "text")
        return types

    def _entity_base_values(self, entity_id: str) -> dict[str, object]:
        """The entry's stored (book-start) values for add/remove resolution:
        its metadata plus the intrinsic title/body (text appends may target
        them). Empty on any read failure (resolution then treats base as
        empty)."""
        try:
            entry = self.read_lore_entry(entity_id)
        except ProjectServiceError:
            return {}
        values = dict(getattr(entry, "metadata", {}) or {})
        values.setdefault("title", getattr(entry, "title", "") or "")
        values.setdefault("body", getattr(entry, "body", "") or "")
        return values

    @staticmethod
    def _resolve_collection(
        field: str, live: list[MutationMarker], base: dict[str, object]
    ) -> list[str]:
        """Resolve one collection field: `(base ∪ live adds) ∖ live removes`,
        remove-wins, set-deduped, order-stable (base order, then adds in start
        order). A live whole-`replace` resets the base to its own value first —
        and supersedes any earlier add/remove: `live` is in manuscript order, so
        only adds/removes authored AFTER the latest replace still apply."""
        cut = _last_replace_index(live)
        if cut >= 0:
            base_list = _split_collection_value(live[cut].value)
        else:
            base_list = _as_str_list(base.get(field))
        tail = live[cut + 1 :]
        removes = {m.value for m in tail if m.op == "remove"}
        result: list[str] = []
        seen: set[str] = set()
        for item in [*base_list, *(m.value for m in tail if m.op == "add")]:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
        return [item for item in result if item not in removes]

    @staticmethod
    def _resolve_text_append(
        field: str, field_type: str, live: list[MutationMarker], base: dict[str, object]
    ) -> str:
        """Resolve one text field with live appends: base text (or the latest
        live whole-`replace`, which resets it — same rule as collections) plus
        live adds in start order. Fragments join with a space for `text`, a
        paragraph break for `long_text`. Empty fragments drop out. Only appends
        authored AFTER the latest replace survive it (`live` is manuscript-ordered)."""
        cut = _last_replace_index(live)
        base_text = live[cut].value if cut >= 0 else str(base.get(field) or "")
        adds = [m.value for m in live[cut + 1 :] if m.op == "add"]
        separator = "\n\n" if field_type == "long_text" else " "
        # Stored bodies end in a newline; trim fragment edges so the separator
        # alone spaces the joints (inner newlines are preserved).
        return separator.join(
            part.strip() for part in [base_text, *adds] if part.strip()
        )

    def _marker_is_live(
        self,
        marker: MutationMarker,
        scene_order: dict[str, int],
        target_pos: int,
        position: int | None,
        close: tuple[int, int] | None = None,
    ) -> bool:
        marker_pos = scene_order.get(marker.scene_id)
        if marker_pos is None or marker_pos > target_pos:
            return False
        if marker_pos == target_pos and not (
            position is END_OF_SCENE or marker.offset <= position
        ):
            return False  # same scene, cursor before the marker → not yet started
        # Started (start ≤ target). A close narrows the upper bound: live iff the
        # resolution point is strictly before the close (exclusive, #59).
        return close is None or self._target_before_close(close, target_pos, position)

    @staticmethod
    def _target_before_close(
        close: tuple[int, int], target_pos: int, position: int | None
    ) -> bool:
        close_pos, close_offset = close
        if close_pos > target_pos:
            return True  # close is in a later scene
        if close_pos < target_pos:
            return False  # close already passed
        # Same scene as the resolution point: end-of-scene sits at/after any
        # in-scene close; a cursor is before it iff its offset is smaller.
        if position is END_OF_SCENE:
            return False
        return position < close_offset

    def _mutations_version(
        self,
        by_entity: dict[str, list[MutationMarker]],
        closes_by_start: dict[str, tuple[int, int]],
        anchor_hits: list[tuple[int, int, str, str, str]],
        sets: dict[str, _SetView],
    ) -> str:
        """Changes when a set's rows/title/pin change (its rows already flow
        into each record's field/op/value/name; its own revision is hashed
        too, so a save that leaves resolution unchanged still bumps the
        version — harmless, cache-only) or when anchors move, are added,
        removed, or a set's usability flips (`anchor_hits` covers every
        anchor found, not only the ones that ended up contributing records)."""
        digest = hashlib.sha1()  # noqa: S324 - cache key, not security
        for entity_id in sorted(by_entity):
            for marker in by_entity[entity_id]:
                digest.update(
                    f"{entity_id}\x1f{marker.scene_id}\x1f{marker.offset}"
                    f"\x1f{marker.field}\x1f{marker.op}\x1f{marker.value}"
                    f"\x1f{marker.name}\x1f{marker.marker_id}"
                    f"\x1f{marker.anchor_id}\x1f{marker.set_id}\x1f{marker.row_id}\x1e".encode()
                )
        for start_id in sorted(closes_by_start):
            close_pos, close_offset = closes_by_start[start_id]
            digest.update(f"close\x1f{start_id}\x1f{close_pos}\x1f{close_offset}\x1e".encode())
        for _pos, _offset, scene_id, anchor_id, set_id in sorted(anchor_hits, key=lambda h: (h[2], h[3])):
            view = sets.get(set_id)
            revision = view.revision if view else ""
            usable = view.usable if view else False
            digest.update(
                f"anchor\x1f{scene_id}\x1f{anchor_id}\x1f{set_id}"
                f"\x1f{revision}\x1f{usable}\x1e".encode()
            )
        return digest.hexdigest()[:16]

