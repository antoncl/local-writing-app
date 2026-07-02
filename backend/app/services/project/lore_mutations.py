"""Mid-scene lore mutations slice of ProjectService (GH #33, #50).

A mutation is a self-contained HTML-comment marker living inline in scene
markdown, carrying the new value at the point of change:

    <!-- mutate:entity=<lore-id>;field=<field-key>;value=<url-encoded>;id=<marker-id> -->

v1.1 extends the grammar with three forward-compatible optional attributes
(absent on v1.0 markers, so old markers parse unchanged):

    ;op=<add|remove|replace>   collection operator (#58); absent ⇒ replace
    ;name=<url-encoded>        human label for the change (#65)
    ;group=<group-id>          co-authored-set tie for a shared name (#65, legacy)

Canonical order is `entity;field;op?;value;name?;group?;id`.

The mutation-unit rework (#69, ADR-0016) adds the **carrier** form: one authored
change touching N fields is ONE multi-line comment — a head (entity, optional
name, unit id) plus one `field=` row per line, each row keeping its own id:

    <!-- mutate:entity=<lore-id>[;name=<url-encoded>];id=<unit-id>
    field=<key>[;op=<op>];value=<url-encoded>;id=<row-id>
    -->

The single-line marker is the **degenerate one-row form** of that grammar, not a
legacy case: rendering emits it for one-row units (head folded into the sole
row, unit id dropped), the carrier for ≥ 2 rows. Rows stay independent records —
the unit is authoring/presentation granularity, never lifetime granularity
(ADR-0002 holds). Every record carries `unit_id`/`unit_name`: its own id for a
standalone single-line marker, the shared `group=` for legacy co-authored sets
(subsumed; still parses, never re-emitted by new authoring), the head id for
carrier rows. `close;ref=<unit-id>` is index-time sugar that ends every live row
of the unit — expanded in `_resolve_closes` to per-row ends that merely coincide.

Unlike embedded todos this marker wraps **no prose** — it is a point marker
whose position within the scene body is semantically load-bearing (prose before
it sees the old value, prose after it the new; ADR-0003). The scene is
authoritative and the marker travels with the prose, so moving/deleting a scene
moves/deletes its mutations with it — no orphan management (ADR-0001).

This mixin owns the marker pattern and the per-scene scan; the atomic
single-marker rewrite/remove machinery (without a full body save) is shared with
the other in-prose marker kinds via `MarkerMixin`. The project-wide index and the
effective-state resolver that read these markers live in a separate slice (#51).
`ProjectService` composes it; shared helpers (`read_scene`, `_path_for_node_id`,
`_write_scene_file`) resolve via MRO.

`MUTATION_MARKER_PATTERN` lives here (its single home, alongside the code that
rewrites markers with it), mirroring `EMBEDDED_TODO_PATTERN`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field
from urllib.parse import quote, unquote

from app.models import (
    MutationMarker,
    MutationMarkerList,
    Scene,
    UpdateMutationRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.markers import MarkerMixin

MUTATION_MARKER_PATTERN = re.compile(
    r"<!--\s*mutate:entity=(?P<entity>[A-Za-z0-9_-]+);field=(?P<field>[A-Za-z0-9_.-]+);"
    r"(?:op=(?P<op>add|remove|replace);)?"
    r"value=(?P<value>[^;\s]*)"
    r"(?:;name=(?P<name>[^;\s]*))?"
    r"(?:;group=(?P<group>[A-Za-z0-9_-]+))?"
    r";id=(?P<id>[A-Za-z0-9_-]+)\s*-->",
)

# Carrier marker (#69, ADR-0016): head line + one field row per line. The rows
# capture is deliberately loose (whole lines) — each line is re-matched against
# MUTATION_CARRIER_ROW_PATTERN, and a carrier with ANY malformed row does not
# parse as a unit at all (stays an inert comment), so a rewrite can never
# silently drop a hand-authored line it failed to understand.
MUTATION_CARRIER_PATTERN = re.compile(
    r"<!--[ \t]*mutate:entity=(?P<entity>[A-Za-z0-9_-]+)"
    r"(?:;name=(?P<name>[^;\s]*))?"
    r";id=(?P<id>[A-Za-z0-9_-]+)[ \t]*\r?\n"
    r"(?P<rows>(?:[ \t]*field=[^\r\n]*\r?\n)+)"
    r"[ \t]*-->",
)

MUTATION_CARRIER_ROW_PATTERN = re.compile(
    r"field=(?P<field>[A-Za-z0-9_.-]+);"
    r"(?:op=(?P<op>add|remove|replace);)?"
    r"value=(?P<value>[^;\s]*)"
    r";id=(?P<id>[A-Za-z0-9_-]+)",
)

# Field types whose values are collections; these accept add/remove ops (#58).
COLLECTION_FIELD_TYPES = frozenset({"multi_select", "tags", "entity_ref_list"})

# Scalar text types that accept an additive `add` (append) op: the effective
# value is the base (or latest live replace) with live adds concatenated in
# start order — a space between text fragments, a paragraph break for
# long_text. `remove` stays collection-only; every other type is replace-only.
TEXT_APPEND_FIELD_TYPES = frozenset({"text", "long_text"})

# Interval-close marker (#59): a separate point marker at the close position that
# ends the record `ref` — the record is live iff `start ≤ pos < close` (close
# exclusive, ADR-0010). Op-agnostic; carries its own id so it edits/deletes like
# any marker. Distinct grammar from a start marker (`close;ref=` vs `entity=`),
# so the two patterns never overlap.
MUTATION_CLOSE_PATTERN = re.compile(
    r"<!--\s*mutate:close;ref=(?P<ref>[A-Za-z0-9_-]+);id=(?P<id>[A-Za-z0-9_-]+)\s*-->",
)

# Sentinel position: resolve at end of scene (every in-scene marker counts as
# live). Only `replace_selection` passes a real cursor offset; every other
# surface resolves at end-of-scene (ADR-0003).
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


def _render_mutation_marker(
    entity: str, field: str, op: str, value: str, name: str, group: str, marker_id: str
) -> str:
    """Assemble a mutation marker in canonical order (`entity;field;op?;value;
    name?;group?;id`), omitting optional attributes at their defaults so v1.0
    markers round-trip byte-stable. `value` and `name` are already url-encoded."""
    parts = [f"entity={entity}", f"field={field}"]
    if op and op != "replace":
        parts.append(f"op={op}")
    parts.append(f"value={value}")
    if name:
        parts.append(f"name={name}")
    if group:
        parts.append(f"group={group}")
    parts.append(f"id={marker_id}")
    return f"<!-- mutate:{';'.join(parts)} -->"


@dataclass
class CarrierRow:
    """One `field=` row of a carrier marker (#69), value kept url-encoded
    verbatim so untouched rows round-trip byte-stable through a rewrite."""

    field: str
    op: str  # "replace" when the marker omits op=
    raw_value: str
    row_id: str


def _parse_carrier_rows(match: re.Match[str]) -> list[CarrierRow] | None:
    """Parse a carrier match's row block. `None` when any row is malformed —
    the whole comment then stays an inert (never-rewritten) comment."""
    rows: list[CarrierRow] = []
    for line in match.group("rows").splitlines():
        text = line.strip()
        if not text:
            continue
        row = MUTATION_CARRIER_ROW_PATTERN.fullmatch(text)
        if row is None:
            return None
        rows.append(
            CarrierRow(
                field=row.group("field"),
                op=row.group("op") or "replace",
                raw_value=row.group("value"),
                row_id=row.group("id"),
            )
        )
    return rows or None


def _render_carrier_row(row: CarrierRow) -> str:
    parts = [f"field={row.field}"]
    if row.op and row.op != "replace":
        parts.append(f"op={row.op}")
    parts.append(f"value={row.raw_value}")
    parts.append(f"id={row.row_id}")
    return ";".join(parts)


def _render_mutation_unit(
    entity: str, raw_name: str, unit_id: str, rows: list[CarrierRow]
) -> str:
    """Render a unit in canonical form: the multi-line carrier for ≥ 2 rows, the
    degenerate single-line marker for one (head folded into the sole row — the
    unit id drops away and the row id is the marker id, so an edit that leaves
    one row deterministically canonicalizes back to single-line; ADR-0016)."""
    if len(rows) == 1:
        row = rows[0]
        return _render_mutation_marker(
            entity, row.field, row.op, row.raw_value, raw_name, "", row.row_id
        )
    head = [f"entity={entity}"]
    if raw_name:
        head.append(f"name={raw_name}")
    head.append(f"id={unit_id}")
    lines = [
        f"<!-- mutate:{';'.join(head)}",
        *(_render_carrier_row(row) for row in rows),
        "-->",
    ]
    return "\n".join(lines)


@dataclass
class MutationClose:
    """A parsed interval-close marker (#59) — ends the start record `ref` at this
    prose point. Manuscript position is resolved during index build."""

    close_id: str
    ref: str
    scene_id: str
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


class LoreMutationsMixin(MarkerMixin):
    def _scan_scene_mutations(self, scene: Scene) -> Iterator[MutationMarker]:
        """Yield every mutation marker in one scene body, in prose order,
        carrying each marker's char offset (needed for position-granular
        resolution). The single per-scene scan the index (#51) walks."""
        yield from self._iter_body_mutations(scene.body, scene.id)

    def _iter_body_closes(self, body: str, scene_id: str) -> Iterator[MutationClose]:
        """Regex-walk one raw body for interval-close markers (#59)."""
        return self._scan_body_markers(
            body,
            MUTATION_CLOSE_PATTERN,
            lambda match, line: MutationClose(
                close_id=match.group("id"),
                ref=match.group("ref"),
                scene_id=scene_id,
                offset=match.start(),
                line=line,
            ),
        )

    def _iter_body_mutations(self, body: str, scene_id: str) -> Iterator[MutationMarker]:
        """Regex-walk one raw body for markers — single-line AND carrier (#69) —
        yielding one per-row record each, merged into prose order. Split from
        `_scan_scene_mutations` so validation (#53) can scan a body it already
        read (front-matter walk) without materializing a Scene.

        Every record carries `unit_id`/`unit_name` (ADR-0016): own id for a
        standalone marker, the legacy `group=` for co-authored sets, the head id
        for carrier rows. Carrier rows share the carrier's prose offset — the
        unit is one prose point, so its rows resolve together (ADR-0003)."""

        def single(match: re.Match[str], line: int) -> list[MutationMarker]:
            name = unquote(match.group("name") or "")
            return [
                MutationMarker(
                    marker_id=match.group("id"),
                    entity_id=match.group("entity"),
                    field=match.group("field"),
                    op=match.group("op") or "replace",
                    value=unquote(match.group("value")),
                    name=name,
                    group=match.group("group") or "",
                    unit_id=match.group("group") or match.group("id"),
                    unit_name=name,
                    scene_id=scene_id,
                    offset=match.start(),
                    line=line,
                )
            ]

        def carrier(match: re.Match[str], line: int) -> list[MutationMarker]:
            rows = _parse_carrier_rows(match)
            if rows is None:
                return []
            unit_name = unquote(match.group("name") or "")
            return [
                MutationMarker(
                    marker_id=row.row_id,
                    entity_id=match.group("entity"),
                    field=row.field,
                    op=row.op,
                    value=unquote(row.raw_value),
                    unit_id=match.group("id"),
                    unit_name=unit_name,
                    scene_id=scene_id,
                    offset=match.start(),
                    line=line + 1 + index,
                )
                for index, row in enumerate(rows)
            ]

        groups = [
            *self._scan_body_markers(body, MUTATION_MARKER_PATTERN, single),
            *self._scan_body_markers(body, MUTATION_CARRIER_PATTERN, carrier),
        ]
        for group in sorted((g for g in groups if g), key=lambda g: g[0].offset):
            yield from group

    # ----- validation (#53) ----------------------------------------------

    def _validate_scene_mutations(
        self, scene_id: str, body: str, schema: object, node_index: object
    ) -> list[str]:
        """Validate every mutation value in a scene body against its target
        field's constraints — a mutation value IS a field value (ADR-0007), so it
        reuses `_validate_metadata_field_value`, the same validator base values
        run through. Called from validate_project (save_scene never blocks on
        mutation validity — the editor supplies typed values)."""
        errors: list[str] = []
        fields = getattr(schema, "fields", {})
        entry_types = getattr(schema, "entry_types", {})
        by_id = getattr(node_index, "by_id", {})
        for marker in self._iter_body_mutations(body, scene_id):
            label = (
                f"Scene {scene_id} mutation of {marker.entity_id}.{marker.field}"
            )
            # Parity with base metadata validation (ADR-0007): the entity must
            # exist and be a lore entry, and the field must be defined for its
            # entry_type — not merely present somewhere in the global schema.
            index_entry = by_id.get(marker.entity_id)
            if index_entry is None or getattr(index_entry, "kind", None) != "lore":
                errors.append(f"{label} targets unknown lore entity {marker.entity_id}.")
                continue
            if marker.field in INTRINSIC_MUTABLE_FIELDS:
                # title/body are the node's own free-text fields (not schema
                # fields but always present and mutable — the #33 name-change
                # case mutates `title`); no constraints to check.
                continue
            field = fields.get(marker.field)
            if field is None:
                errors.append(f"{label} targets unknown field {marker.field}.")
                continue
            entry_type = getattr(index_entry, "entry_type", "")
            allowed = getattr(entry_types.get(entry_type), "fields", None) or []
            if marker.field not in allowed:
                errors.append(
                    f"{label} field {marker.field} is not defined for entry_type {entry_type}."
                )
                continue
            field_type = getattr(field, "type", "")
            is_collection = field_type in COLLECTION_FIELD_TYPES
            if marker.op == "remove" and not is_collection:
                errors.append(
                    f"{label} op remove is only valid on collection fields "
                    f"(multi_select/tags/entity_ref_list), not {field_type}."
                )
                continue
            if marker.op == "add" and not (
                is_collection or field_type in TEXT_APPEND_FIELD_TYPES
            ):
                errors.append(
                    f"{label} op add is only valid on collection or text fields "
                    f"(multi_select/tags/entity_ref_list/text/long_text), not {field_type}."
                )
                continue
            if is_collection:
                # A collection value is validated as a list: add/remove carry one
                # element (validate that element), replace carries the whole
                # comma-joined value (ADR-0009). The item validator already
                # item-checks the three collection types.
                value: object = (
                    [marker.value]
                    if marker.op in {"add", "remove"}
                    else _split_collection_value(marker.value)
                )
            else:
                value = self._coerce_mutation_value(marker.value, field_type)
            errors.extend(
                self._validate_metadata_field_value(
                    label, marker.field, value, field, node_index=node_index
                )
            )
        return errors

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

        def walk(node: Scene) -> None:
            scene_id = getattr(node, "scene_id", None)
            if scene_id and scene_id not in order:
                order[scene_id] = len(order)
            for child in getattr(node, "children", None) or []:
                walk(child)

        walk(structure.root)
        return order

    def build_mutations_index(self) -> MutationsIndex:
        """Walk every manuscript scene in order, scanning its markers into a
        per-entity list ordered by (manuscript position, prose offset).
        Rebuildable cache over scene files — mirrors `_build_node_index`
        (compute-on-demand); persist to `.cache/` only if it ever gets slow
        (§3.3)."""
        scene_order = self._scene_order()
        scene_paths = self._scene_display_paths()
        by_entity: dict[str, list[MutationMarker]] = {}
        closes: list[MutationClose] = []
        for scene_id in scene_order:
            try:
                scene = self.read_scene(scene_id)
            except ProjectServiceError:
                continue
            for marker in self._scan_scene_mutations(scene):
                marker.scene_path = scene_paths.get(scene_id, marker.scene_path)
                by_entity.setdefault(marker.entity_id, []).append(marker)
            closes.extend(self._iter_body_closes(scene.body, scene_id))
        for records in by_entity.values():
            records.sort(key=lambda m: (scene_order.get(m.scene_id, 0), m.offset))
        closes_by_start = self._resolve_closes(closes, by_entity, scene_order)
        return MutationsIndex(
            version=self._mutations_version(by_entity, closes_by_start),
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
        """Map each start marker id → the (manuscript-position, offset) of its
        governing close: the earliest close positioned at/after the start (#59).
        A close before its start marks an empty interval, so it is ignored; a
        close whose scene isn't in the manuscript is dropped.

        `close;ref=<unit-id>` is expanded here (ADR-0016): it resolves as one
        close per row of the unit — per-row liveness ends that merely coincide,
        no shared-lifetime semantics. A standalone marker's unit id IS its row
        id, so both spellings resolve identically for one-row units."""
        start_pos: dict[str, tuple[int, int]] = {}
        rows_by_unit: dict[str, list[str]] = {}
        for records in by_entity.values():
            for m in records:
                if m.scene_id not in scene_order:
                    continue
                start_pos[m.marker_id] = (scene_order[m.scene_id], m.offset)
                if m.unit_id:
                    rows_by_unit.setdefault(m.unit_id, []).append(m.marker_id)
        governing: dict[str, tuple[int, int]] = {}
        for close in closes:
            if close.scene_id not in scene_order:
                continue
            close_at = (scene_order[close.scene_id], close.offset)
            for ref in rows_by_unit.get(close.ref) or [close.ref]:
                start = start_pos.get(ref)
                if start is None or close_at < start:
                    continue
                current = governing.get(ref)
                if current is None or close_at < current:
                    governing[ref] = close_at
        return governing

    def entity_mutations(self, entity_id: str) -> MutationMarkerList:
        """The manuscript-ordered mutation timeline for one entity (#54) — the
        pre-ordered per-entity slice of the index, for the lore-card list."""
        index = self.build_mutations_index()
        return MutationMarkerList(items=list(index.by_entity.get(entity_id, [])))

    def effective_names(self, scene_id: str) -> dict[str, list[str]]:
        """Each lore entry's **effective** name-set (title + aliases) as of the
        end of `scene_id` — the primitive the effective-name-aware matcher (#61)
        needs. A renamed entity resolves under its as-of-scene name; unmutated
        entries return their base names. Resolution is **scene-granular** (the
        end-of-scene name-set covers the whole scene; ADR-0008 amended)."""
        index = self.build_mutations_index()
        names: dict[str, list[str]] = {}
        try:
            entries = self.list_lore_entries().entries
        except ProjectServiceError:
            return {}
        for summary in entries:
            entity_id = getattr(summary, "id", "")
            if not entity_id:
                continue
            overrides = self.effective_state(entity_id, scene_id, index=index)
            title = str(overrides.get("title") or getattr(summary, "title", "") or "").strip()
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
    ) -> dict[str, str | list[str]]:
        """Effective mutation overrides for `entity_id` as of (scene, position).

        Returns only the fields carrying a **live** mutation, each mapped to its
        winning value; the caller overlays these onto the entry's base field
        values (ADR-0003, ADR-0006). Scalar fields resolve to a **string** —
        among the records live at (scene, position), the latest-started replace
        wins. Collection fields (multi_select / tags / entity_ref_list) resolve
        to a **`list[str]`** = `(base ∪ live adds) ∖ live removes`, remove-wins
        (ADR-0009); the datatype matches the field. Text fields (text /
        long_text, incl. intrinsic title/body) additionally accept `add` as
        **append**: base (or latest live replace) + live adds in start order,
        space-joined for text, paragraph-joined for long_text (ADR-0009
        amendment).

        A record is live iff its start is at or before the resolution point in
        manuscript order — earlier scene always, same scene only if its marker
        sits at/before `position` (so prose before a marker sees the old value,
        prose after it the new). `position=END_OF_SCENE` counts every in-scene
        marker as live. Pass a prebuilt `index` to resolve many entries without
        re-scanning.

        `exclude` skips the given record ids entirely — the list-edit authoring
        baseline (ADR-0017): re-editing a unit diffs against the effective value
        WITHOUT the unit's own rows, so the diff cannot count itself."""
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
        effective: dict[str, str | list[str]] = {}
        base: dict[str, object] | None = None
        field_types: dict[str, str] | None = None
        for field, live in live_by_field.items():
            if any(m.op in {"add", "remove"} for m in live):
                # add/remove needs the entry's base value and the field's type
                # (collection set-resolve vs text append). Both read lazily,
                # once, only when such an op is in play.
                if base is None:
                    base = self._entity_base_values(entity_id)
                if field_types is None:
                    field_types = self._mutation_field_types()
                field_type = field_types.get(field, "text")
                if field_type in COLLECTION_FIELD_TYPES:
                    effective[field] = self._resolve_collection(field, live, base)
                else:
                    effective[field] = self._resolve_text_append(
                        field, field_type, live, base
                    )
            else:
                effective[field] = live[-1].value
        return effective

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
        started (the replace winner)."""
        live_by_field: dict[str, list[MutationMarker]] = {}
        for marker in records:
            if marker.marker_id in exclude:
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
        order). A live whole-`replace` resets the base to its own value first."""
        replaces = [m for m in live if m.op == "replace"]
        if replaces:
            base_list = _split_collection_value(replaces[-1].value)
        else:
            base_list = _as_str_list(base.get(field))
        removes = {m.value for m in live if m.op == "remove"}
        result: list[str] = []
        seen: set[str] = set()
        for item in [*base_list, *(m.value for m in live if m.op == "add")]:
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
        paragraph break for `long_text`. Empty fragments drop out."""
        replaces = [m for m in live if m.op == "replace"]
        base_text = replaces[-1].value if replaces else str(base.get(field) or "")
        adds = [m.value for m in live if m.op == "add"]
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
    ) -> str:
        digest = hashlib.sha1()  # noqa: S324 - cache key, not security
        for entity_id in sorted(by_entity):
            for marker in by_entity[entity_id]:
                digest.update(
                    f"{entity_id}\x1f{marker.scene_id}\x1f{marker.offset}"
                    f"\x1f{marker.field}\x1f{marker.op}\x1f{marker.value}"
                    f"\x1f{marker.name}\x1f{marker.group}\x1f{marker.marker_id}"
                    f"\x1f{marker.unit_id}\x1f{marker.unit_name}\x1e".encode()
                )
        for start_id in sorted(closes_by_start):
            close_pos, close_offset = closes_by_start[start_id]
            digest.update(f"close\x1f{start_id}\x1f{close_pos}\x1f{close_offset}\x1e".encode())
        return digest.hexdigest()[:16]

    # ----- intentful single-marker mutators (#50) ------------------------

    def update_mutation(
        self, scene_id: str, marker_id: str, request: UpdateMutationRequest
    ) -> Scene:
        """Rewrite a single mutation record's entity/field/value in place, without
        a full body save — a standalone marker, or one row inside a carrier
        (ADR-0016: PATCH keeps addressing rows; the whole carrier is rewritten
        around the edited row, untouched rows byte-stable). A `name` on the
        request lands where the grammar keeps it: the marker itself when
        single-line, the carrier head when the row lives in one. Returns the
        updated scene so an open editor pane can reconcile. Like save_scene, a
        marker edit never blocks on value validity — the editor supplies typed
        values; validate_project reports strays."""
        return self._apply_scene_marker_edit(
            scene_id,
            "Mutation",
            marker_id,
            lambda body: self._rewrite_mutation_record(body, marker_id, request),
        )

    def delete_mutation(self, scene_id: str, marker_id: str) -> Scene:
        """Remove a mutation record: a standalone marker, one carrier row (a
        carrier left with one row canonicalizes back to single-line; left with
        none it drops entirely), or — when `marker_id` is a carrier's head id —
        the whole unit and all its rows (ADR-0016). Markers wrap no prose, so
        removal just drops comment text. Returns the updated scene."""
        return self._apply_scene_marker_edit(
            scene_id,
            "Mutation",
            marker_id,
            lambda body: self._rewrite_mutation_record(body, marker_id, None),
        )

    def _rewrite_mutation_record(
        self, body: str, marker_id: str, request: UpdateMutationRequest | None
    ) -> tuple[str, bool]:
        """The single-record rewrite behind update/delete (`request=None` ⇒
        delete): try the single-line grammar first, then the carrier rows."""
        new_body, found = self._rewrite_single_marker(
            body,
            MUTATION_MARKER_PATTERN,
            "id",
            marker_id,
            lambda match: (
                self._render_mutation(match, marker_id, request) if request else ""
            ),
        )
        if found:
            return new_body, found
        return self._rewrite_carrier_record(body, marker_id, request)

    def _rewrite_carrier_record(
        self, body: str, marker_id: str, request: UpdateMutationRequest | None
    ) -> tuple[str, bool]:
        """Rewrite/delete one row inside a carrier marker (#69), or delete a
        whole carrier by its head id. Rows other than the target keep their
        url-encoded values verbatim; the result renders in canonical form, so
        a one-row survivor degenerates to a single-line marker."""
        found = False

        def replace(match: re.Match[str]) -> str:
            nonlocal found
            if found:
                return match.group(0)
            rows = _parse_carrier_rows(match)
            if rows is None:
                return match.group(0)
            if request is None and marker_id == match.group("id"):
                found = True  # deleting the unit drops the carrier wholesale
                return ""
            index = next(
                (i for i, row in enumerate(rows) if row.row_id == marker_id), None
            )
            if index is None:
                return match.group(0)
            found = True
            if request is None:
                del rows[index]
                if not rows:
                    return ""
            else:
                row = rows[index]
                rows[index] = CarrierRow(
                    field=request.field or row.field,
                    op=request.op or row.op,
                    raw_value=(
                        quote(request.value, safe="")
                        if request.value is not None
                        else row.raw_value
                    ),
                    row_id=marker_id,
                )
            entity = (request.entity_id if request else None) or match.group("entity")
            raw_name = (
                quote(request.name, safe="")
                if request is not None and request.name is not None
                else (match.group("name") or "")
            )
            return _render_mutation_unit(entity, raw_name, match.group("id"), rows)

        return MUTATION_CARRIER_PATTERN.sub(replace, body), found

    def _render_mutation(
        self, match: re.Match[str], marker_id: str, request: UpdateMutationRequest
    ) -> str:
        """Rebuild a mutation marker from a match, applying `request`. Preserves
        the optional op/name/group attributes (only re-emitted when non-default),
        so an edit that doesn't touch them keeps the marker byte-stable."""
        entity = request.entity_id or match.group("entity")
        field = request.field or match.group("field")
        op = request.op or match.group("op") or "replace"
        # Re-encode only when a new value is supplied; otherwise keep the existing
        # encoded value verbatim to avoid gratuitous diffs.
        value = quote(request.value, safe="") if request.value is not None else match.group("value")
        name = (
            quote(request.name, safe="")
            if request.name is not None
            else (match.group("name") or "")
        )
        group = request.group if request.group is not None else (match.group("group") or "")
        return _render_mutation_marker(entity, field, op, value, name, group, marker_id)
