"""Layer overrides — the `overrides/` slice of ProjectService (#314 / ADR-0039).

A **layer override** is the consuming layer's *sparse delta* on a node it
inherited from an ancestor. It is applied at **materialization**, not as a tier
inside the mutation resolver: `materialize(chain) -> base`, then
`base -> mutations -> effective`. So scene mutations are untouched — they run on
the folded base exactly as before (`_entity_base_values` reads `read_lore_entry`,
which folds here).

Storage mirrors a reusable mutation set (`mutation_sets.py`): a **body-less Node**
under `<layer>/overrides/`, one file per (layer, target), carrying

    target: <node id>          # the join key — NOT the filename (which tracks title)
    rows:                      # the same op vocabulary as a scene mutation
      - {field: rank, op: replace, value: Captain}
      - {field: aliases, op: add, value: The Salamander}

The override node's own id is `sha256(layer_id + target_id)` — deterministic,
distinct per layer, needing no uniqueness registry (ADR-0039). Overrides are
**deltas, not nodes**: they never enter `by_id`, reference pickers or view
results. They are collected in a parallel pass into `NodeIndex.overrides_by_target`
(see `references.py`), keyed by target id.

**Composition across layers is descendant-wins per item** — deliberately
diverging from the mutation `remove`-wins rule it borrows the vocabulary from.
Layers are totally ordered by rank, so a book that re-adds an alias its series
removed should get it; that case is inexpressible under remove-wins. Records are
applied outermost-first (ascending `rank`), so the nearest descendant's op wins.

The op vocabulary is the codebase's existing `replace | add | remove`
(`MutationSetRow`); ADR-0039's "set" is `replace`. `add`/`remove` apply to
collection fields; a scalar/text field takes `replace` only (PR 1 — text-append
overrides are deferred with body/title overrides, see `lore.py`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import MetadataFieldDefinition, MetadataSchema, MutationSetRow
from app.services.project.errors import ProjectServiceError
from app.services.project.lore_mutation_items import (
    ItemRecord,
    KeyedList,
    encode_item,
    fold_keyed_items,
    item_key,
    keyed_lists_from,
    list_record,
    member_path,
    member_record,
    split_member_path,
)
from app.services.project.lore_mutations import (
    COLLECTION_FIELD_TYPES,
    _as_str_list,
    _split_collection_value,
)
from app.services.project.node_index import IndexLayer, NodeIndex

OVERRIDES_FOLDER = "overrides"
OVERRIDE_ENTRY_TYPE = "override:override"


def _required_select_reading(definition: MetadataFieldDefinition, value: Any) -> Any:
    """`value` as a required select reads it: blank or absent IS the default
    (#1421, the blank rule `_strip_unknown_metadata_fields` writes by). Any
    other field, or any other value, passes through."""
    if definition.required_select and value in (None, ""):
        return definition.default
    return value


def _same_key(key: str) -> str:
    return key


def _items_by_key(value: Any, key_member: str) -> dict[str, dict[str, Any]]:
    """A reference-keyed list's items by key, first wins; unkeyed items dropped."""
    out: dict[str, dict[str, Any]] = {}
    for item in value if isinstance(value, list) else []:
        key = item_key(item, key_member)
        if key is not None and key not in out:
            out[key] = item
    return out


def _member_record_value(value: Any, member_type: str) -> str:
    """A member's value as a record's string — the spelling the fold coerces
    back through `_coerce_mutation_value`: empty for absent, `true`/`false`
    for a boolean, comma-joined for a collection member, `str()` otherwise."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(item) for item in value if str(item))
    return str(value)


@dataclass(frozen=True)
class OverrideShapes:
    """What the override fold knows about the schema: each field's declared
    type, and the reference-keyed lists (ADR-0089 §5) whose rows fold per key."""

    field_types: dict[str, str]
    keyed: dict[str, KeyedList]

    @classmethod
    def empty(cls) -> OverrideShapes:
        return cls({}, {})


@dataclass(frozen=True)
class LayerOverride:
    """One layer's delta on one target, plus where it came from.

    `layer_rank` orders composition (outermost first); `path` feeds the composite
    revision so an override edit changes the folded entry's `revision`.
    """

    target_id: str
    layer_id: str
    layer_rank: int
    layer_label: str
    path: Path
    rows: tuple[MutationSetRow, ...]


class LayerOverridesMixin:
    # --- identity + storage -------------------------------------------------

    @staticmethod
    def _override_id(layer_id: str, target_id: str) -> str:
        """The override node's own id: `sha256(layer_id + target_id)`, prefixed
        like every other minted id. Deterministic and distinct per layer, so a
        series override and a book override of the same entry never collide."""
        digest = hashlib.sha256(f"{layer_id}{target_id}".encode()).hexdigest()
        return f"override_{digest[:16]}"

    def _parse_override_rows(self, raw: Any) -> list[MutationSetRow]:
        """Parse the `rows:` list defensively, skipping malformed rows — a
        hand-edited override file must not take down the whole index build."""
        if not isinstance(raw, list):
            return []
        rows: list[MutationSetRow] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            if not isinstance(field, str) or not field:
                continue
            op = item.get("op")
            value = item.get("value")
            rows.append(
                MutationSetRow(
                    field=field,
                    op=op if isinstance(op, str) and op in {"replace", "add", "remove"} else "replace",
                    value=str(value) if value is not None else "",
                )
            )
        return rows

    def _read_override_record(self, path: Path, layer: IndexLayer) -> LayerOverride | None:
        """Read one override file into a `LayerOverride`, or None when it names no
        target (an override with nothing to join to is not a delta)."""
        try:
            front_matter = self._read_front_matter_only(path, strict=True)
        except ProjectServiceError:
            return None
        target = front_matter.get("target")
        if not isinstance(target, str) or not target:
            return None
        return LayerOverride(
            target_id=target,
            layer_id=layer.id,
            layer_rank=layer.rank,
            layer_label=layer.label,
            path=path,
            rows=tuple(self._parse_override_rows(front_matter.get("rows"))),
        )

    def _chain_has_overrides(self, layers: list[IndexLayer]) -> bool:
        """Whether any layer in the chain holds an override file — the gate that
        routes a chain onto the full-cold-walk path (`_resolve_index_cold`). A
        cheap glob per layer; flat projects have no `overrides/` folder at all."""
        for layer in layers:
            folder = layer.folder / OVERRIDES_FOLDER
            if folder.is_dir() and any(folder.glob("*.md")):
                return True
        return False

    def _collect_all_overrides(self, index: NodeIndex, layers: list[IndexLayer]) -> None:
        """Populate `index.overrides_by_target` over the whole chain."""
        for layer in layers:
            self._collect_layer_overrides(layer, index)

    def _fold_override_edges(self, index: NodeIndex, root: Path, schema: Any) -> None:
        """Rewrite each overridden target's forward edges from its *folded*
        metadata, so the index holds effective edges without holding values
        (#314 / ADR-0039). Runs after the walk and before `resolve()`.

        An override whose target does not resolve is an **orphan**: dropped with a
        warning, never promoted to base and never unlinked (files-are-truth).
        """
        if not index.overrides_by_target or schema is None:
            return
        shapes = self._override_shapes(schema)
        open_layer_id = self._metadata_schema_layer_id(root)
        for target_id, records in index.overrides_by_target.items():
            candidates = index.candidates.get(target_id)
            if not candidates:
                # Attributed to the override file that names the missing target
                # (#382). An override-bearing chain always rebuilds cold and is
                # never snapshotted or patched, so this diagnostic never has to
                # survive a drop — but it still carries provenance so the derived
                # `warnings` view is uniform with every other diagnostic.
                orphan = records[0]
                index.add_diagnostic(
                    layer_id=orphan.layer_id,
                    path=orphan.path,
                    message=f"Layer override targets a missing entry {target_id}; it was ignored.",
                    is_error=False,
                )
                continue
            # Candidates are innermost-first as built (`NodeIndex.add`), so [0] is
            # the winner the open project resolves — the owning entry for an
            # inherited target. Overrides fold onto it.
            winner = candidates[0]
            # Only kinds that support layer overrides fold their edges. Prompts
            # joined lore here (#1738): an overridden `preferred_assistant_id`
            # (entity_ref) must recompute its reference edge from the folded value
            # so the index's backlinks and dangling-ref stripping stay consistent.
            # The gate is really the presence of an override file, which is only
            # ever written for these kinds; the allow-list keeps a hand-authored
            # override targeting some other kind from folding edges unexpectedly.
            if winner.kind not in {"lore", "prompt"}:
                continue
            # An override applies only to an inherited winner. A winner the open
            # project owns locally (a fork that severed inheritance) keeps its own
            # edges — the value fold skips it for the same reason.
            if winner.source_layer_id == open_layer_id:
                continue
            try:
                front_matter = self._read_front_matter_only(winner.path, strict=True)
            except ProjectServiceError:
                continue
            base_metadata = self._normalise_metadata(front_matter.get("metadata"), winner.path)
            folded_metadata, _ = self.materialize_override_metadata(base_metadata, records, shapes)
            index.edges_by_layer_src[(winner.source_layer_id, target_id)] = self._reference_edges_for_entry(
                winner, schema, front_matter={"metadata": folded_metadata}
            )

    def _collect_layer_overrides(self, layer: IndexLayer, index: NodeIndex) -> None:
        """Collect one layer's override files into `index.overrides_by_target`.

        Called per layer from the index builder — a parallel pass to the node
        collectors, so overrides never join `candidates`/`by_id`/edges as nodes.

        **One file per (layer, target)** is the writer's shape
        (`_write_override_file` reuses the existing file), and every reader of
        "this layer's override for X" (`_override_file_for_target`) takes the
        first in sorted order. The collector enforces the same (#1856): when a
        sync tool's "conflicted copy" or an Explorer "- Copy" has duplicated a
        file, only the first is folded and each later one is a warning naming
        both — before this, every copy folded and the later filename silently
        won, so an edit through the app (which rewrites the first) appeared not
        to take."""
        folder = layer.folder / OVERRIDES_FOLDER
        if not folder.is_dir():
            return
        first_for_target: dict[str, Path] = {}
        for path in sorted(folder.glob("*.md")):
            record = self._read_override_record(path, layer)
            if record is None:
                continue
            first = first_for_target.get(record.target_id)
            if first is not None:
                index.add_diagnostic(
                    layer_id=layer.id,
                    path=path,
                    message=(
                        f"Layer override {path.name} duplicates {first.name} for {record.target_id} "
                        f"at {layer.label}; only {first.name} is applied — remove or merge the copy."
                    ),
                    is_error=False,
                )
                continue
            first_for_target[record.target_id] = path
            index.overrides_by_target.setdefault(record.target_id, []).append(record)

    def _write_override_file(
        self, layer_folder: Path, target_id: str, target_title: str, rows: list[MutationSetRow]
    ) -> Path:
        """Write (or overwrite) the override delta for `target_id` at `layer_folder`.

        One file per (layer, target): reuse the existing file if this layer
        already overrides the target (the filename is cosmetic — the `target`
        front-matter key is the join), otherwise mint one from the target's
        title."""
        override_id = self._override_id(self._metadata_schema_layer_id(layer_folder), target_id)
        path = self._override_file_for_target(layer_folder, target_id)
        if path is None:
            path = self._filepath_for_new_node(layer_folder / OVERRIDES_FOLDER, f"{target_title} (override)")
        self._write_node_entry_file(
            path,
            override_id,
            f"{target_title} (override)",
            OVERRIDE_ENTRY_TYPE,
            {},
            "",
            extra={"target": target_id, "rows": [row.model_dump() for row in rows]},
            omit_empty_metadata=True,
        )
        return path

    def _override_file_for_target(self, layer_folder: Path, target_id: str) -> Path | None:
        """The existing override file this layer holds for `target_id`, matched on
        the `target` front-matter key, or None. One file per (layer, target) is the
        writer's shape; when a sync tool's conflict copy has broken it, this is the
        first in sorted order — the one `_write_override_file` reuses."""
        files = self._override_files_for_target(layer_folder, target_id)
        return files[0] if files else None

    def _override_files_for_target(self, layer_folder: Path, target_id: str) -> list[Path]:
        """EVERY override file this layer holds for `target_id`, sorted. Normally
        one; more when a file has been duplicated outside the app (a "conflicted
        copy", an Explorer "- Copy"). The collector folds only the first (#1856),
        but a gesture that UNLINKS a layer's override for a target must unlink
        all of them — `_drop_layer_overrides_for_target` — or the survivor is the
        one file on the next build and a value the author just removed is back."""
        folder = layer_folder / OVERRIDES_FOLDER
        if not folder.is_dir():
            return []
        return [
            path
            for path in sorted(folder.glob("*.md"))
            if self._read_front_matter_only(path).get("target") == target_id
        ]

    def _drop_layer_overrides_for_target(self, layer_folder: Path, target_id: str) -> None:
        """Unlink this layer's override for `target_id` — every file carrying it.

        The one way an override file leaves the disk through the app: a revert to
        canon or a field reset (`_save_lore_override` / `_save_prompt_override`),
        a fork-to-here that baked the folded values into the copy
        (`fork_lore_entry`), and a promotion settling the origin's leftover
        (`_settle_origin_override`). Routed through `_delete_node_files` so the
        memo stays coherent (an override-bearing chain rebuilds cold)."""
        files = tuple(self._override_files_for_target(layer_folder, target_id))
        if files:
            self._delete_node_files(files)

    # --- the fold -----------------------------------------------------------

    def _override_shapes(self, schema: Any) -> OverrideShapes:
        """What the fold needs to know about the schema, derived once per
        caller: every field's declared type, and the reference-keyed lists
        whose rows fold per key (ADR-0089 §5)."""
        return OverrideShapes(self._schema_field_types(schema), keyed_lists_from(schema))

    def materialize_override_metadata(
        self,
        base: dict[str, Any],
        records: list[LayerOverride],
        shapes: OverrideShapes,
        *,
        canonical: Callable[[str], str] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Fold `records` onto `base`, descendant-wins per item.

        Returns `(effective_metadata, overridden_field_ids)`. A field is reported
        overridden when an override row in the chain writes to it — the tell the
        `ti-versions` mark renders (PR 2), whether or not the value coincides with
        canon. Records are applied outermost-first so the nearest descendant wins.

        A reference-keyed list's rows are the marker grammar's three records
        (ADR-0089 §5): `add` carries an item, `replace` on
        `<field>.<target id>.<member>` a member, `remove` a target id. They are
        set aside in chain order and folded once per list, positional per key
        (the same fold the scene resolver runs), keys matched through
        `canonical` when the caller has an index (a record written against an
        id later merged away still finds its item); the list's own field id is
        what `touched` reports, never a member path. A `replace` with an empty
        value on such a list is the clear #698 v1 files may still hold — every
        row before it is moot and the fold starts from nothing — and a
        non-empty whole-list replace is not a record of this class (§2).
        """
        result = dict(base)
        touched: list[str] = []
        item_rows: dict[str, list[ItemRecord]] = {}
        cleared: set[str] = set()
        for record in sorted(records, key=lambda record: record.layer_rank):
            for row in record.rows:
                target = self._keyed_row_target(row, shapes.keyed)
                if target is None:
                    field_type = shapes.field_types.get(row.field, "text")
                    if self._apply_override_row(result, row, field_type) and row.field not in touched:
                        touched.append(row.field)
                    continue
                keyed, item_record = target
                if row.field == keyed.field_id and row.op == "replace":
                    if row.value != "":
                        continue
                    item_rows[keyed.field_id] = []
                    cleared.add(keyed.field_id)
                else:
                    item_rows.setdefault(keyed.field_id, []).append(item_record)
                if keyed.field_id not in touched:
                    touched.append(keyed.field_id)
        for field_id, rows in item_rows.items():
            base_items = [] if field_id in cleared else result.get(field_id)
            result[field_id] = fold_keyed_items(
                base_items, shapes.keyed[field_id], rows, self._coerce_mutation_value, canonical or _same_key
            )
        return result, touched

    @staticmethod
    def _keyed_row_target(row: MutationSetRow, keyed: dict[str, KeyedList]) -> tuple[KeyedList, ItemRecord] | None:
        """The reference-keyed list a row addresses — by its own field id or by
        a `<field>.<target id>.<member>` path — with the row classified for the
        fold; `None` for a row on any other field."""
        target = keyed.get(row.field)
        if target is not None:
            return target, list_record(target, row)
        path = split_member_path(row.field, keyed) if "." in row.field else None
        if path is None:
            return None
        target, key, member = path
        return target, member_record(row, key, member)

    @staticmethod
    def _override_row_field(row: MutationSetRow, keyed: dict[str, KeyedList]) -> str:
        """The field a row belongs to as the author sees it: a member path's
        list, else the row's own field — what a reset-to-inherited names."""
        if row.field in keyed or "." not in row.field:
            return row.field
        path = split_member_path(row.field, keyed)
        return path[0].field_id if path is not None else row.field

    def _apply_override_row(
        self, result: dict[str, Any], row: MutationSetRow, field_type: str
    ) -> bool:
        """Apply one override `row` of `field_type` onto `result` in place.

        Returns whether the row was applied — an ignored op (a hand-edited file
        cannot corrupt the fold) does not mark the field overridden.
        """
        if field_type == "list":
            # #698: string rows cannot carry structured items. "" is
            # the representable clear (folds to an empty list); any
            # other value — a hand-edited file, or a row written while
            # the field was still a scalar type before a retype — is
            # ignored rather than installed as a string the reads
            # would then reject ("a hand-edited file cannot corrupt
            # the fold" must hold for this type too).
            if row.op == "replace" and row.value == "":
                result[row.field] = []
                return True
            return False
        if field_type in COLLECTION_FIELD_TYPES:
            result[row.field] = self._folded_collection_value(result.get(row.field), row)
            return True
        if row.op == "replace":
            # Scalar / text: only whole-value replace in PR 1.
            result[row.field] = row.value
            return True
        # `add`/`remove` on a non-collection field are rejected at write time
        # and ignored on read.
        return False

    def _folded_collection_value(self, current_value: Any, row: MutationSetRow) -> list[str]:
        """The new list value for a collection field after applying `row`
        (replace whole / add one / remove one) onto its current value."""
        current = _as_str_list(current_value)
        if row.op == "replace":
            current = _split_collection_value(row.value)
        elif row.op == "add":
            if row.value and row.value not in current:
                current = [*current, row.value]
        elif row.op == "remove":
            current = [item for item in current if item != row.value]
        return current

    def _schema_field_types(self, schema: Any) -> dict[str, str]:
        """field id -> declared type, for fold + diff resolution. Empty on a
        schema that would not load — unknown fields then resolve as plain text."""
        fields = getattr(schema, "fields", None) or {}
        return {field_id: getattr(field, "type", "text") for field_id, field in fields.items()}

    def _diff_metadata_to_override_rows(
        self,
        base: dict[str, Any],
        submitted: dict[str, Any],
        schema: MetadataSchema,
    ) -> list[MutationSetRow]:
        """The sparse delta from `base` (the effective value above the authoring
        layer) to `submitted` (the whole metadata the client sent).

        Scalars diff to a `replace`; collections to `add`/`remove` per item, so a
        later ancestor addition to a multi-valued field keeps flowing down after
        an override adds one item (ADR-0039). Fields equal to base contribute
        nothing, keeping the override sparse.

        A required select's sparse spelling IS its default (#1421): both sides
        are read as the default before they are compared, and a row that sets
        one carries the default literally (#1917) — "back to the default" over
        an ancestor's pick is a delta like any other, where the bare absent key
        would diff to a blank the save then refuses."""
        fields = schema.fields
        keyed_lists = keyed_lists_from(schema)
        rows: list[MutationSetRow] = []
        # Only fields in L's own roster can be stored at L. A field the client
        # round-trips that is defined only *below* L (the entry is edited from the
        # deeper open project) is not part of L's view of the entry and must not
        # become a delta row — otherwise it fails the as-of-L validation that
        # follows (ADR-0045 §4). Fields outside the roster are dropped here.
        for field in sorted(f for f in (set(base) | set(submitted)) if f in fields):
            definition = fields[field]
            field_type = definition.type
            if field in keyed_lists:
                # A reference-keyed list diffs BY KEY (ADR-0089 §5): a new key is
                # an `add` of the whole item, a missing key a `remove`, a changed
                # member a `replace` on the member path. A reorder alone is no delta.
                rows.extend(self._keyed_list_override_rows(keyed_lists[field], base.get(field), submitted.get(field)))
                continue
            if field_type in COLLECTION_FIELD_TYPES:
                base_items = _as_str_list(base.get(field))
                new_items = _as_str_list(submitted.get(field))
                for item in new_items:
                    if item and item not in base_items:
                        rows.append(MutationSetRow(field=field, op="add", value=item))
                for item in base_items:
                    if item not in new_items:
                        rows.append(MutationSetRow(field=field, op="remove", value=item))
                continue
            base_value = _required_select_reading(definition, base.get(field))
            new_value = _required_select_reading(definition, submitted.get(field))
            if new_value != base_value:
                rows.append(self._scalar_override_row(field, field_type, new_value))
        return rows

    @staticmethod
    def _keyed_list_override_rows(keyed: KeyedList, base_value: Any, new_value: Any) -> list[MutationSetRow]:
        """The sparse delta between two reference-keyed lists, as records: an
        `add` (the whole item, JSON) per key only `new_value` holds, a `replace`
        on the member path per member that differs for a key both hold, a
        `remove` per key only `base_value` holds. Items without a key cannot be
        addressed by a record and contribute nothing; a repeated key reads as
        its first item (the save refuses duplicates before diffing)."""
        before = _items_by_key(base_value, keyed.key_member)
        after = _items_by_key(new_value, keyed.key_member)
        rows: list[MutationSetRow] = []
        for key, item in after.items():
            base_item = before.get(key)
            if base_item is None:
                rows.append(MutationSetRow(field=keyed.field_id, op="add", value=encode_item(item)))
                continue
            for member, member_field in keyed.member_fields.items():
                if member == keyed.key_member:
                    continue
                new_text = _member_record_value(item.get(member), member_field.type)
                if new_text != _member_record_value(base_item.get(member), member_field.type):
                    rows.append(
                        MutationSetRow(field=member_path(keyed.field_id, key, member), op="replace", value=new_text)
                    )
        for key in before:
            if key not in after:
                rows.append(MutationSetRow(field=keyed.field_id, op="remove", value=key))
        return rows

    @staticmethod
    def _scalar_override_row(field: str, field_type: str, new_value: Any) -> MutationSetRow:
        """The `replace` row that sets a scalar field to `new_value`."""
        if field_type == "list":
            # #698 v1: the override row format is string-typed (the #58 marker
            # grammar), so a NON-EMPTY structured list has no honest
            # representation here — str() would persist a Python repr the fold
            # then serves as the value. Clearing IS representable (value=""
            # folds to []), so the revert gesture keeps working; anything else
            # refuses loudly. A list keyed by its one reference member has its
            # own records and never reaches here (ADR-0089 §5).
            if new_value in (None, "", []):
                return MutationSetRow(field=field, op="replace", value="")
            raise ProjectServiceError(
                f"Ordered-list field {field} cannot be overridden from a descendant "
                "layer; edit the entry in the project that owns it (a list keyed by "
                "one reference member can be, ADR-0089).",
                422,
            )
        # A field omitted from the payload clears to empty, matching an owned
        # save (which drops the key by rewriting the whole file).
        return MutationSetRow(field=field, op="replace", value="" if new_value is None else str(new_value))

    @staticmethod
    def _marked_override_fields(
        touched: list[str], metadata: dict[str, Any], entry_type: str, schema: MetadataSchema
    ) -> list[str]:
        """`touched` (the fields the fold wrote) narrowed to the ones the read
        still marks after the repair ran. The mark reports the delta — a row
        this layer holds on the field — not whether the shown value differs
        from canon, so it survives the select canon: a select the entry type
        carries reads its blank, its default (#1912) and a stale derived state
        (#1911) as the absent key, and that absent key is a spelling of the
        override's value, not a strip (#1917). A field the strips removed
        (retired from the schema, a dangling reference) drops its mark with
        its value."""
        if not touched:
            return touched
        entry_type_definition = schema.entry_types.get(entry_type)
        carried = entry_type_definition.fields if entry_type_definition is not None else ()
        sparse = {
            field
            for field in carried
            if (definition := schema.fields.get(field)) is not None and definition.type == "select"
        }
        return [field for field in touched if field in metadata or field in sparse]

    # --- composite revision -------------------------------------------------

    def _composite_revision(self, paths: list[Path]) -> str:
        """A revision spanning the fold: hash the owning file plus every override
        file in the chain, in order (ADR-0039). A single path reproduces
        `_revision` exactly, so a non-overridden entry's revision is unchanged."""
        digest = hashlib.sha256()
        for path in paths:
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _override_paths_for_target(self, index: NodeIndex, target_id: str) -> list[Path]:
        """The override file paths in the chain for `target_id`, ordered
        outermost-first — the tail of the composite-revision input."""
        records = index.overrides_by_target.get(target_id, [])
        return [record.path for record in sorted(records, key=lambda record: record.layer_rank)]
