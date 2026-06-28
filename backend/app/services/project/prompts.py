"""Prompt-entry slice of ProjectService (#14 backend split).

Prompt entries are layered Node markdown files under `<project>/prompts/`
(plus any schema layers). This mixin owns their CRUD; `ProjectService`
composes it. Method bodies moved verbatim from project_service.py —
shared helpers they call (`self._build_node_index`,
`self._read_markdown_with_front_matter`, `self._normalise_metadata`,
`self._require_project`, `self._check_entry_type_kind`, `self._new_id`,
`self.read_metadata_schema`, `self._initial_metadata_from_defaults`,
`self._write_node_entry_file`, `self._filepath_for_new_node`,
`self._path_for_node_id`, `self._node_id_for_path`, `self._revision`,
`self._read_front_matter_only`, `self._maybe_rename_node_file`) still
live on the core class and resolve through the MRO at call time.

`_check_entry_type_kind` stays in core: it's shared by the assistant
and lore slices too.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    CreatePromptEntryRequest,
    MetadataValue,
    PromptEntry,
    PromptEntryList,
    PromptEntrySummary,
    PromptInputDefinition,
    SavePromptEntryRequest,
)
from app.services.project.errors import ProjectServiceError


class PromptEntriesMixin:
    def list_prompt_entries(self) -> PromptEntryList:
        index = self._build_node_index()
        entries: list[PromptEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "prompt":
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "prompt"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "prompt"
            entries.append(
                PromptEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body=body,
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
                    inputs=self._parse_prompt_inputs(front_matter.get("inputs")),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return PromptEntryList(entries=entries)

    def create_prompt_entry(self, request: CreatePromptEntryRequest) -> PromptEntry:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "prompt")
        entry_id = self._new_id("prompt")
        initial_body = ""
        initial_inputs: list[PromptInputDefinition] = []
        initial_metadata: dict[str, MetadataValue] = {}
        try:
            schema = self.read_metadata_schema()
            entry_type_def = schema.entry_types.get(request.entry_type)
            if entry_type_def:
                initial_body = entry_type_def.default_body
                initial_inputs = list(entry_type_def.default_inputs)
            initial_metadata = self._initial_metadata_from_defaults(request.entry_type, schema)
        except Exception:
            pass
        entry = PromptEntry(
            id=entry_id,
            title=request.title,
            body=initial_body,
            revision="",
            entry_type=request.entry_type,
            metadata=initial_metadata,
            inputs=initial_inputs,
        )
        inputs_payload = [i.model_dump(exclude_none=True) for i in entry.inputs]
        self._write_node_entry_file(
            self._filepath_for_new_node(root / "prompts", request.title),
            entry.id,
            entry.title,
            entry.entry_type,
            entry.metadata,
            entry.body,
            extra={"inputs": inputs_payload} if inputs_payload else None,
            omit_empty_metadata=True,
        )
        return self.read_prompt_entry(entry_id)

    def read_prompt_entry(self, entry_id: str) -> PromptEntry:
        index_entry = self._build_node_index().by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "prompt":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "prompt")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "prompt"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Prompt {node_id} has invalid entry_type; it must be text.", 422)
        return PromptEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body=body,
            revision=self._revision(path),
            entry_type=raw_entry_type,
            metadata=self._normalise_metadata(front_matter.get("metadata"), path),
            inputs=self._parse_prompt_inputs(front_matter.get("inputs")),
            computed_metadata={},
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_prompt_entry(self, entry_id: str, request: SavePromptEntryRequest) -> PromptEntry:
        path = self._path_for_node_id(entry_id, "prompt")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Prompt changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "prompt")
        metadata = self._normalise_metadata(request.metadata, path)
        inputs_payload = [i.model_dump(exclude_none=True) for i in request.inputs]
        self._write_node_entry_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            metadata,
            request.body,
            extra={"inputs": inputs_payload},
            omit_empty_metadata=True,
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_prompt_entry(node_id)

    @staticmethod
    def _parse_prompt_inputs(raw: Any) -> list[PromptInputDefinition]:
        from pydantic import ValidationError

        if not isinstance(raw, list):
            return []
        parsed: list[PromptInputDefinition] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(PromptInputDefinition.model_validate(item))
            except ValidationError:
                # Skip malformed entries rather than fail the whole prompt load.
                # Narrowed from `except Exception` after a missing import was
                # silently swallowed (NameError caught as "malformed") and
                # every input was discarded.
                continue
        return parsed

    def delete_prompt_entry(self, entry_id: str) -> PromptEntryList:
        path = self._path_for_node_id(entry_id, "prompt")
        if path.exists():
            path.unlink()
        return self.list_prompt_entries()
