"""Node-index + reference-resolution slice of ProjectService (#14 backend split).

`_build_node_index` walks every node markdown file (scenes, lore, prompts,
research, chats, plus the machine assistants layer) into an in-memory
`NodeIndex` keyed by id; the reference API (`resolve_references`,
`list_backlinks`, `list_reference_candidates`) and the node-identity helpers
(`_node_id_for_path`, `_path_for_node_id`, `_safe_relative`,
`_read_body_summary`) build on it. This mixin owns that subsystem; almost
every other slice consumes `_build_node_index` / `_node_id_for_path` /
`_path_for_node_id` via `self` → MRO, so they keep resolving unchanged.

Method bodies moved verbatim. Shared helpers they call (`self._require_project`,
`self._read_yaml`, `self._read_markdown_with_front_matter`,
`self._read_front_matter_only`, `self.read_metadata_schema`,
`self._project_layer_folders` and the schema-layer label helpers from
`MetadataSchemaMixin`) live elsewhere on the composed class.
`NodeIndex`/`NodeIndexEntry` come from the shared `node_index` module so this
slice imports them without a cycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models import (
    Backlink,
    BacklinksResponse,
    MetadataSchema,
    ReferenceCandidate,
    ReferenceCandidatesResponse,
    ReferenceResolveResponse,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndex, NodeIndexEntry


class ReferencesMixin:
    def _build_node_index(self, root: Path | None = None) -> NodeIndex:
        root = root or self._require_project()
        index = NodeIndex()
        # Machine config dir is a base layer for assistants only — it lives
        # outside the project tree and carries the user's roster.
        self._collect_machine_layer_assistants(index, duplicate_relative_to=root)
        layer_folders = self._project_layer_folders(root)
        # Outermost ancestor first so descendant entries overwrite on collision.
        for layer_index, folder in enumerate(layer_folders):
            layer_id = self._metadata_schema_layer_id(folder)
            layer_label = self._layer_label_for_folder(root, folder, layer_index)
            is_current_project = folder == root
            for kind, folder_name, default_entry_type in [
                ("scene", "scenes", "scene:scene"),
                # Research notes walk `research/notes/`. Treated like lore
                # (cross-layer) rather than scenes (book-scoped) — universe-
                # or series-level research notes are a natural use case.
                ("research", "research/notes", "research:note"),
                ("lore", "lore", "lore:lore_note"),
                ("prompt", "prompts", "prompt:prompt"),
                ("assistant", "assistants", "assistant:assistant"),
                # Reusable mutation sets (#62): body-less Node files under
                # `mutation-sets/`. Layered like lore/prompts (a werewolf
                # transform can live at any project level).
                ("mutation_set", "mutation-sets", "mutation_set:mutation_set"),
                # Saved views (0.5.0, #35/#78): body-less Node files under
                # `views/`, each carrying a ViewSpec in front matter. Layered
                # like mutation sets — a view can live at any project level.
                ("view", "views", "view:view"),
            ]:
                # Scenes stay book-scoped — only walk the current project's scenes folder.
                if kind == "scene" and not is_current_project:
                    continue
                self._collect_layer_entries(
                    folder=folder,
                    folder_name=folder_name,
                    kind=kind,
                    default_entry_type=default_entry_type,
                    layer_id=layer_id,
                    layer_label=layer_label,
                    index=index,
                    duplicate_relative_to=root,
                )
            # Chat sessions live as YAML files (not Node-shaped .md), so they
            # need their own collector. Read-only for now: this makes them
            # discoverable as nodes (kind="chat") for reference graphs and
            # the unified-CRUD migration to come, but ChatSession storage
            # remains the source of truth (Phase 3b-i / decisions-node-
            # editor-modularization).
            if is_current_project:
                self._collect_chat_entries(
                    folder=folder,
                    layer_id=layer_id,
                    layer_label=layer_label,
                    index=index,
                )
        return index

    def _collect_chat_entries(
        self,
        *,
        folder: Path,
        layer_id: str,
        layer_label: str,
        index: NodeIndex,
    ) -> None:
        """Walk <project>/chats/*.yaml and add an index entry per session.

        Storage stays YAML — this is just a discovery layer so chats are
        addressable from the unified node index alongside other kinds.
        """
        chats_dir = folder / "chats"
        if not chats_dir.exists():
            return
        for path in sorted(chats_dir.glob("*.yaml")):
            try:
                data = self._read_yaml(path)
            except Exception as exc:
                index.errors.append(f"Failed to read chat session {path.name}: {exc}")
                continue
            if not isinstance(data, dict):
                continue
            raw_id = data.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                continue
            chat_id = raw_id.strip()
            raw_title = data.get("title")
            title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else "Untitled chat"
            entry = NodeIndexEntry(
                id=chat_id,
                kind="chat",
                entry_type="chat:chat_session",
                path=path,
                title=title,
                source_layer_id=layer_id,
                source_layer_label=layer_label,
            )
            index.id_by_path[path.resolve()] = chat_id
            existing = index.by_id.get(chat_id)
            if existing is not None:
                # Chat ids are prefixed (`chat_…`) and minted via _new_id, so
                # cross-kind collisions shouldn't happen in practice. If one
                # ever does, surface it rather than silently shadowing.
                index.errors.append(
                    f"Chat id {chat_id} collides with an existing entry."
                )
                continue
            index.by_id[chat_id] = entry

    def _collect_machine_layer_assistants(
        self, index: NodeIndex, *, duplicate_relative_to: Path
    ) -> None:
        from app.services import machine_settings as ms_service

        machine_dir = ms_service.assistants_dir().parent
        if not (machine_dir / "assistants").exists():
            return
        self._collect_layer_entries(
            folder=machine_dir,
            folder_name="assistants",
            kind="assistant",
            default_entry_type="assistant:assistant",
            layer_id=self._metadata_schema_layer_id(machine_dir),
            layer_label="Machine",
            index=index,
            duplicate_relative_to=duplicate_relative_to,
        )

    def _collect_layer_entries(
        self,
        *,
        folder: Path,
        folder_name: str,
        kind: str,
        default_entry_type: str,
        layer_id: str,
        layer_label: str,
        index: NodeIndex,
        duplicate_relative_to: Path,
    ) -> None:
        for path in sorted((folder / folder_name).glob("*.md")):
            try:
                front_matter = self._read_front_matter_only(path, strict=True)
            except ProjectServiceError as exc:
                index.errors.append(exc.message)
                continue

            raw_node_id = front_matter.get("id")
            if raw_node_id is None:
                node_id = path.stem
                index.warnings.append(
                    f"{kind.title()} file {self._safe_relative(path, folder)} is missing front matter id; using filename stem as legacy id."
                )
            elif isinstance(raw_node_id, str) and raw_node_id.strip():
                node_id = raw_node_id.strip()
            else:
                node_id = path.stem
                index.errors.append(
                    f"{kind.title()} file {self._safe_relative(path, folder)} has invalid front matter id; it must be text."
                )

            raw_entry_type = front_matter.get("entry_type") or default_entry_type
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else default_entry_type
            raw_title = front_matter.get("title")
            title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else node_id
            entry = NodeIndexEntry(
                id=node_id,
                kind=kind,
                entry_type=entry_type,
                path=path,
                title=title,
                source_layer_id=layer_id,
                source_layer_label=layer_label,
            )
            index.id_by_path[path.resolve()] = node_id
            existing = index.by_id.get(node_id)
            if existing is not None:
                if existing.source_layer_id == layer_id:
                    # Duplicate within the same layer — stays an error.
                    index.errors.append(
                        f"Duplicate front matter id {node_id} in "
                        f"{self._safe_relative(existing.path, duplicate_relative_to)} and "
                        f"{self._safe_relative(path, duplicate_relative_to)}."
                    )
                    continue
                # Cross-layer collision: descendant wins, but flag it for visibility.
                index.warnings.append(
                    f"Entry id {node_id} in {layer_label} shadows the entry from "
                    f"{existing.source_layer_label}."
                )
            index.by_id[node_id] = entry

    def _safe_relative(self, path: Path, anchor: Path) -> Path | str:
        try:
            return path.relative_to(anchor)
        except ValueError:
            return path

    def _node_id_for_path(self, path: Path, front_matter: dict[str, Any] | None = None) -> str:
        if front_matter is None:
            front_matter = self._read_front_matter_only(path, strict=True)
        raw_node_id = front_matter.get("id")
        if isinstance(raw_node_id, str) and raw_node_id.strip():
            return raw_node_id.strip()
        return path.stem

    def _path_for_node_id(self, node_id: str, kind: str) -> Path:
        root = self._require_project()
        index = self._build_node_index(root)
        entry = index.by_id.get(node_id)
        if entry and entry.kind == kind:
            return entry.path
        folder_by_kind = {
            "scene": "scenes",
            "lore": "lore",
            "prompt": "prompts",
            "research": "research/notes",
            "mutation_set": "mutation-sets",
            "view": "views",
        }
        label_by_kind = {
            "scene": "Scene",
            "lore": "Lore Entry",
            "prompt": "Prompt",
            "research": "Research Note",
            "mutation_set": "Mutation set",
            "view": "View",
        }
        fallback_folder = folder_by_kind.get(kind, "lore")
        fallback_path = root / fallback_folder / f"{node_id}.md"
        if fallback_path.exists():
            return fallback_path
        raise ProjectServiceError(f"{label_by_kind.get(kind, 'Entry')} {node_id} does not exist.", 404)

    def _read_body_summary(self, path: Path, *, max_chars: int = 160) -> str:
        try:
            with path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
                if first_line.strip() == "---":
                    for line in handle:
                        if line.strip() == "---":
                            break
                for line in handle:
                    text = line.strip()
                    if not text or text.startswith("#"):
                        continue
                    if len(text) > max_chars:
                        return text[: max_chars - 1].rstrip() + "…"
                    return text
        except OSError:
            return ""
        return ""

    def _entry_type_matches(self, entry_type_id: str, target_entry_type: str, schema: MetadataSchema) -> bool:
        if entry_type_id == target_entry_type:
            return True
        seen: set[str] = set()
        current = schema.entry_types.get(entry_type_id)
        while current and current.parent and current.parent not in seen:
            if current.parent == target_entry_type:
                return True
            seen.add(current.parent)
            current = schema.entry_types.get(current.parent)
        return False

    def _candidate_from_index_entry(self, entry: NodeIndexEntry, *, include_summary: bool) -> ReferenceCandidate:
        return ReferenceCandidate(
            id=entry.id,
            title=entry.title or entry.id,
            kind=entry.kind,
            entry_type=entry.entry_type,
            summary=self._read_body_summary(entry.path) if include_summary else "",
            found=True,
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )

    def resolve_references(self, ids: list[str]) -> ReferenceResolveResponse:
        index = self._build_node_index()
        candidates: list[ReferenceCandidate] = []
        for node_id in ids:
            entry = index.by_id.get(node_id)
            if entry is None:
                candidates.append(
                    ReferenceCandidate(id=node_id, title=node_id, kind="", entry_type="", summary="", found=False)
                )
                continue
            candidates.append(self._candidate_from_index_entry(entry, include_summary=True))
        return ReferenceResolveResponse(candidates=candidates)

    def list_backlinks(self, target_id: str) -> BacklinksResponse:
        node_index = self._build_node_index()
        if target_id not in node_index.by_id:
            return BacklinksResponse(target_id=target_id, backlinks=[])
        schema = self.read_metadata_schema()
        backlinks: list[Backlink] = []
        for entry in node_index.by_id.values():
            if entry.id == target_id:
                continue
            entry_definition = schema.entry_types.get(entry.entry_type)
            if entry_definition is None:
                continue
            try:
                front_matter = self._read_front_matter_only(entry.path, strict=True)
            except ProjectServiceError:
                continue
            metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
            for field_id in entry_definition.fields:
                field = schema.fields.get(field_id)
                if field is None:
                    continue
                value = metadata.get(field_id)
                matched = False
                if field.type == "entity_ref" and isinstance(value, str) and value == target_id or field.type == "entity_ref_list" and isinstance(value, list) and target_id in value:
                    matched = True
                if matched:
                    backlinks.append(
                        Backlink(
                            id=entry.id,
                            title=entry.title or entry.id,
                            kind=entry.kind,
                            entry_type=entry.entry_type,
                            field_id=field_id,
                            field_name=field.name,
                        )
                    )
        backlinks.sort(key=lambda link: (link.kind, link.title.lower(), link.field_id))
        return BacklinksResponse(target_id=target_id, backlinks=backlinks)

    def list_reference_candidates(
        self,
        *,
        kind: str | None = None,
        entry_type: str | None = None,
        exclude_id: str | None = None,
    ) -> ReferenceCandidatesResponse:
        index = self._build_node_index()
        schema = self.read_metadata_schema() if entry_type else None
        candidates: list[ReferenceCandidate] = []
        for entry in index.by_id.values():
            if exclude_id and entry.id == exclude_id:
                continue
            if kind and entry.kind != kind:
                continue
            if entry_type and schema is not None and not self._entry_type_matches(entry.entry_type, entry_type, schema):
                continue
            candidates.append(self._candidate_from_index_entry(entry, include_summary=False))
        candidates.sort(key=lambda candidate: (candidate.entry_type, candidate.title.lower(), candidate.id))
        return ReferenceCandidatesResponse(candidates=candidates)
