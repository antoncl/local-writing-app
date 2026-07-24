"""Lore-entry slice of ProjectService (#14 backend split).

Lore entries are layered Node markdown files under `<project>/lore/` (plus
any schema layers). This mixin owns their CRUD; `ProjectService` composes
it. Method bodies moved verbatim from project_service.py — the shared
helpers they call (`self._build_node_index`,
`self._read_markdown_with_front_matter`, `self._normalise_metadata`,
`self._require_project`, `self.read_metadata_schema`,
`self._initial_metadata_from_defaults`, `self._validate_lore_entry_metadata`,
`self._new_id`, `self._write_lore_entry_file`, `self._filepath_for_new_node`,
`self._path_for_node_id`, `self._node_id_for_path`, `self._revision`,
`self._strip_unknown_metadata_fields`, `self._strip_dangling_references`,
`self._computed_entry_metadata`, `self._read_front_matter_only`,
`self._canonicalise_metadata_tags`, `self._maybe_rename_node_file`,
`self._purge_references_to`) still live on the core class and resolve
through the MRO at call time.

`_write_lore_entry_file` and `_validate_lore_entry_metadata` stay in core:
the former is also called by `move_lore_note_to_research`, and the latter
is part of the shared metadata-validation subsystem (`validate_project`).
"""

from __future__ import annotations

from app.models import (
    CreateLoreEntryRequest,
    LoreEntry,
    LoreEntryList,
    LoreEntrySummary,
    SaveLoreEntryRequest,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.project.errors import ProjectServiceError
from app.services.project.overrides import LayerOverride


class LoreEntriesMixin:
    def list_lore_entries(self) -> LoreEntryList:
        index = self._build_node_index()
        # Read once for the override fold's field types (#314) — cached (#394),
        # and only consulted when a chain actually carries overrides.
        has_overrides = bool(index.overrides_by_target)
        field_types = self._schema_field_types(self.read_metadata_schema()) if has_overrides else {}
        open_layer_id = self._metadata_schema_layer_id(self._require_project()) if has_overrides else ""
        entries: list[LoreEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "lore":
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "lore:lore_note"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "lore:lore_note"
            metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
            # Fold overrides so a list shows the effective value (#314 / ADR-0039),
            # but only onto an inherited entry — a locally-owned winner (a fork)
            # ignores any leftover override, matching read_lore_entry.
            override_records = index.overrides_by_target.get(entry.id)
            if override_records and entry.source_layer_id != open_layer_id:
                metadata, _ = self.materialize_override_metadata(metadata, override_records, field_types)
            entries.append(
                LoreEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body=body,
                    entry_type=entry_type,
                    metadata=metadata,
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return LoreEntryList(entries=entries)

    def create_lore_entry(self, request: CreateLoreEntryRequest) -> LoreEntry:
        root = self._require_project()
        entry_type = request.entry_type or "lore:lore_note"
        schema = self.read_metadata_schema()
        initial_metadata = self._initial_metadata_from_defaults(entry_type, schema)
        metadata_errors = self._validate_lore_entry_metadata(
            "new",
            entry_type,
            initial_metadata,
            schema,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)

        entry_id = self._new_id("lore")
        entry = LoreEntry(
            id=entry_id,
            title=request.title,
            body="",
            revision="",
            entry_type=entry_type,
            metadata=initial_metadata,
        )
        self._write_lore_entry_file(self._filepath_for_new_node(root / "lore", request.title), entry)
        return self.read_lore_entry(entry_id)

    def read_lore_entry(self, entry_id: str) -> LoreEntry:
        index = self._build_node_index()
        index_entry = index.by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "lore":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "lore")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "lore:lore_note"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Lore Entry {node_id} has invalid entry_type; it must be text.", 422)
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        schema = self.read_metadata_schema()
        # Fold the chain's layer overrides onto this inherited entry's canon
        # (#314 / ADR-0039): the effective value the open project sees, while the
        # ancestor file stays untouched. `overridden_fields` tells the frontend
        # which values carry the `ti-versions` override mark (rendered in PR 2).
        # Overrides apply only to an **inherited** winner — an entry the open
        # project owns locally (a book-local entry, or a fork that severed
        # inheritance) ignores any leftover override, so an edit to a fork is
        # never masked by the delta it copied down.
        overridden_fields: list[str] = []
        override_records = index.overrides_by_target.get(node_id)
        if override_records and index_entry is not None and index_entry.source_layer_id != self._metadata_schema_layer_id(self._require_project()):
            metadata, overridden_fields = self.materialize_override_metadata(
                metadata, override_records, self._schema_field_types(schema)
            )
        # Heal stale fields (retired by a schema change) and dangling
        # references before validation — see _strip_unknown_metadata_fields
        # / _strip_dangling_references for the rationale.
        metadata = self._strip_unknown_metadata_fields(metadata, entry_type, schema)
        metadata = self._strip_dangling_references(metadata, schema, index)
        # A field the fold touched but the strips then removed is no longer a
        # value to mark — keep `overridden_fields` in step with what shipped.
        overridden_fields = [field for field in overridden_fields if field in metadata]
        metadata_errors = self._validate_lore_entry_metadata(node_id, entry_type, metadata, schema, index)
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return LoreEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body=body,
            # A revision that spans the fold (#314): the composite over the owning
            # file plus every override in the chain, so an override edit changes
            # `revision` — optimistic concurrency and the AI prompt cache both see
            # it. With no overrides this reproduces `_revision(path)` exactly.
            revision=self._composite_revision([path, *self._override_paths_for_target(index, node_id)]),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(body, node_id=node_id, entry_type=entry_type, schema=schema),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
            forked_from=self._forked_from_of(front_matter),
            overridden_fields=overridden_fields,
        )

    def save_lore_entry(self, entry_id: str, request: SaveLoreEntryRequest) -> LoreEntry:
        """Save a lore entry, routed by its authoring layer (#314 / ADR-0039/0042).

        A **book-local** entry (or a fork — a fork is a local copy) saves to its
        own file, exactly as before. An **inherited** entry — the index winner is
        an ancestor's — never writes upstream by accident: without an explicit
        write target it fails loudly (the data-loss guard); with one, `L == the
        owning layer` writes the owning file (a deliberate direct edit of canon),
        and `L` below it writes a sparse **override delta** at L. The frontend
        rail picker (PR 2) sends L, defaulting to the open project.
        """
        root = self._require_project()
        index = self._build_node_index()
        winner = index.by_id.get(entry_id)
        open_layer_id = self._metadata_schema_layer_id(root)
        ambient_layer_folder = self._scope_authoring_layer()

        # Owned locally (book-local entry or a fork), or not yet indexed → the
        # ordinary save to the entry's own file. L defaults to the open project.
        # The layer walk is deferred to the inherited / explicit-L paths, so a
        # flat book-local save never pays for it.
        if winner is None or winner.kind != "lore" or winner.source_layer_id == open_layer_id:
            path = winner.path if winner is not None and winner.kind == "lore" else self._path_for_node_id(entry_id, "lore")
            if request.authoring_layer_id:
                explicit = self.layer_by_id(root, request.authoring_layer_id)
                if explicit is None:
                    raise ProjectServiceError("Unknown authoring layer.", 422)
                authoring_folder = explicit.folder
            else:
                authoring_folder = ambient_layer_folder or root
            return self._save_owned_lore_entry(entry_id, request, path, index, authoring_layer=authoring_folder)

        # Inherited: the winner is an ancestor's entry. Resolve the effective
        # authoring layer L — request body first (the ADR-0042 rail picker), else
        # the ambient `WorkScope` (#393/ADR-0045).
        layer_by_id = {layer.id: layer for layer in self.collect_layers(root)}
        explicit_layer = layer_by_id.get(request.authoring_layer_id) if request.authoring_layer_id else None
        if request.authoring_layer_id and explicit_layer is None:
            raise ProjectServiceError("Unknown authoring layer.", 422)

        owning_layer = layer_by_id.get(winner.source_layer_id)
        authoring_layer = explicit_layer or (
            layer_by_id.get(self._metadata_schema_layer_id(ambient_layer_folder.resolve()))
            if ambient_layer_folder is not None
            else None
        )
        if authoring_layer is None:
            raise ProjectServiceError(
                f"This entry is inherited from {winner.source_layer_label or 'an ancestor'}; saving it "
                "needs an explicit write target. Fork it to edit locally, or choose a layer to override "
                "it — a silent save would rewrite ancestor canon for every book downstream.",
                409,
            )
        if owning_layer is None or authoring_layer.rank < owning_layer.rank:
            raise ProjectServiceError("That layer cannot author this entry.", 422)
        if authoring_layer.id == owning_layer.id:
            # An explicit direct edit of ancestor canon: allowed precisely because
            # it was chosen, and it reaches upstream to the owning file.
            return self._save_owned_lore_entry(entry_id, request, winner.path, index, authoring_layer=authoring_layer.folder)
        # L strictly below the owning layer → a sparse override delta at L.
        return self._save_lore_override(entry_id, request, winner, authoring_layer, index)

    def _save_owned_lore_entry(
        self,
        entry_id: str,
        request: SaveLoreEntryRequest,
        path,
        index,
        *,
        authoring_layer,
    ) -> LoreEntry:
        """Write an entry to its own file, validated as of `authoring_layer`."""
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        # The revision spans the fold (#314): stale relative to any override in
        # the chain, not just this file. Reproduces `_revision(path)` when none.
        current_revision = self._composite_revision([path, *self._override_paths_for_target(index, node_id)])
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Lore Entry changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)
        # As of the authoring layer L, not the resolution scope (#393): a write is
        # validated against what its own target layer can store. For a book-local
        # entry L is the open project, so this is the full-chain schema, unchanged.
        schema = self._schema_as_authored(authoring_layer=authoring_layer)
        metadata = self._normalise_metadata(request.metadata, path)
        # NOTE: the tag *vocabulary* stays full-chain here — the schema is as-of-L
        # but `_canonicalise_metadata_tags` still reads all layers and writes its
        # assertion back to the resolution scope's tags.yaml. Scoping it to L means
        # moving the write *target*, not just the read (ADR-0045 §4); left for the
        # PR 2 authoring work with the picker.
        metadata = self._canonicalise_metadata_tags(metadata, schema, kind="lore", entry_type=request.entry_type)
        entry = LoreEntry(
            id=node_id,
            title=request.title,
            body=request.body,
            revision=current_revision,
            entry_type=request.entry_type,
            metadata=metadata,
            # A fork stays severed across edits: preserve `forked_from` so a save
            # never silently re-shadows the ancestor it forked from (#313).
            forked_from=self._forked_from_of(front_matter),
        )
        metadata_errors = self._validate_lore_entry_metadata(node_id, entry.entry_type, entry.metadata, schema, index)
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_lore_entry_file(path, entry)
        self._maybe_rename_node_file(path, request.title)
        return self.read_lore_entry(node_id)

    def _save_lore_override(
        self,
        entry_id: str,
        request: SaveLoreEntryRequest,
        winner,
        authoring_layer,
        index,
    ) -> LoreEntry:
        """Write the consuming layer's sparse override delta on an inherited entry.

        The delta is the diff from the entry's effective value *above* L to the
        metadata the client submitted, validated as of L's schema. Body and title
        overrides are deferred with the rest of ADR-0013's total scope — an
        override captures metadata field changes only in PR 1.
        """
        schema = self._schema_as_authored(authoring_layer=authoring_layer.folder)
        field_types = self._schema_field_types(schema)
        owning_front_matter = self._read_front_matter_only(winner.path, strict=True)
        base_metadata = self._normalise_metadata(owning_front_matter.get("metadata"), winner.path)
        # The base an override at L diffs against is the effective value of every
        # layer *above* L — so the delta captures only what L itself changes, and
        # a later ancestor addition to a multi-valued field still flows down.
        records_above = [
            record for record in index.overrides_by_target.get(entry_id, []) if record.layer_rank < authoring_layer.rank
        ]
        base_above_layer, _ = self.materialize_override_metadata(base_metadata, records_above, field_types)
        # Diff raw-vs-raw: `base_above_layer` comes from the raw owning file, so
        # canonicalising `submitted` first would diff a canonical value against a
        # raw one and mint spurious tag rows (and defeat revert-to-canon). Tag
        # canonicalisation on an override write is deferred with the tag *write
        # target* (#393 / ADR-0045 §4), the same reason it is not scoped to L yet.
        submitted = self._normalise_metadata(request.metadata, winner.path)

        current_revision = self._composite_revision([winner.path, *self._override_paths_for_target(index, entry_id)])
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Lore Entry changed on disk after it was opened.", 409)

        rows = self._diff_metadata_to_override_rows(base_above_layer, submitted, field_types)
        # Validate the entry *as L would resolve it* against L's own roster — a
        # field only the book defines cannot be stored at a series (ADR-0045 §4).
        preview = LayerOverride(entry_id, authoring_layer.id, authoring_layer.rank, authoring_layer.label, winner.path, tuple(rows))
        effective_at_layer, _ = self.materialize_override_metadata(base_above_layer, [preview], field_types)
        metadata_errors = self._validate_lore_entry_metadata(entry_id, request.entry_type, effective_at_layer, schema, index)
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)

        if rows:
            self._write_override_file(authoring_layer.folder, entry_id, request.title, rows)
        else:
            # An empty delta means the author reverted to canon: drop this layer's
            # override rather than leave an inert file (files-are-truth). Routed
            # through `_delete_node_file` so the memo stays coherent — for an
            # override-bearing chain that rebuilds cold (`_mutate_index_for_write`).
            existing = self._override_file_for_target(authoring_layer.folder, entry_id)
            if existing is not None:
                self._delete_node_file(existing)
        return self.read_lore_entry(entry_id)

    @staticmethod
    def _forked_from_of(front_matter: dict) -> str | None:
        """The `forked_from` relative path a lore file records, or None."""
        raw = front_matter.get("forked_from")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None

    def fork_lore_entry(self, entry_id: str) -> LoreEntry:
        """Fork-to-here (#313 / ADR-0039): copy an inherited lore entry down into
        the current project and stop inheriting it from here.

        The copy **keeps the id**, so inbound references from ancestor entries
        resolve to the fork within this project (ADR-0040's candidate stack keeps
        the ancestor reachable as a shadow). Front matter records `forked_from` —
        the path from the base folder to the layer copied from — which both
        declares the severance and silences the shadow warning `resolve()` would
        otherwise emit; an *accidental* same-id collision, carrying no
        `forked_from`, still warns.

        Only lore can be forked: scenes and research notes are book-local, so
        they are never inherited and have nothing to sever.
        """
        root = self._require_project()
        index = self._build_node_index()
        index_entry = index.by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "lore":
            raise ProjectServiceError(f"Lore Entry {entry_id} not found.", 404)
        if index_entry.source_layer_id == self._metadata_schema_layer_id(root):
            raise ProjectServiceError(
                f"Lore Entry {entry_id} already lives in this project; there is nothing to fork.",
                409,
            )
        base = self._metadata_schema_base_folder(root)
        owning_layer = self.layer_by_id(root, index_entry.source_layer_id)
        if base is None or owning_layer is None:
            raise ProjectServiceError(
                f"Cannot resolve the source layer of Lore Entry {entry_id} to fork it.",
                409,
            )
        forked_from = owning_layer.folder.resolve().relative_to(base.resolve()).as_posix()

        # The materialized effective entry is what gets copied down. Pre-#314
        # (no layer overrides yet) that is simply the ancestor's canon.
        resolved = self.read_lore_entry(entry_id)
        entry = LoreEntry(
            id=entry_id,
            title=resolved.title,
            body=resolved.body,
            revision="",
            entry_type=resolved.entry_type,
            metadata=resolved.metadata,
            forked_from=forked_from,
        )
        # The fork writes at the current level (= the resolution scope), so the
        # as-of-L schema is the full-chain schema — no authoring-layer plumbing
        # needed here (that is #314's, for writes *below* the owning layer).
        schema = self._schema_as_authored()
        metadata_errors = self._validate_lore_entry_metadata(
            entry_id, entry.entry_type, entry.metadata, schema, index
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_lore_entry_file(self._filepath_for_new_node(root / "lore", entry.title), entry)
        # The fork copied the effective (already-folded) value down, so this
        # project's own override for the id is now redundant — drop it so it does
        # not resurface if the local copy is later deleted (the value fold already
        # ignores it while the local copy wins). An ancestor's override stays: it
        # belongs to that layer and its other descendants.
        own_override = self._override_file_for_target(root, entry_id)
        if own_override is not None:
            self._delete_node_file(own_override)
        return self.read_lore_entry(entry_id)

    def delete_lore_entry(self, entry_id: str) -> LoreEntryList:
        # Captured before the unlink, so the purge rewrites the project this
        # delete belongs to even if another request opens a different one
        # mid-operation (#381).
        root = self._require_project()
        path = self._path_for_node_id(entry_id, "lore")
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        self._purge_references_to({entry_id}, root)
        return self.list_lore_entries()
