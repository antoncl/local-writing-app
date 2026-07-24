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


class LoreEntriesMixin:
    def list_lore_entries(self) -> LoreEntryList:
        index = self._build_node_index()
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
            entries.append(
                LoreEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body=body,
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
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
        # Heal stale fields (retired by a schema change) and dangling
        # references before validation — see _strip_unknown_metadata_fields
        # / _strip_dangling_references for the rationale.
        metadata = self._strip_unknown_metadata_fields(metadata, entry_type, schema)
        metadata = self._strip_dangling_references(metadata, schema, index)
        metadata_errors = self._validate_lore_entry_metadata(node_id, entry_type, metadata, schema, index)
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return LoreEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(body, node_id=node_id, entry_type=entry_type, schema=schema),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
            forked_from=self._forked_from_of(front_matter),
        )

    def save_lore_entry(self, entry_id: str, request: SaveLoreEntryRequest) -> LoreEntry:
        path = self._path_for_node_id(entry_id, "lore")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Lore Entry changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)

        # As of the authoring layer L, not the resolution scope (#393): a write
        # is validated against what its own target layer can store. Absent L
        # (every client today) this is the full-chain schema, unchanged. Lore is
        # the only inherited node kind, so it is the only save that can be
        # authored above the book — scenes and research notes are book-local.
        schema = self._schema_as_authored()
        metadata = self._normalise_metadata(request.metadata, path)
        # NOTE: the tag *vocabulary* stays full-chain here — the schema is
        # as-of-L but `_canonicalise_metadata_tags` still reads all layers and
        # writes its assertion back to the resolution scope's tags.yaml. Scoping
        # it to L means moving the write *target*, not just the read, which #393
        # did not do. ADR-0045 §4 requires this closed by #313/#314 at the
        # latest — earlier is welcome, it is a deadline and not a reservation.
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
        metadata_errors = self._validate_lore_entry_metadata(
            node_id,
            entry.entry_type,
            entry.metadata,
            schema,
            self._build_node_index(),
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_lore_entry_file(path, entry)
        self._maybe_rename_node_file(path, request.title)
        return self.read_lore_entry(node_id)

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
