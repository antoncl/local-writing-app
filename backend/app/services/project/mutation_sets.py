"""Mutation-set slice of ProjectService (#62, GH #33).

A mutation set is a reusable, body-less Node kind (`mutation_set`): an
ordered list of `(field, op, value)` rows plus a `target_entry_type` (the lore
entry-type its rows apply to). It expands to ordinary inline Model-A markers when
applied to a chosen entity. It is a **stamp, not a live link**: applied markers
are independent; edit-once-propagate is the deferred v2 (#66).

The entity binding is **optional** (ADR-0055 §3): unset ⇒ a reusable template,
entity chosen at apply time; set (`target_entity`) ⇒ an entity-*pinned* one-off,
offered only for its own entity and stamped on apply. The pin is a `metadata`
entity_ref (edge + reference-integrity), distinct from the top-level
`target_entry_type`/`rows`.

Storage mirrors prompt entries — layered Node markdown files under
`<project>/mutation-sets/`, but with **no prose body**: the rows + target
entry-type live in front matter (via `_write_node_entry_file`'s `extra=`), the
same way prompts store their `inputs`. `ProjectService` composes this mixin;
shared IO/index helpers resolve through the MRO (see `prompts.py`).
"""

from __future__ import annotations

from typing import Any

from app.models import (
    CreateMutationSetEntryRequest,
    MutationSetEntry,
    MutationSetEntryList,
    MutationSetEntrySummary,
    MutationSetRow,
    SaveMutationSetEntryRequest,
)
from app.services.project.errors import ProjectServiceError


class MutationSetEntriesMixin:
    def list_mutation_set_entries(self) -> MutationSetEntryList:
        index = self._build_node_index()
        entries: list[MutationSetEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "mutation_set":
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            rows = self._parse_mutation_set_rows(front_matter.get("rows"))
            entries.append(
                MutationSetEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=self._mutation_set_entry_type(front_matter),
                    target_entry_type=str(front_matter.get("target_entry_type") or ""),
                    target_entity=self._mutation_set_target_entity(front_matter),
                    row_count=len(rows),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return MutationSetEntryList(entries=entries)

    def create_mutation_set_entry(
        self, request: CreateMutationSetEntryRequest
    ) -> MutationSetEntry:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "mutation_set")
        entry_id = self._new_id("mutation_set")
        self._write_mutation_set_file(
            self._filepath_for_new_node(root / "mutation-sets", request.title),
            entry_id,
            request.title,
            request.entry_type,
            request.target_entry_type,
            request.target_entity,
            request.rows,
        )
        return self.read_mutation_set_entry(entry_id)

    def read_mutation_set_entry(self, entry_id: str) -> MutationSetEntry:
        index_entry = self._build_node_index().by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "mutation_set":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "mutation_set")
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        return MutationSetEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=self._mutation_set_entry_type(front_matter),
            target_entry_type=str(front_matter.get("target_entry_type") or ""),
            target_entity=self._mutation_set_target_entity(front_matter),
            rows=self._parse_mutation_set_rows(front_matter.get("rows")),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_mutation_set_entry(
        self, entry_id: str, request: SaveMutationSetEntryRequest
    ) -> MutationSetEntry:
        path = self._path_for_node_id(entry_id, "mutation_set")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Mutation set changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "mutation_set")
        self._write_mutation_set_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            request.target_entry_type,
            request.target_entity,
            request.rows,
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_mutation_set_entry(node_id)

    def delete_mutation_set_entry(self, entry_id: str) -> MutationSetEntryList:
        path = self._path_for_node_id(entry_id, "mutation_set")
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        return self.list_mutation_set_entries()

    # ----- helpers --------------------------------------------------------

    def _write_mutation_set_file(
        self,
        path: Any,
        node_id: str,
        title: str,
        entry_type: str,
        target_entry_type: str,
        target_entity: str,
        rows: list[MutationSetRow],
    ) -> None:
        rows_payload = [row.model_dump() for row in rows]
        # ADR-0055 §3: the entity pin is a `metadata` entity_ref (so it earns a
        # set→subject edge + reference-integrity), NOT top-level front-matter like
        # target_entry_type/rows. Empty ⇒ no metadata block (omit_empty_metadata),
        # so a reusable set's file is byte-identical to today's.
        metadata = {"target_entity": target_entity} if target_entity else {}
        self._write_node_entry_file(
            path,
            node_id,
            title,
            entry_type,
            metadata,
            "",  # body-less: rows live in front matter, not a prose body
            extra={"target_entry_type": target_entry_type, "rows": rows_payload},
            omit_empty_metadata=True,
        )

    @staticmethod
    def _mutation_set_entry_type(front_matter: dict[str, Any]) -> str:
        raw = front_matter.get("entry_type") or "mutation_set:mutation_set"
        return raw if isinstance(raw, str) else "mutation_set:mutation_set"

    @staticmethod
    def _mutation_set_target_entity(front_matter: dict[str, Any]) -> str:
        # The entity pin round-trips through `metadata.target_entity` — the same
        # top-level-field ↔ metadata projection chat sessions use for `subject`.
        metadata = front_matter.get("metadata")
        if not isinstance(metadata, dict):
            return ""
        return str(metadata.get("target_entity", "") or "")

    @staticmethod
    def _parse_mutation_set_rows(raw: Any) -> list[MutationSetRow]:
        from pydantic import ValidationError

        if not isinstance(raw, list):
            return []
        parsed: list[MutationSetRow] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(MutationSetRow.model_validate(item))
            except ValidationError:
                continue  # skip a malformed row rather than fail the whole set
        return parsed
