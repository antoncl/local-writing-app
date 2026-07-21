"""Computed-metadata slice of ProjectService (#14 backend split).

Derived read-time fields that never persist to disk: word_count, the per-scope
scene counters (within siblings / within the whole manuscript), and the
AI-invocation cost rollup behind the `cost` computed field. `ProjectService`
composes it; inputs (`read_structure`, `list_ai_invocations`) resolve via MRO.

This dispatch covers the BODY-derived functions only — see
`default_schema.AUTHORABLE_COMPUTED_FUNCTIONS` / `BUILTIN_COMPUTED_FUNCTIONS`
for the full vocabulary. The built-in ones are stamped by their own resolver
(`references` at view-eval time on the frontend; the assistant curation pair by
the layer traversal in `assistants.py`), so an unknown function falling through
the chain below and yielding no value is correct, not a gap.
"""

from __future__ import annotations

import re
from typing import Any

from app.models import MetadataSchema, StructureDocument, StructureNode

WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")


class ComputedMetadataMixin:
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
                scope = field.computed.get("scope", "siblings")
                value = self._compute_counter(structure.root, node_id, entry_type, scope)
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
        total = 0.0
        for record in self._read_ai_invocations_raw():
            if scope == "scene" and record.get("scene_id") != node_id:
                continue
            if scope == "character" and record.get("character_id") != node_id:
                continue
            cost = record.get("cost_usd")
            if isinstance(cost, (int, float)):
                total += float(cost)
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
        result: list[int | None] = [None]
        counter = [0]

        def walk(node: StructureNode) -> None:
            if result[0] is not None:
                return
            if node.type == entry_type:
                counter[0] += 1
                if node.scene_id == target_scene_id:
                    result[0] = counter[0]
                    return
            for child in node.children:
                walk(child)
                if result[0] is not None:
                    return

        walk(root)
        return result[0]
