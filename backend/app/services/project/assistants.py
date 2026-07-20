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
`self._read_yaml`, `self._write_yaml`, `self.root_path`) still live on the
core class and resolve through the MRO at call time. The layer walk
(`self.project_layers`, `self.layer_by_id`, `self._metadata_schema_layer_id`,
`self._machine_layer_folder`) lives in `layers.py` since #329 and resolves the
same way — the roster's layer rank now comes from the walk rather than from
`index.by_id` insertion order.

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
        # Layer rank + folder read straight off the one walk (#329). Both used
        # to be inferred from the entries themselves — the folder from the first
        # entry's `path.parent`, the rank from `index.by_id` insertion order.
        # That misordered the roster in two ways. Today: a cross-layer id
        # collision reuses the *ancestor's* dict slot (`by_id[id] = entry`
        # overwrites the value, keeps the position), so a descendant that
        # shadows an outer id was "first seen" at the outer layer's position and
        # its whole bucket jumped up the roster. Later: an incremental index
        # patch (#307) re-parsing one file would move its layer to the end.
        # The walk is machine-layer-first, then base folder → … → open
        # project, so rank stays the LEADING sort term and keeps the roster
        # layer-grouped (Machine bucket first). That is the ADR-0037 §7
        # assumption the Assistants default's `group_by: source_layer` relies on
        # under the first-seen bucket rule; without it a fresh project-layer
        # "Alpha" precedes a machine "Zed" whenever no `.order.yaml` exists (#224).
        layer_paths, layer_rank = self._assistant_layer_paths_and_ranks()
        for entry in index.by_id.values():
            if entry.kind != "assistant":
                continue
            try:
                front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "assistant:assistant"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "assistant:assistant"
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
        # Per-layer ordering: read each layer's .order.yaml (if any) and use
        # it as the secondary sort key (within a layer). Entries not listed in
        # the order file sort alphabetically by title after the listed ones.
        order_by_layer: dict[str, dict[str, int]] = {}
        for layer_id, folder in layer_paths.items():
            ordered = self._read_assistants_order(folder)
            order_by_layer[layer_id] = {entry_id: idx for idx, entry_id in enumerate(ordered)}

        def sort_key(entry: AssistantEntrySummary):
            rank = layer_rank.get(entry.source_layer_id, len(layer_rank))
            positions = order_by_layer.get(entry.source_layer_id, {})
            if entry.id in positions:
                return (rank, 0, positions[entry.id], "")
            return (rank, 1, 0, entry.title.lower())

        entries.sort(key=sort_key)
        return AssistantEntryList(entries=entries)

    def _assistant_layer_paths_and_ranks(self) -> tuple[dict[str, Path], dict[str, int]]:
        """Each layer's `assistants/` folder and its rank, from the one walk.

        Without an open project only the machine layer exists — the same
        degenerate case `_build_assistant_index` handles.
        """
        if self.root_path is not None:
            layers = self.project_layers(self.root_path, include_machine=True)
        else:
            machine_layer = self.machine_layer()
            layers = [] if machine_layer is None else [machine_layer]
        layer_paths = {layer.id: layer.folder / "assistants" for layer in layers}
        layer_rank = {layer.id: layer.rank for layer in layers}
        return layer_paths, layer_rank

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
        raw_entry_type = front_matter.get("entry_type") or "assistant:assistant"
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
        # Register the assistant's tags in the machine-global vocabulary so the
        # `[+]` picker + tag manager surface them (#88).
        from app.services import machine_settings as ms_service

        ms_service.register_assistant_tags(ms_service.tag_names_from_field(metadata.get("tags")))
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
        per-user roster).

        Reverses the id over the one walk (#329) instead of re-deriving the
        chain. The machine layer stays reachable two ways — "" and its folder
        hash — which the create/reorder endpoints both rely on.
        """
        from app.services import machine_settings as ms_service

        if not layer_id:
            return ms_service.assistants_dir()
        # Deliberately not `_machine_layer_folder()`: that gates on the
        # assistants/ folder already existing, and this path is how the *first*
        # machine assistant gets created.
        machine_dir = ms_service.assistants_dir().parent
        if self._metadata_schema_layer_id(machine_dir) == layer_id:
            return machine_dir / "assistants"
        if self.root_path is not None:
            layer = self.layer_by_id(self.root_path, layer_id)
            if layer is not None:
                return layer.folder / "assistants"
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
        """Look up an assistant by id; with no id, falls back to the **topmost**
        assistant in roster (manual) order. Returns None when nothing matches —
        callers fall back to the legacy default_provider / default_models path.

        The old ``is_default`` flag is retired (ADR-0024): manual order already
        expresses global preference, so "topmost" is the dynamic default, and it
        degrades to exactly the old behaviour when no scope is declared. Any
        prompt-scoped default (topmost *matching* a tag) is resolved on the
        frontend, which then supplies a concrete id here."""
        index = self._build_assistant_index()
        if assistant_id:
            entry = index.by_id.get(assistant_id)
            if entry is None or entry.kind != "assistant":
                return None
            return self._read_assistant_from_index_entry(entry)
        # No id supplied: the topmost assistant in the **sorted roster** — the
        # same order the UI shows (per-layer .order.yaml, then title), so the
        # backend's fallback default and the frontend's dynamic default agree.
        roster = self.list_assistant_entries().entries
        if not roster:
            return None
        entry = index.by_id.get(roster[0].id)
        return self._read_assistant_from_index_entry(entry) if entry else None

    def _read_assistant_from_index_entry(
        self, entry: NodeIndexEntry
    ) -> AssistantEntry | None:
        try:
            front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return None
        raw_entry_type = front_matter.get("entry_type") or "assistant:assistant"
        return AssistantEntry(
            id=entry.id,
            title=str(front_matter.get("title") or entry.id),
            revision=self._revision(entry.path),
            entry_type=raw_entry_type if isinstance(raw_entry_type, str) else "assistant:assistant",
            metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )
