"""Research slice of ProjectService (#14 backend split).

The research tree works exactly like the manuscript's (ADR-0094): its nodes are
files under `research/notes/` — notes (`research:note`, the leaf) and the
containers that hold them — each carrying its own `parent` and `rank`, and the
tree is built from them by `TreeNodesMixin`. This mixin owns the research tree
CRUD, the note file IO, and the lore_note→research move. `ProjectService`
composes it.

The shared helpers these methods call (`self._require_project`,
`self.read_metadata_schema`, `self._initial_metadata_from_defaults`,
`self._new_id`, `self._filepath_for_new_node`, `self._path_for_node_id`,
`self._read_markdown_with_front_matter`, `self._write_markdown_with_front_matter`,
`self._maybe_rename_node_file`, `self._backlinks_to_targets`,
`self._purge_references_to`, `self._build_node_index`, `self._node_id_for_path`,
`self._normalise_metadata`, `self._strip_unknown_metadata_fields`,
`self._revision`, `self._atomic_write`, the tree helpers) plus the lore helpers
(`self.read_lore_entry`, `self.delete_lore_entry`, `self.list_lore_entries`)
live elsewhere on the composed class and resolve through the MRO at call time.
Computed-metadata injection isn't applied here: research's schema has no
counters/status fields that need it (docs/research-strategy.md slice 1).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import yaml

from app.models import (
    CreateStructureNodeRequest,
    MoveLoreNoteToResearchResponse,
    ResearchNote,
    SaveResearchNoteRequest,
    StructureDocument,
    StructureNodeDeletePreview,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.tree_configs import RESEARCH_TREE
from app.services.tree_structure import TreeStructureService


class ResearchNotesMixin:
    def read_research_structure(self) -> StructureDocument:
        return self._read_tree(self._require_project(), RESEARCH_TREE)

    def create_research_node(self, request: CreateStructureNodeRequest) -> StructureDocument:
        root = self._require_project()
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

        document = self._read_tree(root, RESEARCH_TREE)
        parent_id: str | None = None
        if request.parent_id and request.parent_id != "root":
            parent = TreeStructureService.find_node(document, request.parent_id)
            if parent is None:
                raise ProjectServiceError(
                    f"Parent node {request.parent_id} does not exist.", 404
                )
            if parent.type == RESEARCH_TREE.leaf_type:
                raise ProjectServiceError(
                    "Cannot add a child under a research note.", 422
                )
            parent_id = parent.id

        # Every research node is a file now, containers included (ADR-0094 §7):
        # a topic can be opened and carry fields like any node.
        note_id = self._new_id(RESEARCH_TREE.id_prefix)
        initial_metadata = self._initial_metadata_from_defaults(request.entry_type, schema)
        note = ResearchNote(
            id=note_id,
            title=request.title,
            body="",
            entry_type=request.entry_type,
            metadata=initial_metadata,
        )
        self._write_research_note_file(
            self._filepath_for_new_node(root / RESEARCH_TREE.folder, request.title),
            note,
        )
        self._place_node(root, RESEARCH_TREE, note_id, parent_id, None)
        return self._read_tree(root, RESEARCH_TREE)

    def rename_research_node(self, node_id: str, title: str) -> StructureDocument:
        root = self._require_project()
        clean_title = title.strip()
        if not clean_title:
            raise ProjectServiceError("Title cannot be empty.", 422)
        node = self._require_tree_node(self._read_tree(root, RESEARCH_TREE), node_id)
        path = self._path_for_node_id(node.id, "research")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        front_matter["title"] = clean_title
        self._write_markdown_with_front_matter(path, front_matter, body)
        self._maybe_rename_node_file(path, clean_title)
        return self._read_tree(root, RESEARCH_TREE)

    def move_research_node(
        self, node_id: str, target_parent_id: str, position: int
    ) -> StructureDocument:
        return self._move_tree_node(
            self._require_project(), RESEARCH_TREE, node_id, target_parent_id, position
        )

    def cascade_research_delete_preview(
        self, node_id: str
    ) -> StructureNodeDeletePreview:
        document = self._read_tree(self._require_project(), RESEARCH_TREE)
        node = self._require_tree_node(document, node_id)

        descendant_leaf_count = 0
        descendant_container_count = 0
        for n in TreeStructureService.collect(node, skip_root=True):
            if n.type == RESEARCH_TREE.leaf_type:
                descendant_leaf_count += 1
            else:
                descendant_container_count += 1

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
        root = self._require_project()  # see manuscript.delete_structure_node (#381)
        node = self._require_tree_node(self._read_tree(root, RESEARCH_TREE), node_id)

        # Every node in the subtree is a file and its id is its file's id
        # (ADR-0094 §4): one set is both what to delete and what to purge.
        note_ids = TreeStructureService.collect_leaf_ids(node)
        # Collect first, then delete as one batch (#476) so a research subtree of
        # many notes writes a single coalesced snapshot instead of one per note.
        paths: list[Path] = []
        for note_id in note_ids:
            with contextlib.suppress(ProjectServiceError):
                paths.append(self._path_for_node_id(note_id, "research"))
            # A note and its snapshot store are one unit of deletion (ADR-0043):
            # a research note is snapshottable since #1981, so drop its store too
            # or it is the unreachable residue the manuscript delete paths
            # (delete_scene / delete_structure_node) also clear. Outside the
            # suppress so it runs even when the note file can't be resolved.
            self.delete_scene_snapshots(root, note_id)
        self._delete_node_files(tuple(paths))  # unlink all + un-shadow the memo once

        self._purge_references_to(set(note_ids), root)
        return self._read_tree(root, RESEARCH_TREE)

    # ----- Research note leaf IO -----

    def _write_research_note_file(self, path: Path, note: ResearchNote) -> None:
        # Placement is carried over from the file on disk, never taken from the
        # note being saved (ADR-0094 §1): a save does not move a node.
        front_matter = yaml.safe_dump(
            self._with_disk_placement(
                path,
                {
                    "id": note.id,
                    "title": note.title,
                    "entry_type": note.entry_type,
                    "metadata": note.metadata,
                },
            ),
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
        raw_entry_type = front_matter.get("entry_type") or "research:note"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(
                f"Research note {node_id} has invalid entry_type; it must be text.", 422
            )
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        schema = self.read_metadata_schema()
        metadata = self._repair_metadata_on_read(metadata, entry_type, schema, index)
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
        # Not as-of-L (#393): research is organised as a per-project tree and
        # nothing inherits that tree across layers (ADR-0094), so a note is only
        # ever authored at the resolution scope.
        # Inheriting research is arguable in principle — unlike a scene, a note
        # is fairly self-contained — but the tree is the knot: an inherited note
        # has no defined position in the inheriting project's tree, the same
        # obstacle an inherited scene hits in the manuscript. **Not planned, and
        # not a deferred TODO.** As-of-L is for inherited nodes (lore).
        schema = self.read_metadata_schema()
        entry_type = request.entry_type or "research:note"
        if entry_type not in schema.entry_types:
            raise ProjectServiceError(f"Unknown entry type {entry_type}.", 404)
        clean_metadata = self._strip_unknown_metadata_fields(
            request.metadata, entry_type, schema
        )
        clean_metadata = self._canonicalise_metadata_selects(clean_metadata, entry_type, schema)
        note = ResearchNote(
            id=node_id,
            title=request.title,
            body=request.body,
            entry_type=entry_type,
            metadata=clean_metadata,
        )
        # Before the write: the session-boundary photo is the pre-save bytes —
        # what this note looked like when the author sat down (ADR-0043 Am. 2).
        self.maybe_capture_session_boundary(node_id, kind="research")
        self._write_research_note_file(path, note)
        renamed_path = self._maybe_rename_node_file(path, request.title) or path
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
        root = self._require_project()
        index = self._build_node_index(root)
        index_entry = index.by_id.get(lore_id)
        if index_entry is None or index_entry.kind != "lore":
            raise ProjectServiceError(f"Lore entry {lore_id} does not exist.", 404)
        source = self.read_lore_entry(lore_id)
        if source.entry_type != "lore:note":
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

        note_id = self._new_id(RESEARCH_TREE.id_prefix)
        note = ResearchNote(
            id=note_id,
            title=source.title,
            body=source.body,
            entry_type="research:note",
            metadata=preserved_metadata,
        )
        self._write_research_note_file(
            self._filepath_for_new_node(root / RESEARCH_TREE.folder, source.title), note
        )
        self._place_node(root, RESEARCH_TREE, note_id, None, None)

        # Delete the source lore_note last so a write failure above leaves
        # the original intact. _purge_references_to clears outbound refs
        # pointed at the now-gone id; downstream links break — same
        # behavior as a manual delete.
        self.delete_lore_entry(lore_id)

        return MoveLoreNoteToResearchResponse(
            note_id=note_id,
            tree=self._read_tree(root, RESEARCH_TREE),
            dropped_fields=sorted(dropped_fields),
            lore=self.list_lore_entries(),
        )
