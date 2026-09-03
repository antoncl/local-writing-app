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
`self._delete_node_file`, `self._purge_references_to`,
`self._layer_folder_for_id`, `self._machine_write_schema`,
`self._build_assistant_index`) live elsewhere on the composed class and
resolve through the MRO at call time — the same contract `assistants.py`
documents, since this mixin models every method on that path (plus
`views.py` for the body-less-node shape).

This slice registers the kind on the read + create path only: `create_missing`
picker wiring, the assistant field rename, `tagged:` changes, merge
(`merged_into`) and the `tags` field-type retirement are later ADR-0082
slices — do not add them here.
"""

from __future__ import annotations

from app.models import (
    CreateTagEntryRequest,
    MetadataSchema,
    SaveTagEntryRequest,
    TagEntry,
    TagEntryList,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndexEntry


class TagNodesMixin:
    def _tag_write_schema(self) -> MetadataSchema:
        """The schema a tag create/save validates against. Delegates to
        `LayerWalkMixin._machine_write_schema()` (`layers.py`) — was
        identical to `AssistantEntriesMixin._assistant_write_schema` before
        ADR-0082 slice 1's review factored the shared body out from under
        both."""
        return self._machine_write_schema()

    def _tag_index_entry(self, tag_id: str) -> NodeIndexEntry:
        """The one lookup + `kind == "tag"` + 404 guard read/save/delete all
        need. `_build_assistant_index` (byte-identical to the old, now-deleted
        `_build_tag_index`) covers both machine families — assistants and
        tags — so this filters to the one this mixin owns."""
        index_entry = self._build_assistant_index().by_id.get(tag_id)
        if index_entry is None or index_entry.kind != "tag":
            raise ProjectServiceError(f"Tag {tag_id} does not exist.", 404)
        return index_entry

    def _tag_from_index_entry(self, entry: NodeIndexEntry) -> TagEntry:
        """Build a `TagEntry` from an already-resolved index entry. `title`
        and `entry_type` come off the INDEX ENTRY — parsed from the same
        front matter the index build already read (`references.py` ~980) —
        rather than a second full front-matter read; only `metadata` needs
        its own (cheaper, body-less) read via `_read_front_matter_only`."""
        front_matter = self._read_front_matter_only(entry.path, strict=True)
        return TagEntry(
            id=entry.id,
            title=entry.title,
            entry_type=entry.entry_type,
            metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
            revision=self._revision(entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )

    def list_tag_entries(self) -> TagEntryList:
        index = self._build_assistant_index()
        entries: list[TagEntry] = []
        for entry in index.by_id.values():
            if entry.kind != "tag":
                continue
            try:
                entries.append(self._tag_from_index_entry(entry))
            except ProjectServiceError:
                # One hand-broken tags/*.md must not 422 the whole roster —
                # `list_assistant_entries` applies the same guard on its own
                # read. This list is now on the boot path (`loadMachineSettings`
                # awaits `refreshTagNodes` with no project open), so a single
                # malformed machine-layer file must not take the roster down.
                continue
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return TagEntryList(tags=entries)

    def read_tag_entry(self, tag_id: str) -> TagEntry:
        return self._tag_from_index_entry(self._tag_index_entry(tag_id))

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
        index_entry = self._tag_index_entry(tag_id)
        path = index_entry.path
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Tag changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "tag", schema=self._tag_write_schema())
        metadata = self._normalise_metadata(request.metadata, path)
        self._write_node_entry_file(path, index_entry.id, request.title, request.entry_type, metadata, "")
        self._maybe_rename_node_file(path, request.title)
        return self.read_tag_entry(index_entry.id)

    def delete_tag_entry(self, tag_id: str) -> None:
        index_entry = self._tag_index_entry(tag_id)
        self._delete_node_file(index_entry.path)  # unlink + un-shadow the memo (#392)
        # Only with a project open: no-project tag deletes are machine-layer
        # vocabulary entries (e.g. an assistant tag), and references live in
        # the open project's own node files, same guard `delete_lore_entry`
        # applies before its purge (`lore.py`).
        if self.root_path is not None:
            self._purge_references_to({tag_id}, self.root_path)
        return None
