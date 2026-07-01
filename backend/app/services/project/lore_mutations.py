"""Mid-scene lore mutations slice of ProjectService (GH #33, #50).

A mutation is a self-contained HTML-comment marker living inline in scene
markdown, carrying the new value at the point of change:

    <!-- mutate:entity=<lore-id>;field=<field-key>;value=<url-encoded>;id=<marker-id> -->

v1.1 extends the grammar with three forward-compatible optional attributes
(absent on v1.0 markers, so old markers parse unchanged):

    ;op=<add|remove|replace>   collection operator (#58); absent ⇒ replace
    ;name=<url-encoded>        human label for the change (#65)
    ;group=<group-id>          co-authored-set tie for a shared name (#65)

Canonical order is `entity;field;op?;value;name?;group?;id`.

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

# Field types whose values are collections; only these accept add/remove ops
# (#58). Every other type stays replace-only.
COLLECTION_FIELD_TYPES = frozenset({"multi_select", "tags", "entity_ref_list"})

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
class MutationsIndex:
    """Project-wide mutation index (#51). Rebuildable from scene files; each
    entity's list is pre-ordered by manuscript position then prose offset, so
    the resolver slices O(applicable) rather than re-scanning. `version` changes
    whenever any marker changes, letting the AI cache layer key volatile lore on
    it instead of the (now-insufficient) lore file revision (ADR-0006)."""

    version: str = ""
    by_entity: dict[str, list[MutationMarker]] = dc_field(default_factory=dict)
    scene_order: dict[str, int] = dc_field(default_factory=dict)


class LoreMutationsMixin(MarkerMixin):
    def _scan_scene_mutations(self, scene: Scene) -> Iterator[MutationMarker]:
        """Yield every mutation marker in one scene body, in prose order,
        carrying each marker's char offset (needed for position-granular
        resolution). The single per-scene scan the index (#51) walks."""
        yield from self._iter_body_mutations(scene.body, scene.id)

    def _iter_body_mutations(self, body: str, scene_id: str) -> Iterator[MutationMarker]:
        """Regex-walk one raw body for markers. Split from `_scan_scene_mutations`
        so validation (#53) can scan a body it already read (front-matter walk)
        without materializing a Scene."""
        return self._scan_body_markers(
            body,
            MUTATION_MARKER_PATTERN,
            lambda match, line: MutationMarker(
                marker_id=match.group("id"),
                entity_id=match.group("entity"),
                field=match.group("field"),
                op=match.group("op") or "replace",
                value=unquote(match.group("value")),
                name=unquote(match.group("name") or ""),
                group=match.group("group") or "",
                scene_id=scene_id,
                offset=match.start(),
                line=line,
            ),
        )

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
            if marker.op in {"add", "remove"} and not is_collection:
                errors.append(
                    f"{label} op {marker.op} is only valid on collection fields "
                    f"(multi_select/tags/entity_ref_list), not {field_type}."
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
        for scene_id in scene_order:
            try:
                scene = self.read_scene(scene_id)
            except ProjectServiceError:
                continue
            for marker in self._scan_scene_mutations(scene):
                marker.scene_path = scene_paths.get(scene_id, marker.scene_path)
                by_entity.setdefault(marker.entity_id, []).append(marker)
        for records in by_entity.values():
            records.sort(key=lambda m: (scene_order.get(m.scene_id, 0), m.offset))
        return MutationsIndex(
            version=self._mutations_version(by_entity),
            by_entity=by_entity,
            scene_order=scene_order,
        )

    def entity_mutations(self, entity_id: str) -> MutationMarkerList:
        """The manuscript-ordered mutation timeline for one entity (#54) — the
        pre-ordered per-entity slice of the index, for the lore-card list."""
        index = self.build_mutations_index()
        return MutationMarkerList(items=list(index.by_entity.get(entity_id, [])))

    def effective_state(
        self,
        entity_id: str,
        scene_id: str,
        position: int | None = END_OF_SCENE,
        index: MutationsIndex | None = None,
    ) -> dict[str, str | list[str]]:
        """Effective mutation overrides for `entity_id` as of (scene, position).

        Returns only the fields carrying a **live** mutation, each mapped to its
        winning value; the caller overlays these onto the entry's base field
        values (ADR-0003, ADR-0006). Scalar fields resolve to a **string** —
        among the records live at (scene, position), the latest-started replace
        wins. Collection fields (multi_select / tags / entity_ref_list) resolve
        to a **`list[str]`** = `(base ∪ live adds) ∖ live removes`, remove-wins
        (ADR-0009); the datatype matches the field.

        A record is live iff its start is at or before the resolution point in
        manuscript order — earlier scene always, same scene only if its marker
        sits at/before `position` (so prose before a marker sees the old value,
        prose after it the new). `position=END_OF_SCENE` counts every in-scene
        marker as live. Pass a prebuilt `index` to resolve many entries without
        re-scanning."""
        idx = index or self.build_mutations_index()
        records = idx.by_entity.get(entity_id)
        if not records:
            return {}
        target_pos = idx.scene_order.get(scene_id)
        if target_pos is None:
            # Scene not in the manuscript → no manuscript position → base only.
            return {}
        live_by_field: dict[str, list[MutationMarker]] = {}
        for marker in records:  # pre-sorted ascending, so the last live wins
            if self._marker_is_live(marker, idx.scene_order, target_pos, position):
                live_by_field.setdefault(marker.field, []).append(marker)
        effective: dict[str, str | list[str]] = {}
        base: dict[str, object] | None = None
        for field, live in live_by_field.items():
            if any(m.op in {"add", "remove"} for m in live):
                # Collection field — needs the entry's base list to resolve the
                # set. Read it lazily, once, only when an add/remove is in play.
                if base is None:
                    base = self._entity_base_values(entity_id)
                effective[field] = self._resolve_collection(field, live, base)
            else:
                effective[field] = live[-1].value
        return effective

    def _entity_base_values(self, entity_id: str) -> dict[str, object]:
        """The entry's stored (book-start) metadata, for collection resolution.
        Empty on any read failure (resolution then treats base as empty)."""
        try:
            entry = self.read_lore_entry(entity_id)
        except ProjectServiceError:
            return {}
        return dict(getattr(entry, "metadata", {}) or {})

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

    def _marker_is_live(
        self,
        marker: MutationMarker,
        scene_order: dict[str, int],
        target_pos: int,
        position: int | None,
    ) -> bool:
        marker_pos = scene_order.get(marker.scene_id)
        if marker_pos is None or marker_pos > target_pos:
            return False
        if marker_pos < target_pos:
            return True
        return position is END_OF_SCENE or marker.offset <= position

    def _mutations_version(self, by_entity: dict[str, list[MutationMarker]]) -> str:
        digest = hashlib.sha1()  # noqa: S324 - cache key, not security
        for entity_id in sorted(by_entity):
            for marker in by_entity[entity_id]:
                digest.update(
                    f"{entity_id}\x1f{marker.scene_id}\x1f{marker.offset}"
                    f"\x1f{marker.field}\x1f{marker.op}\x1f{marker.value}"
                    f"\x1f{marker.name}\x1f{marker.group}\x1f{marker.marker_id}\x1e".encode()
                )
        return digest.hexdigest()[:16]

    # ----- intentful single-marker mutators (#50) ------------------------

    def update_mutation(
        self, scene_id: str, marker_id: str, request: UpdateMutationRequest
    ) -> Scene:
        """Rewrite a single mutation marker's entity/field/value in place, without
        a full body save. Returns the updated scene so an open editor pane can
        reconcile. Like save_scene, a marker edit never blocks on value
        validity — the editor supplies typed values; validate_project reports
        strays."""
        return self._apply_scene_marker_edit(
            scene_id,
            "Mutation",
            marker_id,
            lambda body: self._rewrite_single_marker(
                body,
                MUTATION_MARKER_PATTERN,
                "id",
                marker_id,
                lambda match: self._render_mutation(match, marker_id, request),
            ),
        )

    def delete_mutation(self, scene_id: str, marker_id: str) -> Scene:
        """Remove a single mutation marker. The marker wraps no prose, so removal
        just drops the comment. Returns the updated scene."""
        return self._apply_scene_marker_edit(
            scene_id,
            "Mutation",
            marker_id,
            lambda body: self._rewrite_single_marker(
                body,
                MUTATION_MARKER_PATTERN,
                "id",
                marker_id,
                lambda match: "",  # point marker: removal drops the comment
            ),
        )

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
