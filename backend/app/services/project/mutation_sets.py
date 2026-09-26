"""Mutation-set slice of ProjectService (#62, GH #33, ADR-0095).

A mutation set is a Node kind (`mutation_set`): an ordered list of `(field,
op, value)` rows plus a `target_entry_type` (the lore entry-type its rows
apply to). Its entity binding is **optional** (ADR-0055 §3): unset ⇒ a
reusable template, entity chosen at apply time; set (`target_entity`) ⇒ an
entity-*pinned* set. Since ADR-0095, a pinned set's lifecycle state —
template / staged / active — is READ from the scenes that anchor it
(`anchors_by_set`, `mutation_set_anchors.py`), never stored: the set carries
no `placed` flag.

Storage mirrors prompt entries — layered Node markdown files under
`<project>/mutation-sets/`, but with **no prose body**: the rows + target
entry-type live in front matter (via `_write_node_entry_file`'s `extra=`), the
same way prompts store their `inputs`. A NEW set's file is named after its id
(`<set-id>.md`, ADR-0095 §12) — not its title, which is optional and may
change without churning the filename. `ProjectService` composes this mixin;
shared IO/index helpers resolve through the MRO (see `prompts.py`).
"""

from __future__ import annotations

from typing import Any, Literal

from app.models import (
    CopyMutationSetRequest,
    CopyMutationSetResult,
    CreateMutationSetEntryRequest,
    MutationSetAnchor,
    MutationSetEntry,
    MutationSetEntryList,
    MutationSetEntrySummary,
    MutationSetRow,
    SaveMutationSetEntryRequest,
)
from app.services.project.errors import ProjectServiceError

_VALID_ROW_OPS = ("replace", "add", "remove")


class MutationSetEntriesMixin:
    def list_mutation_set_entries(self) -> MutationSetEntryList:
        index = self._build_node_index()
        anchors_by_set = self.anchors_by_set()
        entries: list[MutationSetEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "mutation_set":
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            rows = self._parse_mutation_set_rows(front_matter.get("rows"))
            target_entity = self._mutation_set_target_entity(front_matter)
            anchors = anchors_by_set.get(entry.id, [])
            entries.append(
                MutationSetEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or ""),
                    entry_type=self._mutation_set_entry_type(front_matter),
                    target_entry_type=str(front_matter.get("target_entry_type") or ""),
                    target_entity=target_entity,
                    row_count=len(rows),
                    rows=rows,
                    anchors=anchors,
                    state=self._mutation_set_state(target_entity, anchors),
                    pin_missing=self._mutation_set_pin_missing(index, target_entity),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return MutationSetEntryList(entries=entries)

    def create_mutation_set_entry(
        self, request: CreateMutationSetEntryRequest
    ) -> MutationSetEntry:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "mutation_set")
        index = self._build_node_index()
        rows = self._prepare_set_rows(index, request.target_entity, request.target_entry_type, request.rows)
        entry_id = self._new_id("mutation_set")
        self._write_mutation_set_file(
            root / "mutation-sets" / f"{entry_id}.md",
            entry_id,
            request.title,
            request.entry_type,
            request.target_entry_type,
            request.target_entity,
            rows,
        )
        return self.read_mutation_set_entry(entry_id)

    def read_mutation_set_entry(self, entry_id: str) -> MutationSetEntry:
        index = self._build_node_index()  # built once, reused below (review fix #2236)
        index_entry = index.by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "mutation_set":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "mutation_set")
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        target_entity = self._mutation_set_target_entity(front_matter)
        anchors = self.anchors_by_set().get(node_id, [])
        return MutationSetEntry(
            id=node_id,
            title=str(front_matter.get("title") or ""),
            revision=self._revision(path),
            entry_type=self._mutation_set_entry_type(front_matter),
            target_entry_type=str(front_matter.get("target_entry_type") or ""),
            target_entity=target_entity,
            rows=self._parse_mutation_set_rows(front_matter.get("rows")),
            anchors=anchors,
            state=self._mutation_set_state(target_entity, anchors),
            pin_missing=self._mutation_set_pin_missing(index, target_entity),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_mutation_set_entry(
        self, entry_id: str, request: SaveMutationSetEntryRequest
    ) -> MutationSetEntry:
        path = self._path_for_node_id(entry_id, "mutation_set")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Mutation set changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "mutation_set")
        index = self._build_node_index()
        rows = self._prepare_set_rows(index, request.target_entity, request.target_entry_type, request.rows)
        self._write_mutation_set_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            request.target_entry_type,
            request.target_entity,
            rows,
        )
        # ADR-0095 §2: the file is named after its id, not its title — a title
        # save never renames it.
        return self.read_mutation_set_entry(node_id)

    def copy_mutation_set_entry(
        self, set_id: str, request: CopyMutationSetRequest
    ) -> CopyMutationSetResult:
        """Copy `set_id` into the OPEN project (ADR-0095 §6) — the source may
        live in an ancestor layer, resolved through the node index like a read.
        `request.target_entity` re-pins the copy (`None` keeps the source's own
        pin, including none for a template). Rows that no longer validate
        against the (re-)pinned entity's type are dropped and reported, never
        raised — the copy is written even when every row is dropped."""
        root = self._require_project()
        source = self.read_mutation_set_entry(set_id)
        target_entity = source.target_entity if request.target_entity is None else request.target_entity
        index = self._build_node_index()
        entry_type = self._set_validation_entry_type(index, target_entity, source.target_entry_type)
        kept_rows: list[MutationSetRow] = []
        dropped_rows: list[MutationSetRow] = []
        for row in source.rows:
            errors = self.validate_set_rows(entry_type, [row])
            (dropped_rows if errors else kept_rows).append(row)
        new_id = self._new_id("mutation_set")
        self._write_mutation_set_file(
            root / "mutation-sets" / f"{new_id}.md",
            new_id,
            source.title,
            source.entry_type,
            source.target_entry_type,
            target_entity,
            kept_rows,
        )
        return CopyMutationSetResult(
            entry=self.read_mutation_set_entry(new_id), dropped_rows=dropped_rows
        )

    def delete_mutation_set_entry(self, entry_id: str) -> MutationSetEntryList:
        # Captured before the unlink (#381) — same reasoning as
        # `delete_lore_entry`.
        root = self._require_project()
        path = self._path_for_node_id(entry_id, "mutation_set")
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        # ADR-0095 §9: deleting a set purges references to it — a chat's
        # `staged_set` included — the same way any other node delete does.
        # Today the file was deleted and the chat's reference left dangling.
        self._purge_references_to({entry_id}, root)
        return self.list_mutation_set_entries()

    # ----- helpers --------------------------------------------------------

    def _prepare_set_rows(
        self,
        index: Any,
        target_entity: str,
        target_entry_type: str,
        rows: list[MutationSetRow],
    ) -> list[MutationSetRow]:
        """Mint an id for every row with none (existing ids kept), refuse
        duplicate ids and an op outside replace/add/remove, then refuse any
        row that fails the position-free checks (ADR-0095 §4) against the
        pinned entity's type (or the set's own `target_entry_type` when
        unpinned), naming each bad row."""
        minted = [row if row.id else row.model_copy(update={"id": self._new_id("row")}) for row in rows]
        seen: set[str] = set()
        for row in minted:
            if row.id in seen:
                raise ProjectServiceError(f"Duplicate row id {row.id} in this set.", 422)
            seen.add(row.id)
            if row.op not in _VALID_ROW_OPS:
                raise ProjectServiceError(
                    f"Row {row.id} (field {row.field}) has op {row.op}; must be replace, add or remove.",
                    422,
                )
        entry_type = self._set_validation_entry_type(index, target_entity, target_entry_type)
        errors = self.validate_set_rows(entry_type, minted)
        if errors:
            raise ProjectServiceError("; ".join(errors), 422)
        return minted

    @staticmethod
    def _set_validation_entry_type(index: Any, target_entity: str, target_entry_type: str) -> str:
        """The entry_type to validate rows against (ADR-0095 §3): the pinned
        entity's own `entry_type` when the pin resolves to a lore entry in the
        node index; else the set's `target_entry_type`; "" (skip value
        validation) when neither resolves — a dead pin must still be saveable."""
        if target_entity:
            pin_entry = index.by_id.get(target_entity)
            if pin_entry is not None and pin_entry.kind == "lore":
                return pin_entry.entry_type
        return target_entry_type

    @staticmethod
    def _mutation_set_pin_missing(index: Any, target_entity: str) -> bool:
        """A pin that names a lore entry no longer in the node index (ADR-0095
        §2) — a dead pin, distinct from no pin at all."""
        if not target_entity:
            return False
        entry = index.by_id.get(target_entity)
        return entry is None or entry.kind != "lore"

    @staticmethod
    def _mutation_set_state(
        target_entity: str, anchors: list[MutationSetAnchor]
    ) -> Literal["template", "staged", "active"]:
        if not target_entity:
            return "template"
        return "active" if anchors else "staged"

    def _copy_mutation_set_unvalidated(self, set_id: str) -> str:
        """Copy `set_id` into a brand new set, keeping EVERY row untouched and
        unvalidated (ADR-0095 §11) — used only to give a re-minted restored
        anchor (`scene_snapshots.restore_snapshot`) its own set. Deliberately
        NOT `copy_mutation_set_entry`, which drops rows that fail validation;
        restore must not change what a scene resolves to (§4)."""
        root = self._require_project()
        source = self.read_mutation_set_entry(set_id)
        new_id = self._new_id("mutation_set")
        self._write_mutation_set_file(
            root / "mutation-sets" / f"{new_id}.md",
            new_id,
            source.title,
            source.entry_type,
            source.target_entry_type,
            source.target_entity,
            source.rows,
        )
        return new_id

    def _write_converted_mutation_set(self, converted: Any) -> None:
        """Write one `ConvertedSet` (`legacy_mutation_markers.py`) straight to
        `mutation-sets/<set-id>.md`, WITHOUT validation (ADR-0095 §4/§12): the
        migration's own output, and the fixtures a test converts through
        `convert_legacy_mutations`, must be writable even when a row no
        longer validates — Verify reports it, the writer fixes it later."""
        root = self._require_project()
        rows = [
            MutationSetRow(id=row.id, field=row.field, op=row.op, value=row.value)
            for row in converted.rows
        ]
        self._write_mutation_set_file(
            root / "mutation-sets" / f"{converted.set_id}.md",
            converted.set_id,
            converted.title,
            "mutation_set:mutation_set",
            converted.target_entry_type,
            converted.entity_id,
            rows,
        )

    def _write_mutation_set_file(
        self,
        path: Any,
        node_id: str,
        title: str,
        entry_type: str,
        target_entry_type: str,
        target_entity: str,
        rows: list[MutationSetRow],
    ) -> None:
        rows_payload = [row.model_dump() for row in rows]
        # ADR-0055 §3: the entity pin is a `metadata` entity_ref (so it earns a
        # set→subject edge + reference-integrity), NOT top-level front-matter like
        # target_entry_type/rows. Empty ⇒ no metadata block (omit_empty_metadata),
        # so a reusable set's file is byte-identical to today's.
        metadata = {"target_entity": target_entity} if target_entity else {}
        extra: dict[str, Any] = {"target_entry_type": target_entry_type, "rows": rows_payload}
        self._write_node_entry_file(
            path,
            node_id,
            title,
            entry_type,
            metadata,
            "",  # body-less: rows live in front matter, not a prose body
            extra=extra,
            omit_empty_metadata=True,
        )

    @staticmethod
    def _mutation_set_entry_type(front_matter: dict[str, Any]) -> str:
        raw = front_matter.get("entry_type") or "mutation_set:mutation_set"
        return raw if isinstance(raw, str) else "mutation_set:mutation_set"

    @staticmethod
    def _mutation_set_target_entity(front_matter: dict[str, Any]) -> str:
        # The entity pin round-trips through `metadata.target_entity` — the same
        # top-level-field ↔ metadata projection chat sessions use for `subject`.
        metadata = front_matter.get("metadata")
        if not isinstance(metadata, dict):
            return ""
        return str(metadata.get("target_entity", "") or "")

    @staticmethod
    def _parse_mutation_set_rows(raw: Any) -> list[MutationSetRow]:
        from pydantic import ValidationError

        if not isinstance(raw, list):
            return []
        parsed: list[MutationSetRow] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(MutationSetRow.model_validate(item))
            except ValidationError:
                continue  # skip a malformed row rather than fail the whole set
        return parsed
