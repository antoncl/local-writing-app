"""Transformation-set slice of ProjectService (#62, GH #33).

A transformation set is a reusable, body-less Node kind (`transformation`): an
ordered list of `(field, op, value)` rows plus a `target_entry_type` (the lore
entry-type its rows apply to). It expands to ordinary inline Model-A markers when
applied to a chosen entity (the entity is bound at apply time, not stored — the
set is a template). It is a **stamp, not a live link**: applied markers are
independent; edit-once-propagate is the deferred v2 (#66).

Storage mirrors prompt entries — layered Node markdown files under
`<project>/transformations/`, but with **no prose body**: the rows + target
entry-type live in front matter (via `_write_node_entry_file`'s `extra=`), the
same way prompts store their `inputs`. `ProjectService` composes this mixin;
shared IO/index helpers resolve through the MRO (see `prompts.py`).
"""

from __future__ import annotations

from typing import Any

from app.models import (
    CreateTransformationEntryRequest,
    SaveTransformationEntryRequest,
    TransformationEntry,
    TransformationEntryList,
    TransformationEntrySummary,
    TransformationRow,
)
from app.services.project.errors import ProjectServiceError


class TransformationEntriesMixin:
    def list_transformation_entries(self) -> TransformationEntryList:
        index = self._build_node_index()
        entries: list[TransformationEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "transformation":
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            rows = self._parse_transformation_rows(front_matter.get("rows"))
            entries.append(
                TransformationEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=self._transformation_entry_type(front_matter),
                    target_entry_type=str(front_matter.get("target_entry_type") or ""),
                    row_count=len(rows),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return TransformationEntryList(entries=entries)

    def create_transformation_entry(
        self, request: CreateTransformationEntryRequest
    ) -> TransformationEntry:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "transformation")
        entry_id = self._new_id("transformation")
        self._write_transformation_file(
            self._filepath_for_new_node(root / "transformations", request.title),
            entry_id,
            request.title,
            request.entry_type,
            request.target_entry_type,
            request.rows,
        )
        return self.read_transformation_entry(entry_id)

    def read_transformation_entry(self, entry_id: str) -> TransformationEntry:
        index_entry = self._build_node_index().by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "transformation":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "transformation")
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        return TransformationEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=self._transformation_entry_type(front_matter),
            target_entry_type=str(front_matter.get("target_entry_type") or ""),
            rows=self._parse_transformation_rows(front_matter.get("rows")),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_transformation_entry(
        self, entry_id: str, request: SaveTransformationEntryRequest
    ) -> TransformationEntry:
        path = self._path_for_node_id(entry_id, "transformation")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Transformation changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "transformation")
        self._write_transformation_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            request.target_entry_type,
            request.rows,
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_transformation_entry(node_id)

    def delete_transformation_entry(self, entry_id: str) -> TransformationEntryList:
        path = self._path_for_node_id(entry_id, "transformation")
        if path.exists():
            path.unlink()
        return self.list_transformation_entries()

    # ----- helpers --------------------------------------------------------

    def _write_transformation_file(
        self,
        path: Any,
        node_id: str,
        title: str,
        entry_type: str,
        target_entry_type: str,
        rows: list[TransformationRow],
    ) -> None:
        rows_payload = [row.model_dump() for row in rows]
        self._write_node_entry_file(
            path,
            node_id,
            title,
            entry_type,
            {},
            "",  # body-less: rows live in front matter, not a prose body
            extra={"target_entry_type": target_entry_type, "rows": rows_payload},
            omit_empty_metadata=True,
        )

    @staticmethod
    def _transformation_entry_type(front_matter: dict[str, Any]) -> str:
        raw = front_matter.get("entry_type") or "transformation"
        return raw if isinstance(raw, str) else "transformation"

    @staticmethod
    def _parse_transformation_rows(raw: Any) -> list[TransformationRow]:
        from pydantic import ValidationError

        if not isinstance(raw, list):
            return []
        parsed: list[TransformationRow] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(TransformationRow.model_validate(item))
            except ValidationError:
                continue  # skip a malformed row rather than fail the whole set
        return parsed
