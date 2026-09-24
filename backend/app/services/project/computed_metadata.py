"""Computed-metadata slice of ProjectService (#14 backend split).

Derived read-time fields that never persist to disk: word_count, the per-scope
scene counters (within siblings / within the whole manuscript), and the
AI-invocation cost rollup behind the `cost` computed field. `ProjectService`
composes it; inputs (`read_structure`, `list_ai_invocations`) resolve via MRO.

This dispatch covers the BODY-derived functions only — see
`default_schema.AUTHORABLE_COMPUTED_FUNCTIONS` / `BUILTIN_COMPUTED_FUNCTIONS`
for the full vocabulary. The built-in ones are stamped by their own resolver
(`references` at view-eval time on the frontend; the assistant curation pair by
the layer traversal in `assistants.py`; `path` by `read_project_node`, which has
the project root in hand — `project_node.py`), so an unknown function falling
through the chain below and yielding no value is correct, not a gap.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.models import MetadataSchema, StructureDocument, StructureNode
from app.services.tree_structure import StructureVisitor, TreeStructureService

WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")


class _ManuscriptOrdinal(StructureVisitor):
    """The 1-based position of the target scene among nodes of `entry_type`, in
    pre-order — halting the walk once the target is reached."""

    def __init__(self, entry_type: str, target_scene_id: str) -> None:
        self._entry_type = entry_type
        self._target_scene_id = target_scene_id
        self.count = 0
        self.result: int | None = None

    def visit_node(
        self, node: StructureNode, ancestors: tuple[StructureNode, ...]
    ) -> bool | None:
        if node.type == self._entry_type:
            self.count += 1
            if node.scene_id == self._target_scene_id:
                self.result = self.count
                return True
        return None


def _has_cascade_value(value: Any) -> bool:
    """A cascade field counts as *set* only with a real value; None and the empty
    string read as absent (inherit) — the ADR-0079 rule that makes absence the
    inherited signal."""
    return value is not None and value != ""


class _CascadeResolver(StructureVisitor):
    """Folds each schema `cascade_fields` id down the manuscript structure,
    nearest-explicit-wins, stamping `node.resolved_cascade` (ADR-0079). Own value
    wins; else the nearest ancestor that sets it; else the book (project) default;
    else unset. Provenance rides along for the markers: `source_id` (None = book
    default) and `own`; plus `overrides` — True when an own value SHADOWS a value
    it would otherwise inherit — and `inherited_source_id` (whose value it shadows,
    None = book), so the rail can show an override mark + "reset to inherited"
    distinctly from a value merely set with nothing above it (#1734). The fold is
    **generic** over cascade_fields; narration-specific reads (an omniscient
    `pov_mode` ignoring `pov`) are a consumer concern, not baked in here."""

    def __init__(
        self,
        cascade_fields: list[str],
        own_metadata: Callable[[StructureNode], dict[str, Any]],
        book_default: dict[str, Any],
    ) -> None:
        self._fields = cascade_fields
        self._own = own_metadata
        self._book_default = book_default

    def visit_node(
        self, node: StructureNode, ancestors: tuple[StructureNode, ...]
    ) -> None:
        node.resolved_cascade = {
            field_id: self._resolve(field_id, node, ancestors) for field_id in self._fields
        } or None

    def _resolve(
        self, field_id: str, node: StructureNode, ancestors: tuple[StructureNode, ...]
    ) -> dict[str, Any]:
        own = self._own(node).get(field_id)
        # What this field WOULD resolve to if this node did not set it — computed
        # even when `own` is present, so an own value can report whether it SHADOWS
        # an inherited one (`overrides`) rather than merely being set (#1734).
        inherited_value, inherited_source_id = self._inherited(field_id, ancestors)
        shadows = _has_cascade_value(inherited_value)
        if _has_cascade_value(own):
            return {
                "value": own,
                "source_id": node.id,
                "own": True,
                "overrides": shadows,
                "inherited_source_id": inherited_source_id if shadows else None,
            }
        if shadows:
            return {
                "value": inherited_value,
                "source_id": inherited_source_id,
                "own": False,
                "overrides": False,
                "inherited_source_id": None,
            }
        return {
            "value": None,
            "source_id": None,
            "own": False,
            "overrides": False,
            "inherited_source_id": None,
        }

    def _inherited(
        self, field_id: str, ancestors: tuple[StructureNode, ...]
    ) -> tuple[Any, str | None]:
        """The (value, source_id) this field would inherit absent an own value: the
        nearest ancestor that sets it, else the book (project) default (source_id
        None), else (None, None)."""
        # ancestors are root-first; the nearest is last.
        for ancestor in reversed(ancestors):
            inherited = self._own(ancestor).get(field_id)
            if _has_cascade_value(inherited):
                return inherited, ancestor.id
        return self._book_default.get(field_id), None


def strip_computed_fields(metadata: dict[str, Any], schema: MetadataSchema) -> dict[str, Any]:
    """Drop the keys `schema` declares as computed fields from a metadata dict
    about to be persisted. Computed values are stamped at read; a stored copy
    would assert a value the real source (the resolver, the front matter it
    derives from) contradicts on the very next read.

    Deliberately a COMPUTED-KEYS-ONLY strip, never a full unknown/not-allowed
    strip: `schema` may not be the only schema the node's fields answer to (an
    assistant is machine-layer and shared across projects; a project layer may
    declare fields this resolved view lacks), so filtering to known keys would
    silently delete another layer's data from disk. Keep it narrow. Callers:
    the assistant and prompt save paths.
    """
    computed = {field_id for field_id, field in schema.fields.items() if field.type == "computed"}
    return {key: value for key, value in metadata.items() if key not in computed}


class ComputedMetadataMixin:
    def _stamp_resolved_cascade(
        self,
        root_node: StructureNode,
        cascade_fields: list[str],
        scene_front: dict[str, tuple[str | None, dict[str, Any]]],
        book_default: dict[str, Any],
    ) -> None:
        """Fold `cascade_fields` down the tree and stamp `resolved_cascade` per node
        (ADR-0079). Own values come from the pre-built front-matter index — which
        covers every manuscript node, containers included — so no per-node file read.
        A no-op when the schema declares no cascade_fields."""
        if not cascade_fields:
            return

        def own_metadata(node: StructureNode) -> dict[str, Any]:
            pair = scene_front.get(node.scene_id) if node.scene_id else None
            return (pair[1] if pair else {}) or {}

        TreeStructureService.walk(
            root_node, _CascadeResolver(cascade_fields, own_metadata, book_default)
        )

    def _computed_entry_metadata(
        self,
        body: str,
        node_id: str | None = None,
        entry_type: str | None = None,
        schema: MetadataSchema | None = None,
        structure: StructureDocument | None = None,
    ) -> dict[str, Any]:
        computed: dict[str, Any] = {}
        if schema is None:
            schema = self.read_metadata_schema()
        entry_definition = schema.entry_types.get(entry_type or "")
        field_ids = entry_definition.fields if entry_definition else ["word_count"]
        for field_id in field_ids:
            field = schema.fields.get(field_id)
            if field is None or field.type != "computed" or not field.computed:
                continue
            function = field.computed.get("function")
            if function == "word_count":
                without_comments = re.sub(r"<!--[\s\S]*?-->", " ", body)
                computed[field_id] = len(WORD_PATTERN.findall(without_comments))
            elif function == "counter" and node_id and entry_type:
                if structure is None:
                    structure = self.read_structure()
                value = self._counter_value(structure, node_id, entry_type, field_id, field.computed)
                if value is not None:
                    computed[field_id] = value
            elif function == "cost":
                # Scope-aware sum over the ai_invocations sidecar log.
                # `scene` and `character` need a node_id to filter on;
                # `project` ignores it and sums the whole log.
                scope = field.computed.get("scope", "scene")
                total = self._compute_invocation_cost(scope, node_id)
                if total is not None:
                    computed[field_id] = total
        return computed

    def _counter_value(
        self, structure: StructureDocument, node_id: str, entry_type: str, field_id: str, spec: dict[str, Any]
    ) -> int | None:
        """One node's `{number}`: a container's is by its level, which the tree
        read already stamped (`_number_containers`, ADR-0094 §7); a scene's is
        by its type within the field's scope, as before."""
        node = TreeStructureService.find_node(structure, node_id)
        if node is not None and node.level is not None:
            return node.computed_metadata.get(field_id)
        return self._compute_counter(structure.root, node_id, entry_type, spec.get("scope", "siblings"))

    def _compute_invocation_cost(self, scope: str, node_id: str | None) -> float | None:
        # Sum cost_usd across `ai_invocations.yaml` rows matching the scope.
        #   scene     → records whose scene_id == node_id
        #   character → records whose character_id == node_id
        #   project   → all records (node_id ignored)
        # Returns None for unknown scopes or when a node-bound scope is
        # asked without a node_id, so the caller can skip emitting the
        # computed field entirely instead of writing a misleading 0.
        if scope in ("scene", "character") and not node_id:
            return None
        if scope not in ("scene", "character", "project"):
            return None
        # Routes through the shared ledger scan (#1708). Unlike the per-chat
        # projection and the summary, a computed cost field reports 0.0 (not
        # None) for a scope with no priced rows — the resolver only emits the
        # field when it is non-None, so 0.0 keeps a genuine "no spend yet"
        # figure visible rather than dropping the field.
        total = 0.0
        for record, cost, _input, _output in self._iter_invocation_rows():
            if scope == "scene" and record.get("scene_id") != node_id:
                continue
            if scope == "character" and record.get("character_id") != node_id:
                continue
            if cost is not None:
                total += cost
        return total

    def _compute_counter(self, root: StructureNode, target_scene_id: str, entry_type: str, scope: str) -> int | None:
        if scope == "siblings":
            return self._counter_among_siblings(root, target_scene_id, entry_type)
        if scope == "manuscript":
            return self._counter_in_manuscript(root, target_scene_id, entry_type)
        return None

    def _counter_among_siblings(self, root: StructureNode, target_scene_id: str, entry_type: str) -> int | None:
        for i, child in enumerate(root.children):
            if child.scene_id == target_scene_id:
                counter = 0
                for j in range(i + 1):
                    if root.children[j].type == entry_type:
                        counter += 1
                return counter
        for child in root.children:
            found = self._counter_among_siblings(child, target_scene_id, entry_type)
            if found is not None:
                return found
        return None

    def _counter_in_manuscript(self, root: StructureNode, target_scene_id: str, entry_type: str) -> int | None:
        ordinal = _ManuscriptOrdinal(entry_type, target_scene_id)
        TreeStructureService.walk(root, ordinal)
        return ordinal.result

    def _number_containers(self, document: StructureDocument, schema: MetadataSchema) -> None:
        """Stamp each container's `{number}` counter by its LEVEL (ADR-0094 §7).

        A container counts among the containers at its own level that show a
        number — whose display template contains `{number}` — so a Prologue
        sub-type with a template of `{title}` beside the acts takes no act's
        number. The level entry's `numbering` says where the count runs:
        `restart` within the parent (Act 2's chapters are 1, 2), `continuous`
        through the whole tree (they are 3, 4). The type does not matter: one
        container type spans every level, and a book that kept its act and
        chapter types numbers them the same way. A counter field that says
        `scope: manuscript` runs on whatever the level says — the author asked
        for that field to count through the book."""
        levels = document.levels
        counters: dict[int, int] = {}

        def shows_number(node: StructureNode) -> bool:
            definition = schema.entry_types.get(node.type)
            return bool(definition and definition.display_template and "{number}" in definition.display_template)

        def counter_fields(node: StructureNode) -> list[tuple[str, bool]]:
            """Each counter field on the node's type, and whether it runs on
            through the book whatever the level says."""
            definition = schema.entry_types.get(node.type)
            return [
                (field_id, (field.computed or {}).get("scope") == "manuscript")
                for field_id in (definition.fields if definition else [])
                if (field := schema.fields.get(field_id)) is not None
                and field.type == "computed"
                and (field.computed or {}).get("function") == "counter"
            ]

        def visit(node: StructureNode) -> None:
            within_parent: dict[int, int] = {}
            for child in node.children:
                if child.level is not None and shows_number(child):
                    counters[child.level] = counters.get(child.level, 0) + 1
                    within_parent[child.level] = within_parent.get(child.level, 0) + 1
                    level_runs_on = bool(levels) and levels[min(child.level, len(levels)) - 1].numbering == "continuous"
                    for field_id, runs_on in counter_fields(child):
                        child.computed_metadata[field_id] = (
                            counters[child.level] if runs_on or level_runs_on else within_parent[child.level]
                        )
                visit(child)

        visit(document.root)
