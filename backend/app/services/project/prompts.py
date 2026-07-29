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

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.project.node_index import NodeIndexEntry


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
            raw_entry_type = front_matter.get("entry_type") or "prompt:base"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "prompt:base"
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
                    is_library=entry.is_library,
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
        index = self._build_node_index()
        index_entry = index.by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "prompt":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "prompt")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "prompt:base"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Prompt {node_id} has invalid entry_type; it must be text.", 422)
        # Hide references whose target is gone, exactly as the scene/lore/research
        # read paths do (#345). The schema editor can put an `entity_ref` on any
        # entry_type, so "prompts don't hold references" was an assumption, not a
        # constraint — and without this the picker renders a row for a node that
        # no longer exists.
        metadata = self._strip_dangling_references(
            self._normalise_metadata(front_matter.get("metadata"), path),
            self.read_metadata_schema(),
            index,
        )
        return PromptEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body=body,
            revision=self._revision(path),
            entry_type=raw_entry_type,
            metadata=metadata,
            inputs=self._parse_prompt_inputs(front_matter.get("inputs")),
            computed_metadata={},
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
            is_library=index_entry.is_library if index_entry else False,
        )

    def _prompt_winner_is_owned(self, winner: NodeIndexEntry, root: Path) -> bool:
        """Whether the open project OWNS this prompt winner, vs inheriting it from
        the built-in Library or an ancestor project.

        The single predicate for the owned/inherited split, so the two consumers
        cannot drift to opposite polarity: `fork_prompt_entry` clones only what is
        NOT owned, `_reject_inherited_prompt_write` refuses to write what is NOT
        owned. (lore.py / overrides.py compute the same split for their kinds;
        folding those onto one helper is out of scope here — #676 review.)
        """
        return winner.source_layer_id == self._metadata_schema_layer_id(root)

    def fork_prompt_entry(self, entry_id: str) -> PromptEntry:
        """Clone an inherited prompt into this project as an editable copy
        (ADR-0049 §5; generalized to ancestor-project prompts per #676).

        Unlike lore's fork-to-here (`fork_lore_entry`, which keeps the id and
        shadows the source to sever an *inherited* entry), a prompt clone mints
        a **new id** and leaves the inherited original in place. Keeping the id
        would make the copy shadow the source — which is exactly what a
        per-project *hide* (slice 3) does — so clone and hide stay orthogonal.
        The inherited prompt is a starting point lifted into the project, not an
        override of the layer below (the "duplicate the default view" gesture):
        a writer clones a prompt to *adapt* it, they do not correct it in place.

        Applies to any inherited winner — a built-in Library node **or** an
        ancestor *project's* prompt (#676). A prompt this project already owns is
        directly editable, so there is nothing to clone and it is refused.
        """
        root = self._require_project()
        winner = self._build_node_index().by_id.get(entry_id)
        if winner is None or winner.kind != "prompt":
            raise ProjectServiceError(f"Prompt {entry_id} not found.", 404)
        if self._prompt_winner_is_owned(winner, root):
            raise ProjectServiceError(
                f"Prompt {entry_id} is owned by this project and is directly "
                "editable; there is nothing to clone.",
                409,
            )
        source = self.read_prompt_entry(entry_id)
        request = CreatePromptEntryRequest(title=source.title, entry_type=source.entry_type)
        clone = self.create_prompt_entry(request)
        # `create_prompt_entry` seeds from the entry type (an empty body now that
        # the shipped bodies live only in the Library, §7); overwrite with the
        # Library node's own body/metadata/inputs so the clone is a faithful copy.
        return self.save_prompt_entry(
            clone.id,
            SavePromptEntryRequest(
                title=source.title,
                body=source.body,
                entry_type=source.entry_type,
                metadata=source.metadata,
                inputs=source.inputs,
                base_revision=clone.revision,
            ),
        )

    def _reject_inherited_prompt_write(self, entry_id: str) -> None:
        """Refuse a write to a prompt this project does not own.

        A prompt whose index winner is an ancestor's — or a built-in Library
        node (ADR-0049 §3) — is read-only in place. For the Library this is the
        structural "never a write target" guarantee at the actual boundary: the
        save/delete is refused here, not merely hidden in the UI, so overwriting
        or deleting a shipped app file is unconstructable rather than validated.
        (Prompts have no per-layer override or authoring-L path the way lore
        does — the only path to a change is to clone the prompt into this
        project, which slice 2 adds.)
        """
        root = self._require_project()
        winner = self._build_node_index().by_id.get(entry_id)
        if winner is None or winner.kind != "prompt":
            return
        if not self._prompt_winner_is_owned(winner, root):
            label = winner.source_layer_label or "an ancestor"
            raise ProjectServiceError(
                f"This prompt is inherited from {label} and is read-only here.", 409
            )

    def save_prompt_entry(self, entry_id: str, request: SavePromptEntryRequest) -> PromptEntry:
        self._reject_inherited_prompt_write(entry_id)
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
        # A prompt's `assistant_tags` (its soft assistant scope) feed the same
        # machine-global vocabulary as assistants' own tags (#88).
        from app.services import machine_settings as ms_service

        ms_service.register_assistant_tags(ms_service.tag_names_from_field(metadata.get("assistant_tags")))
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
        self._reject_inherited_prompt_write(entry_id)
        path = self._path_for_node_id(entry_id, "prompt")
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        return self.list_prompt_entries()
