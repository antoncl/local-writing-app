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
`self._rewrite_references_from_to`, `self._metadata_schema_layer_id`,
`self._layer_folder_for_id`, `self._machine_write_schema`,
`self._build_assistant_index`) live elsewhere on the composed class and
resolve through the MRO at call time — the same contract `assistants.py`
documents, since this mixin models every method on that path (plus
`views.py` for the body-less-node shape).

Merge (ADR-0082 §5) lives here too: it is a redirect (`metadata.merged_into`),
not a rewrite of every carrier — see `merge_tag_entries`. The legacy
`TagsMixin.merge_tags`/`_reject_sources_above_this_layer` (`tags.py`, retired
by slice 3) are the precedent for the "source must be owned by this layer"
bound and its message style.
"""

from __future__ import annotations

from app.models import (
    CreateTagEntryRequest,
    MetadataSchema,
    SaveTagEntryRequest,
    TagEntry,
    TagEntryList,
)
from app.services import machine_settings as ms_service
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndex, NodeIndexEntry


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
        metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
        merged_into = metadata.get("merged_into")
        return TagEntry(
            id=entry.id,
            title=entry.title,
            entry_type=entry.entry_type,
            metadata=metadata,
            revision=self._revision(entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
            merged_into=merged_into if isinstance(merged_into, str) and merged_into else None,
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
        index = self._build_assistant_index()
        index_entry = index.by_id.get(tag_id)
        if index_entry is None or index_entry.kind != "tag":
            raise ProjectServiceError(f"Tag {tag_id} does not exist.", 404)
        # A redirect (a tag with `merged_into` set) has no survivor to leave
        # behind, so cascade-deleting it is meaningless — but deleting a
        # SURVIVOR takes every tag that redirects to it with it (ADR-0082 §5):
        # `_purge_references_to` would otherwise scrub their `merged_into`
        # values and resurrect them into pickers. Collected transitively
        # (a redirect may itself be redirected to) — the chat-subject cascade
        # (`_chats_with_subject_in`) is the precedent for "a deleted survivor
        # takes its dependents with it".
        redirect_ids = self._transitive_redirects(tag_id, index)
        for redirect_id in redirect_ids:
            self._delete_node_file(index.by_id[redirect_id].path)
        self._delete_node_file(index_entry.path)  # unlink + un-shadow the memo (#392)
        # Only with a project open: no-project tag deletes are machine-layer
        # vocabulary entries (e.g. an assistant tag), and references live in
        # the open project's own node files, same guard `delete_lore_entry`
        # applies before its purge (`lore.py`).
        if self.root_path is not None:
            self._purge_references_to({tag_id, *redirect_ids}, self.root_path)
        return None

    def _transitive_redirects(self, tag_id: str, index: NodeIndex) -> set[str]:
        """Every OTHER tag id that redirects to `tag_id`, directly or through
        another redirect (ADR-0082 §5) — `index.redirects_to` is one hop, so
        this walks it to a fixed point.

        `tag_id` itself is NEVER in the result, even when a hand-edited cycle's
        edges loop back to it (a caller deleting `tag_id`'s redirects must not
        be handed `tag_id` back — that is the file the caller's own separate
        `_delete_node_file` unlinks, and unlinking it twice raises). `visited`
        seeds with `tag_id` so the walk can never re-add it, which is also
        what makes this cycle-safe (bounded by set membership either way)."""
        visited = {tag_id}
        frontier = [tag_id]
        while frontier:
            current = frontier.pop()
            for redirect_id in index.redirects_to.get(current, []):
                if redirect_id not in visited:
                    visited.add(redirect_id)
                    frontier.append(redirect_id)
        visited.discard(tag_id)
        return visited

    def merge_tag_entries(self, source_id: str, target_id: str) -> TagEntry:
        """Merge `source_id` into `target_id`: record a `merged_into` redirect
        on the source (ADR-0082 §5), not a rewrite of every carrier. Every
        rule below is a 422 — this is a governance action on data the author
        is looking at, not a lookup that can 404.

        1. Write `metadata.merged_into = target` on the source's own file
           FIRST — the redirect is what makes the merge correct at all
           (`canonical_id` resolves every read through it the moment the
           index next builds), so it must land before anything that can fail.
        2. Rewrite references to the source, in the owned scope, to the
           target (`_rewrite_references_from_to`, the same sweep
           `_purge_references_to` uses) — an eager convenience, not a
           correctness requirement. If this raises, the redirect from step 1
           already stands and the error propagates: the merge is not rolled
           back, and a carrier that still names the source keeps reading as
           the target via `canonical_id` regardless (S3) until a rerun of the
           sweep (idempotent — nothing left naming the source, nothing to
           rewrite) or the carrier's own next save (S4) catches it up.
        3. Index maintenance happens through the write funnel as usual — the
           next index build reads the redirect and resolves it everywhere
           (`NodeIndex.canonical_id`).
        """
        if source_id == target_id:
            raise ProjectServiceError("A tag cannot be merged into itself.", 422)
        index = self._build_assistant_index()
        source_entry = index.by_id.get(source_id)
        if source_entry is None or source_entry.kind != "tag":
            raise ProjectServiceError(f"Tag {source_id} does not exist.", 422)
        target_entry = index.by_id.get(target_id)
        if target_entry is None or target_entry.kind != "tag":
            raise ProjectServiceError(f"Tag {target_id} does not exist.", 422)
        # The target may itself be a redirect — merge into its survivor rather
        # than reject, so a chain never has to be resolved by hand first.
        canonical_target_id = index.canonical_id(target_id)
        if canonical_target_id != target_id:
            target_id = canonical_target_id
            target_entry = index.by_id[target_id]
        if source_id == target_id:
            raise ProjectServiceError(
                f"{source_entry.title} is already merged into {target_entry.title}.", 422
            )
        if source_entry.entry_type != target_entry.entry_type:
            raise ProjectServiceError(
                f"{source_entry.title} and {target_entry.title} are different tag "
                "vocabularies and cannot be merged.",
                422,
            )
        machine_dir = ms_service.assistants_dir().parent
        owning_folder = self.root_path if self.root_path is not None else machine_dir
        owned_layer_id = self._metadata_schema_layer_id(owning_folder)
        if source_entry.source_layer_id != owned_layer_id:
            raise ProjectServiceError(
                f"{source_entry.title} is defined in a parent folder and cannot be merged from here.",
                422,
            )

        source_metadata = self._normalise_metadata(
            self._read_front_matter_only(source_entry.path, strict=True).get("metadata"),
            source_entry.path,
        )
        source_metadata["merged_into"] = target_id
        self._write_node_entry_file(
            source_entry.path,
            source_entry.id,
            source_entry.title,
            source_entry.entry_type,
            source_metadata,
            "",
        )

        # Eager convenience, run AFTER the redirect above (see the docstring):
        # a carrier this sweep never reaches still reads as the survivor via
        # `canonical_id`, so nothing here is load-bearing for correctness.
        # Machine-only (no project open): skipped by design, not merely
        # unreached — references live in whichever project's node files are
        # open, never the machine layer itself, so there is no owned scope to
        # sweep here. Correctness still holds: `canonical_id` resolves the
        # redirect on every read regardless of which scope opens next.
        if self.root_path is not None:
            self._rewrite_references_from_to(source_id, target_id, self.root_path)

        return self.read_tag_entry(target_id)
