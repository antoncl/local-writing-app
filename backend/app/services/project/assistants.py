"""Assistant-entry slice of ProjectService (#14 backend split).

Assistants are file-backed, layered, machine-first Node markdown files
(the canonical roster lives under the per-user machine config dir; project
layers can add their own). This mixin owns their CRUD plus the assistant-
scoped index/resolve helpers; `ProjectService` composes it. Method bodies
moved verbatim from project_service.py — shared helpers they call
(`self._build_node_index`, `self._collect_machine_layer_assistants`,
`self._read_markdown_with_front_matter`, `self._read_front_matter_only`,
`self._normalise_metadata`, `self._revision`, `self._node_id_for_path`,
`self._write_node_entry_file`, `self._filepath_for_new_node`,
`self._new_id`, `self._check_entry_type_kind`, `self._maybe_rename_node_file`,
`self._read_yaml`, `self._write_yaml`, `self._metadata_schema_layer_id`,
`self._project_layer_folders`, `self.root_path`) still live on the core
class and resolve through the MRO at call time.

`_build_assistant_index` moves here even though it instantiates `NodeIndex`
and calls `_collect_machine_layer_assistants`: `NodeIndex` is imported from
the shared node_index module, and `_collect_machine_layer_assistants` stays
in core (it's shared with `_build_node_index`) — reached via self → MRO.
`resolve_assistant` is also called by ChatSessionsMixin.save_chat_session;
that call resolves here through the composed class's MRO.
"""

from __future__ import annotations

from pathlib import Path

from app.models import (
    AssistantEntry,
    AssistantEntryList,
    AssistantEntrySummary,
    CreateAssistantEntryRequest,
    ReorderAssistantsRequest,
    SaveAssistantEntryRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndex, NodeIndexEntry


class AssistantEntriesMixin:
    def list_assistant_entries(self) -> AssistantEntryList:
        index = self._build_assistant_index()
        entries: list[AssistantEntrySummary] = []
        layer_paths: dict[str, Path] = {}
        for entry in index.by_id.values():
            if entry.kind != "assistant":
                continue
            try:
                front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "assistant"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "assistant"
            entries.append(
                AssistantEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
            layer_paths.setdefault(entry.source_layer_id, entry.path.parent)
        # Per-layer ordering: read each layer's .order.yaml (if any) and use
        # it as the primary sort key. Entries not listed in the order file
        # sort alphabetically by title after the listed ones.
        order_by_layer: dict[str, dict[str, int]] = {}
        for layer_id, folder in layer_paths.items():
            ordered = self._read_assistants_order(folder)
            order_by_layer[layer_id] = {entry_id: idx for idx, entry_id in enumerate(ordered)}

        def sort_key(entry: AssistantEntrySummary):
            positions = order_by_layer.get(entry.source_layer_id, {})
            if entry.id in positions:
                return (0, positions[entry.id], "")
            return (1, 0, entry.title.lower())

        entries.sort(key=sort_key)
        return AssistantEntryList(entries=entries)

    def reorder_assistant_entries(
        self, request: ReorderAssistantsRequest
    ) -> AssistantEntryList:
        folder = self._assistant_layer_folder_for_id(request.layer_id)
        if not folder.exists():
            raise ProjectServiceError(
                f"No assistants folder exists at layer {request.layer_id!r}.", 404
            )
        # Validate that every supplied id exists in this layer.
        layer_ids: set[str] = set()
        for path in folder.glob("*.md"):
            try:
                front = self._read_front_matter_only(path, strict=True)
            except ProjectServiceError:
                continue
            entry_id = front.get("id")
            if isinstance(entry_id, str) and entry_id.strip():
                layer_ids.add(entry_id.strip())
        unknown = [eid for eid in request.ordered_ids if eid not in layer_ids]
        if unknown:
            raise ProjectServiceError(
                f"Unknown assistant id(s) for layer: {', '.join(unknown)}.", 422
            )
        # Preserve only the supplied ids; unlisted entries trail alphabetically.
        dedup: list[str] = []
        seen: set[str] = set()
        for entry_id in request.ordered_ids:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            dedup.append(entry_id)
        self._write_assistants_order(folder, dedup)
        return self.list_assistant_entries()

    def _read_assistants_order(self, folder: Path) -> list[str]:
        order_file = folder / ".order.yaml"
        if not order_file.exists():
            return []
        try:
            data = self._read_yaml(order_file)
        except ProjectServiceError:
            return []
        ids = data.get("ids") if isinstance(data, dict) else None
        if not isinstance(ids, list):
            return []
        return [str(entry_id) for entry_id in ids if isinstance(entry_id, str)]

    def _write_assistants_order(self, folder: Path, ordered_ids: list[str]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._write_yaml(folder / ".order.yaml", {"ids": list(ordered_ids)})

    def read_assistant_entry(self, entry_id: str) -> AssistantEntry:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        path = index_entry.path
        front_matter, _body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "assistant"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Assistant {node_id} has invalid entry_type; it must be text.", 422)
        return AssistantEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=raw_entry_type,
            metadata=self._normalise_metadata(front_matter.get("metadata"), path),
            source_layer_id=index_entry.source_layer_id,
            source_layer_label=index_entry.source_layer_label,
        )

    def create_assistant_entry(self, request: CreateAssistantEntryRequest) -> AssistantEntry:
        target_folder = self._assistant_layer_folder_for_id(request.layer_id)
        self._check_entry_type_kind(request.entry_type, "assistant")
        entry_id = self._new_id("assistant")
        target_folder.mkdir(parents=True, exist_ok=True)
        path = self._filepath_for_new_node(target_folder, request.title)
        self._write_node_entry_file(
            path,
            entry_id,
            request.title,
            request.entry_type,
            {},
            "",
        )
        return self.read_assistant_entry(entry_id)

    def save_assistant_entry(self, entry_id: str, request: SaveAssistantEntryRequest) -> AssistantEntry:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        path = index_entry.path
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Assistant changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "assistant")
        metadata = self._normalise_metadata(request.metadata, path)
        self._write_node_entry_file(path, node_id, request.title, request.entry_type, metadata, "")
        self._maybe_rename_node_file(path, request.title)
        return self.read_assistant_entry(node_id)

    def delete_assistant_entry(self, entry_id: str) -> AssistantEntryList:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        if index_entry.path.exists():
            index_entry.path.unlink()
        return self.list_assistant_entries()

    def _assistant_layer_folder_for_id(self, layer_id: str) -> Path:
        """Resolve a layer_id (from list_metadata_schema_layers, or "") to its
        assistants/ folder. Empty layer_id → machine config dir (the canonical
        per-user roster)."""
        from app.services import machine_settings as ms_service

        if not layer_id:
            return ms_service.assistants_dir()
        machine_dir = ms_service.assistants_dir().parent
        if self._metadata_schema_layer_id(machine_dir) == layer_id:
            return machine_dir / "assistants"
        if self.root_path is not None:
            for folder in self._project_layer_folders(self.root_path):
                if self._metadata_schema_layer_id(folder) == layer_id:
                    return folder / "assistants"
        raise ProjectServiceError(f"Unknown layer id {layer_id}.", 422)

    def _build_assistant_index(self) -> NodeIndex:
        """Build a node index covering just the assistant kind. Works without
        an open project (machine layer only) or with one (full layered walk).
        """
        if self.root_path is not None:
            return self._build_node_index(self.root_path)
        index = NodeIndex()
        self._collect_machine_layer_assistants(
            index, duplicate_relative_to=Path("/")
        )
        return index

    def resolve_assistant(self, assistant_id: str | None) -> AssistantEntry | None:
        """Look up an assistant by id; falls back to the entry flagged
        is_default. Returns None when nothing matches — callers fall back to
        the legacy default_provider / default_models path."""
        index = self._build_assistant_index()
        if assistant_id:
            entry = index.by_id.get(assistant_id)
            if entry is None or entry.kind != "assistant":
                return None
            return self._read_assistant_from_index_entry(entry)
        # No id supplied: find the entry flagged is_default in the highest-
        # priority (descendant) layer present. The index is already iterated
        # outermost → innermost with descendant-wins, so the value in by_id
        # is the right one. Search by metadata.is_default.
        for entry in index.by_id.values():
            if entry.kind != "assistant":
                continue
            data = self._read_assistant_from_index_entry(entry)
            if data is None:
                continue
            if bool(data.metadata.get("is_default")):
                return data
        return None

    def _read_assistant_from_index_entry(
        self, entry: NodeIndexEntry
    ) -> AssistantEntry | None:
        try:
            front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return None
        raw_entry_type = front_matter.get("entry_type") or "assistant"
        return AssistantEntry(
            id=entry.id,
            title=str(front_matter.get("title") or entry.id),
            revision=self._revision(entry.path),
            entry_type=raw_entry_type if isinstance(raw_entry_type, str) else "assistant",
            metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )
