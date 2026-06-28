"""Research slice of ProjectService (#14 backend split).

The research tree mirrors the manuscript structure CRUD via
`TreeStructureService`, but its only leaf type is `note` (entry_type), backed
by a markdown file under `research/notes/`; containers are `topic`. This mixin
owns the research tree CRUD, the note leaf IO, and the lore_note→research
migration. `ProjectService` composes it.

Method bodies moved verbatim from project_service.py — the shared helpers they
call (`self._require_project`, `self.read_metadata_schema`,
`self._initial_metadata_from_defaults`, `self._new_id`,
`self._filepath_for_new_node`, `self._path_for_node_id`,
`self._read_markdown_with_front_matter`, `self._write_markdown_with_front_matter`,
`self._maybe_rename_node_file`, `self._backlinks_to_targets`,
`self._purge_references_to`, `self._build_node_index`, `self._node_id_for_path`,
`self._normalise_metadata`, `self._strip_unknown_metadata_fields`,
`self._strip_dangling_references`, `self._revision`, `self._atomic_write`) plus
the lore helpers from `LoreEntriesMixin` (`self.read_lore_entry`,
`self.delete_lore_entry`, `self.list_lore_entries`) still live elsewhere on the
composed class and resolve through the MRO at call time.

`_manuscript_tree` stays in core — it's used by the manuscript structure CRUD,
not research. Computed-metadata injection isn't applied here: research's v1
schema has no counters/status fields that need it (docs/research-strategy.md
slice 1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.models import (
    CreateStructureNodeRequest,
    MoveLoreNoteToResearchResponse,
    ResearchNote,
    SaveResearchNoteRequest,
    StructureDocument,
    StructureNode,
    StructureNodeDeletePreview,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.tree_configs import RESEARCH_TREE_CONFIG
from app.services.tree_structure import TreeStructureService


class ResearchNotesMixin:
    def _research_tree(self) -> TreeStructureService:
        return TreeStructureService(self._require_project(), RESEARCH_TREE_CONFIG)

    def read_research_structure(self) -> StructureDocument:
        return self._research_tree().read()

    def create_research_node(self, request: CreateStructureNodeRequest) -> StructureDocument:
        self._require_project()
        schema = self.read_metadata_schema()
        entry_type = schema.entry_types.get(request.entry_type)
        if entry_type is None:
            raise ProjectServiceError(f"Unknown entry type {request.entry_type}.", 404)
        if entry_type.kind != "research":
            raise ProjectServiceError(
                f"Entry type {request.entry_type} is not a research type.", 422
            )
        if entry_type.abstract:
            raise ProjectServiceError(
                f"Entry type {request.entry_type} is abstract and cannot be instantiated.", 422
            )

        tree = self._research_tree()
        document = tree.read()

        parent: StructureNode | None
        if request.parent_id:
            parent = TreeStructureService.find_node(document, request.parent_id)
            if parent is None:
                raise ProjectServiceError(
                    f"Parent node {request.parent_id} does not exist.", 404
                )
            if parent.type == "note":
                raise ProjectServiceError(
                    "Cannot add a child under a research note.", 422
                )
        else:
            parent = document.root

        note_id: str | None = None
        if entry_type.has_body:
            note_id = self._new_id("note")
            initial_metadata = self._initial_metadata_from_defaults(request.entry_type, schema)
            note = ResearchNote(
                id=note_id,
                title=request.title,
                body="",
                entry_type=request.entry_type,
                metadata=initial_metadata,
            )
            self._write_research_note_file(
                self._filepath_for_new_node(tree.leaf_dir, request.title),
                note,
            )

        new_node = StructureNode(
            id=self._new_id("node"),
            type=request.entry_type,
            title=request.title,
            scene_id=note_id,  # model field; TreeStructureService maps it to note_id on disk
        )
        TreeStructureService.insert_node(parent, new_node)
        tree.write(document)
        return tree.read()

    def rename_research_node(self, node_id: str, title: str) -> StructureDocument:
        clean_title = title.strip()
        if not clean_title:
            raise ProjectServiceError("Title cannot be empty.", 422)
        tree = self._research_tree()
        document = tree.read()
        node = TreeStructureService.find_node(document, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot rename the root node.", 422)
        node.title = clean_title
        if node.scene_id:
            path = self._path_for_node_id(node.scene_id, "research")
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            front_matter["title"] = clean_title
            self._write_markdown_with_front_matter(path, front_matter, body)
            self._maybe_rename_node_file(path, clean_title)
        tree.write(document)
        return tree.read()

    def move_research_node(
        self, node_id: str, target_parent_id: str, position: int
    ) -> StructureDocument:
        tree = self._research_tree()
        document = tree.read()
        node = TreeStructureService.find_node(document, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot move the root node.", 422)
        target_parent = TreeStructureService.find_node(document, target_parent_id)
        if target_parent is None:
            raise ProjectServiceError(
                f"Target parent {target_parent_id} does not exist.", 404
            )
        if target_parent.type == "note":
            raise ProjectServiceError("Cannot move a node under a research note.", 422)
        if TreeStructureService.contains_node(node, target_parent_id):
            raise ProjectServiceError(
                "Cannot move a node into itself or its descendants.", 422
            )
        removed = TreeStructureService.extract_node(document, node_id)
        if removed is None:
            raise ProjectServiceError(
                f"Could not detach {node_id} from its current parent.", 500
            )
        target_parent = TreeStructureService.find_node(document, target_parent_id)
        if target_parent is None:
            raise ProjectServiceError("Target parent disappeared after detach.", 500)
        insert_at = max(0, min(position, len(target_parent.children)))
        target_parent.children.insert(insert_at, removed)
        tree.write(document)
        return tree.read()

    def cascade_research_delete_preview(
        self, node_id: str
    ) -> StructureNodeDeletePreview:
        document = self._research_tree().read()
        node = TreeStructureService.find_node(document, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot delete the root node.", 422)

        descendant_leaf_count = 0
        descendant_container_count = 0

        def walk(n: StructureNode, is_target: bool) -> None:
            nonlocal descendant_leaf_count, descendant_container_count
            if not is_target:
                if n.type == "note":
                    descendant_leaf_count += 1
                else:
                    descendant_container_count += 1
            for child in n.children:
                walk(child, is_target=False)

        walk(node, is_target=True)
        doomed_leaf_ids = TreeStructureService.collect_leaf_ids(node)
        backlinks = self._backlinks_to_targets(
            doomed_leaf_ids, exclude_source_ids=doomed_leaf_ids
        )
        return StructureNodeDeletePreview(
            target_id=node.id,
            target_title=node.title,
            target_type=node.type,
            descendant_scene_count=descendant_leaf_count,
            descendant_container_count=descendant_container_count,
            backlinks=backlinks,
        )

    def delete_research_node(self, node_id: str) -> StructureDocument:
        tree = self._research_tree()
        document = tree.read()
        node = TreeStructureService.find_node(document, node_id)
        if node is None:
            raise ProjectServiceError(f"Structure node {node_id} does not exist.", 404)
        if node.type == "root":
            raise ProjectServiceError("Cannot delete the root node.", 422)

        note_ids = TreeStructureService.collect_leaf_ids(node)
        # Outbound references can point at either the structure-node id
        # or the underlying leaf file id, so purge both.
        purge_ids = TreeStructureService.collect_descendant_ids(
            node
        ) | TreeStructureService.collect_leaf_ids(node)
        for note_id in note_ids:
            try:
                path = self._path_for_node_id(note_id, "research")
                if path.exists():
                    path.unlink()
            except ProjectServiceError:
                pass

        TreeStructureService.remove_node_by_id(document.root, node_id)
        tree.write(document)
        self._purge_references_to(purge_ids)
        return tree.read()

    # ----- Research note leaf IO -----

    def _write_research_note_file(self, path: Path, note: ResearchNote) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": note.id,
                "title": note.title,
                "entry_type": note.entry_type,
                "metadata": note.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = note.body.rstrip() + "\n" if note.body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

    def read_research_note(self, note_id: str) -> ResearchNote:
        index = self._build_node_index()
        index_entry = index.by_id.get(note_id)
        if index_entry is not None and index_entry.kind == "research":
            path = index_entry.path
        else:
            path = self._path_for_node_id(note_id, "research")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        title = str(front_matter.get("title") or node_id)
        raw_entry_type = front_matter.get("entry_type") or "note"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(
                f"Research note {node_id} has invalid entry_type; it must be text.", 422
            )
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        schema = self.read_metadata_schema()
        metadata = self._strip_unknown_metadata_fields(metadata, entry_type, schema)
        metadata = self._strip_dangling_references(metadata, schema, index)
        return ResearchNote(
            id=node_id,
            title=title,
            body=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
        )

    def save_research_note(
        self, note_id: str, request: SaveResearchNoteRequest
    ) -> ResearchNote:
        path = self._path_for_node_id(note_id, "research")
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        current_revision = self._revision(path)
        if request.base_revision is not None and request.base_revision != current_revision:
            raise ProjectServiceError(
                "The note was modified by someone else. Reload and retry.", 409
            )
        node_id = self._node_id_for_path(path, front_matter)
        schema = self.read_metadata_schema()
        entry_type = request.entry_type or "note"
        if entry_type not in schema.entry_types:
            raise ProjectServiceError(f"Unknown entry type {entry_type}.", 404)
        clean_metadata = self._strip_unknown_metadata_fields(
            request.metadata, entry_type, schema
        )
        note = ResearchNote(
            id=node_id,
            title=request.title,
            body=request.body,
            entry_type=entry_type,
            metadata=clean_metadata,
        )
        self._write_research_note_file(path, note)
        renamed_path = self._maybe_rename_node_file(path, request.title) or path
        # Keep the research tree title in sync the same way save_scene
        # does for manuscript.
        self._update_research_title_in_structure(node_id, request.title)
        return ResearchNote(
            id=node_id,
            title=request.title,
            body=request.body,
            revision=self._revision(renamed_path),
            entry_type=entry_type,
            metadata=clean_metadata,
        )

    def move_lore_note_to_research(self, lore_id: str) -> MoveLoreNoteToResearchResponse:
        """Convert a `lore_note` entry into a research/note (slice 5 of
        docs/research-strategy.md).

        Copies the title + body + tags into a new research note appended
        at the research tree root, then deletes the source lore_note.
        Other lore_note metadata fields (`aliases`, `related_entries`,
        `context_policy`) are intentionally dropped — the v1 research/note
        schema is title + body + tags only. The dropped fields are
        returned in the response so the UI can surface them; nothing
        about the migration is silent.
        """
        index = self._build_node_index()
        index_entry = index.by_id.get(lore_id)
        if index_entry is None or index_entry.kind != "lore":
            raise ProjectServiceError(f"Lore entry {lore_id} does not exist.", 404)
        source = self.read_lore_entry(lore_id)
        if source.entry_type != "lore_note":
            raise ProjectServiceError(
                f"Only lore_note entries can be moved to research; got {source.entry_type}.",
                422,
            )
        preserved_metadata: dict[str, Any] = {}
        dropped_fields: list[str] = []
        for field_id, value in source.metadata.items():
            if field_id == "tags":
                preserved_metadata[field_id] = value
            else:
                if value not in (None, "", [], {}):
                    dropped_fields.append(field_id)

        tree = self._research_tree()
        document = tree.read()
        note_id = self._new_id("note")
        note = ResearchNote(
            id=note_id,
            title=source.title,
            body=source.body,
            entry_type="note",
            metadata=preserved_metadata,
        )
        self._write_research_note_file(
            self._filepath_for_new_node(tree.leaf_dir, source.title), note
        )
        new_tree_node = StructureNode(
            id=self._new_id("node"),
            type="note",
            title=source.title,
            scene_id=note_id,
        )
        TreeStructureService.insert_node(document.root, new_tree_node)
        tree.write(document)

        # Delete the source lore_note last so a write failure above leaves
        # the original intact. _purge_references_to clears outbound refs
        # pointed at the now-gone id; downstream links break — same
        # behavior as a manual delete.
        self.delete_lore_entry(lore_id)

        return MoveLoreNoteToResearchResponse(
            note_id=note_id,
            tree=tree.read(),
            dropped_fields=sorted(dropped_fields),
            lore=self.list_lore_entries(),
        )

    def _update_research_title_in_structure(self, note_id: str, title: str) -> None:
        tree = self._research_tree()
        document = tree.read()
        node = TreeStructureService.find_by_leaf_ref(document, note_id)
        if node is not None:
            node.title = title
            tree.write(document)
