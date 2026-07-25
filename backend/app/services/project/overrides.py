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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import MutationSetRow
from app.services.project.errors import ProjectServiceError
from app.services.project.lore_mutations import (
    COLLECTION_FIELD_TYPES,
    _as_str_list,
    _split_collection_value,
)
from app.services.project.node_index import IndexLayer, NodeIndex

OVERRIDES_FOLDER = "overrides"
OVERRIDE_ENTRY_TYPE = "override:override"


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
        field_types = self._schema_field_types(schema)
        open_layer_id = self._metadata_schema_layer_id(root)
        for target_id, records in index.overrides_by_target.items():
            candidates = index.candidates.get(target_id)
            if not candidates:
                index.warnings.append(
                    f"Layer override targets a missing entry {target_id}; it was ignored."
                )
                continue
            # Candidates are innermost-first as built (`NodeIndex.add`), so [0] is
            # the winner the open project resolves — the owning entry for an
            # inherited target. Overrides fold onto it.
            winner = candidates[0]
            if winner.kind != "lore":
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
            folded_metadata, _ = self.materialize_override_metadata(base_metadata, records, field_types)
            index.edges_by_layer_src[(winner.source_layer_id, target_id)] = self._reference_edges_for_entry(
                winner, schema, front_matter={"metadata": folded_metadata}
            )

    def _collect_layer_overrides(self, layer: IndexLayer, index: NodeIndex) -> None:
        """Collect one layer's override files into `index.overrides_by_target`.

        Called per layer from the index builder — a parallel pass to the node
        collectors, so overrides never join `candidates`/`by_id`/edges as nodes."""
        folder = layer.folder / OVERRIDES_FOLDER
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.md")):
            record = self._read_override_record(path, layer)
            if record is not None:
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
        the `target` front-matter key, or None."""
        folder = layer_folder / OVERRIDES_FOLDER
        if not folder.is_dir():
            return None
        for path in sorted(folder.glob("*.md")):
            front_matter = self._read_front_matter_only(path)
            if front_matter.get("target") == target_id:
                return path
        return None

    # --- the fold -----------------------------------------------------------

    def materialize_override_metadata(
        self,
        base: dict[str, Any],
        records: list[LayerOverride],
        field_types: dict[str, str],
    ) -> tuple[dict[str, Any], list[str]]:
        """Fold `records` onto `base`, descendant-wins per item.

        Returns `(effective_metadata, overridden_field_ids)`. A field is reported
        overridden when an override row in the chain writes to it — the tell the
        `ti-versions` mark renders (PR 2), whether or not the value coincides with
        canon. Records are applied outermost-first so the nearest descendant wins.
        """
        result = dict(base)
        touched: list[str] = []
        for record in sorted(records, key=lambda record: record.layer_rank):
            for row in record.rows:
                field_type = field_types.get(row.field, "text")
                applied = True
                if field_type in COLLECTION_FIELD_TYPES:
                    current = _as_str_list(result.get(row.field))
                    if row.op == "replace":
                        current = _split_collection_value(row.value)
                    elif row.op == "add":
                        if row.value and row.value not in current:
                            current = [*current, row.value]
                    elif row.op == "remove":
                        current = [item for item in current if item != row.value]
                    result[row.field] = current
                elif row.op == "replace":
                    # Scalar / text: only whole-value replace in PR 1.
                    result[row.field] = row.value
                else:
                    # `add`/`remove` on a non-collection field are rejected at
                    # write time and ignored on read (a hand-edited file cannot
                    # corrupt the fold) — and an ignored op does not mark the
                    # field overridden.
                    applied = False
                if applied and row.field not in touched:
                    touched.append(row.field)
        return result, touched

    def _schema_field_types(self, schema: Any) -> dict[str, str]:
        """field id -> declared type, for fold + diff resolution. Empty on a
        schema that would not load — unknown fields then resolve as plain text."""
        fields = getattr(schema, "fields", None) or {}
        return {field_id: getattr(field, "type", "text") for field_id, field in fields.items()}

    def _diff_metadata_to_override_rows(
        self,
        base: dict[str, Any],
        submitted: dict[str, Any],
        field_types: dict[str, str],
    ) -> list[MutationSetRow]:
        """The sparse delta from `base` (the effective value above the authoring
        layer) to `submitted` (the whole metadata the client sent).

        Scalars diff to a `replace`; collections to `add`/`remove` per item, so a
        later ancestor addition to a multi-valued field keeps flowing down after
        an override adds one item (ADR-0039). Fields equal to base contribute
        nothing, keeping the override sparse."""
        rows: list[MutationSetRow] = []
        # Only fields in L's own roster can be stored at L. A field the client
        # round-trips that is defined only *below* L (the entry is edited from the
        # deeper open project) is not part of L's view of the entry and must not
        # become a delta row — otherwise it fails the as-of-L validation that
        # follows (ADR-0045 §4). Fields outside the roster are dropped here.
        for field in sorted(f for f in (set(base) | set(submitted)) if f in field_types):
            field_type = field_types[field]
            if field_type in COLLECTION_FIELD_TYPES:
                base_items = _as_str_list(base.get(field))
                new_items = _as_str_list(submitted.get(field))
                for item in new_items:
                    if item and item not in base_items:
                        rows.append(MutationSetRow(field=field, op="add", value=item))
                for item in base_items:
                    if item not in new_items:
                        rows.append(MutationSetRow(field=field, op="remove", value=item))
            else:
                base_value = base.get(field)
                new_value = submitted.get(field)
                if new_value != base_value:
                    # A field omitted from the payload clears to empty, matching an
                    # owned save (which drops the key by rewriting the whole file).
                    rows.append(MutationSetRow(field=field, op="replace", value="" if new_value is None else str(new_value)))
        return rows

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
