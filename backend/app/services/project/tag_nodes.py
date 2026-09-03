"""Tag-node slice of ProjectService (ADR-0082 slice 1, #1782).

A tag is a body-less node of kind `tag`: a vocabulary is a concrete entry
type (`tag:tag`, `tag:assistant_tag`, or a user-authored one), and a tag is
an entry of it. Storage mirrors the `view`/`assistant` node families —
layered Node markdown files under `<layer>/tags/`, with the machine layer
contributing its own tag entries too, beside its assistants
(`MACHINE_LAYER_FAMILIES`, `references.py`). This mixin owns tag CRUD;
`ProjectService` composes it. Shared IO/index helpers it calls
(`self._write_node_entry_file`, `self._filepath_for_new_node`,
`self._new_id`, `self._check_entry_type_kind`, `self._maybe_rename_node_file`,
`self._delete_node_file`, `self._layer_folder_for_id`,
`self._collect_machine_layer_assistants`) live elsewhere on the composed
class and resolve through the MRO at call time — the same contract
`assistants.py` documents, since this mixin models every method on that
path (plus `views.py` for the body-less-node shape).

This slice registers the kind on the read + create path only: `create_missing`
picker wiring, the assistant field rename, `tagged:` changes, merge
(`merged_into`) and the `tags` field-type retirement are later ADR-0082
slices — do not add them here.
"""

from __future__ import annotations

from pathlib import Path

from app.models import (
    CreateTagEntryRequest,
    MetadataSchema,
    SaveTagEntryRequest,
    TagEntry,
    TagEntryList,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndex

DEFAULT_TAG_ENTRY_TYPE = "tag:tag"


class TagNodesMixin:
    def _tag_write_schema(self) -> MetadataSchema:
        """The schema a tag create/save validates against. Mirrors
        `AssistantEntriesMixin._assistant_write_schema`: a tag can be created
        with no project open (the machine assistant-tag vocabulary), so fall
        back to the built-in machine-layer schema rather than
        `_require_project()`-ing a 409."""
        return self.read_metadata_schema() if self.root_path is not None else self.builtin_metadata_schema()

    def _build_tag_index(self) -> NodeIndex:
        """Build a node index covering just the tag kind. Works without an
        open project (machine layer only — the assistant-tag vocabulary) or
        with one (the full layered walk: project tags plus the machine
        layer). Mirrors `AssistantEntriesMixin._build_assistant_index`,
        reusing the same machine-layer collector — `_families_for_layer`
        (`references.py`) now yields the tag family for the machine layer
        too, so no new collector is needed."""
        if self.root_path is not None:
            return self._build_node_index(self.root_path)
        index = NodeIndex()
        self._collect_machine_layer_assistants(index, duplicate_relative_to=Path("/"))
        index.resolve()
        return index

    def list_tag_entries(self) -> TagEntryList:
        index = self._build_tag_index()
        entries: list[TagEntry] = []
        for entry in index.by_id.values():
            if entry.kind != "tag":
                continue
            try:
                front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            entries.append(
                TagEntry(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=str(front_matter.get("entry_type") or DEFAULT_TAG_ENTRY_TYPE),
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return TagEntryList(tags=entries)

    def read_tag_entry(self, tag_id: str) -> TagEntry:
        index = self._build_tag_index()
        index_entry = index.by_id.get(tag_id)
        if index_entry is None or index_entry.kind != "tag":
            raise ProjectServiceError(f"Tag {tag_id} does not exist.", 404)
        path = index_entry.path
        front_matter, _body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        return TagEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            entry_type=str(front_matter.get("entry_type") or DEFAULT_TAG_ENTRY_TYPE),
            metadata=self._normalise_metadata(front_matter.get("metadata"), path),
            revision=self._revision(path),
            source_layer_id=index_entry.source_layer_id,
            source_layer_label=index_entry.source_layer_label,
        )

    def create_tag_entry(self, request: CreateTagEntryRequest) -> TagEntry:
        folder = self._layer_folder_for_id(request.layer_id, "tags")
        self._check_entry_type_kind(request.entry_type, "tag", schema=self._tag_write_schema())
        tag_id = self._new_id("tag")
        folder.mkdir(parents=True, exist_ok=True)
        path = self._filepath_for_new_node(folder, request.title)
        self._write_node_entry_file(
            path,
            tag_id,
            request.title,
            request.entry_type,
            {"color": request.color} if request.color else {},
            "",
        )
        return self.read_tag_entry(tag_id)

    def save_tag_entry(self, tag_id: str, request: SaveTagEntryRequest) -> TagEntry:
        index_entry = self._build_tag_index().by_id.get(tag_id)
        if index_entry is None or index_entry.kind != "tag":
            raise ProjectServiceError(f"Tag {tag_id} does not exist.", 404)
        path = index_entry.path
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Tag changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "tag", schema=self._tag_write_schema())
        metadata = self._normalise_metadata(request.metadata, path)
        self._write_node_entry_file(path, node_id, request.title, request.entry_type, metadata, "")
        self._maybe_rename_node_file(path, request.title)
        return self.read_tag_entry(node_id)

    def delete_tag_entry(self, tag_id: str) -> TagEntryList:
        index_entry = self._build_tag_index().by_id.get(tag_id)
        if index_entry is None or index_entry.kind != "tag":
            raise ProjectServiceError(f"Tag {tag_id} does not exist.", 404)
        self._delete_node_file(index_entry.path)  # unlink + un-shadow the memo (#392)
        return self.list_tag_entries()
