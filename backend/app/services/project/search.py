"""Full-text / metadata search slice of ProjectService (#14 backend split).

`search` scans scene + lore markdown (body lines and resolved metadata
values) and, optionally, open TODOs — both the todo.yaml list and the
in-scene embedded-todo comments. This mixin owns that query path plus its
search-only helpers; `ProjectService` composes it.

Method bodies moved verbatim. Shared helpers they call (`self._require_project`,
`self._scene_display_paths` [moved here], `self.read_todos`,
`self._read_markdown_with_front_matter`, `self._node_id_for_path`,
`self.read_metadata_schema`, `self._build_node_index`,
`self._normalise_metadata`, `self.read_structure`) resolve through the MRO at
call time. The embedded-todo scan now delegates to `self._scan_embedded_todos()`
(EmbeddedTodosMixin), which owns `EMBEDDED_TODO_PATTERN` alongside the marker
mutators (GH #45).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.models import (
    MetadataSchema,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StructureNode,
)
from app.services.project.node_index import NodeIndex
from app.services.tree_structure import StructureVisitor, TreeStructureService


class SearchMixin:
    def search(self, request: SearchRequest) -> SearchResponse:
        root = self._require_project()
        hits: list[SearchHit] = []
        query = request.query.strip()

        if not query and not request.include_open_todos:
            return SearchResponse(query=query, hits=[])

        scene_paths = self._scene_display_paths()
        pattern = re.compile(re.escape(query), re.IGNORECASE) if query else None
        if request.include_open_todos:
            hits.extend(self._search_open_todos(pattern, scene_paths))

        if pattern is not None:
            schema = self.read_metadata_schema()
            node_index = self._build_node_index(root)
            if request.include_scenes:
                hits.extend(self._search_scene_content(root, pattern, scene_paths, schema, node_index))
            if request.include_lore:
                hits.extend(self._search_lore_content(root, pattern, schema, node_index))
        return SearchResponse(query=request.query, hits=hits)

    def _search_open_todos(
        self, pattern: re.Pattern[str] | None, scene_paths: dict[str, str]
    ) -> list[SearchHit]:
        """Open TODOs matching `pattern` (or all open ones when `pattern` is
        None) — both the todo.yaml list and the in-scene embedded-todo comments."""
        hits: list[SearchHit] = []
        for item in self.read_todos().items:
            if item.status != "open":
                continue
            if pattern is None or pattern.search(item.text):
                hits.append(
                    SearchHit(
                        kind="manuscript" if item.scene_id else "project",
                        file_id=item.scene_id or "project",
                        path=f"{scene_paths.get(item.scene_id, 'Project')} TODO" if item.scene_id else "Project TODO",
                        line=1,
                        excerpt=item.text,
                        todo_id=item.id,
                    )
                )

        for todo in self._scan_embedded_todos():
            if todo.status != "open":
                continue
            excerpt = todo.note or todo.text
            if pattern is None or pattern.search(f"{todo.note} {todo.text}"):
                hits.append(
                    SearchHit(
                        kind="manuscript",
                        file_id=todo.scene_id,
                        path=todo.scene_path,
                        line=todo.line,
                        excerpt=excerpt,
                        todo_id=todo.todo_id,
                    )
                )
        return hits

    def _search_scene_content(
        self,
        root: Path,
        pattern: re.Pattern[str],
        scene_paths: dict[str, str],
        schema: MetadataSchema,
        node_index: NodeIndex,
    ) -> list[SearchHit]:
        """Scene metadata + body lines matching `pattern`."""
        hits: list[SearchHit] = []
        for path in (root / "scenes").rglob("*.md"):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            scene_id = self._node_id_for_path(path, front_matter)
            title = str(front_matter.get("title") or scene_id)
            status = str(front_matter.get("status") or "draft")
            entry_type = str(front_matter.get("entry_type") or "manuscript:scene")
            metadata = self._resolve_reference_titles(
                self._normalise_metadata(front_matter.get("metadata"), path),
                entry_type,
                schema,
                node_index,
            )
            searchable_metadata = {
                "title": title,
                "status": status,
                "entry_type": entry_type,
                **metadata,
            }
            for label, value in self._iter_metadata_search_values(searchable_metadata):
                if pattern.search(value):
                    hits.append(
                        SearchHit(
                            kind="manuscript",
                            file_id=scene_id,
                            path=f"{scene_paths.get(scene_id, str(path.relative_to(root)))} metadata",
                            line=1,
                            excerpt=f"{label}: {value}",
                        )
                    )
            for index, line in enumerate(body.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(
                        SearchHit(
                            kind="manuscript",
                            file_id=scene_id,
                            path=scene_paths.get(scene_id, str(path.relative_to(root))),
                            line=index,
                            excerpt=line.strip(),
                        )
                    )
        return hits

    def _search_lore_content(
        self,
        root: Path,
        pattern: re.Pattern[str],
        schema: MetadataSchema,
        node_index: NodeIndex,
    ) -> list[SearchHit]:
        """Lore metadata + body lines matching `pattern`."""
        hits: list[SearchHit] = []
        for path in (root / "lore").rglob("*.md"):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            entry_id = self._node_id_for_path(path, front_matter)
            title = str(front_matter.get("title") or entry_id)
            entry_type = str(front_matter.get("entry_type") or "lore:note")
            metadata = self._resolve_reference_titles(
                self._normalise_metadata(front_matter.get("metadata"), path),
                entry_type,
                schema,
                node_index,
            )
            searchable_metadata = {
                "title": title,
                "entry_type": entry_type,
                **metadata,
            }
            for label, value in self._iter_metadata_search_values(searchable_metadata):
                if pattern.search(value):
                    hits.append(
                        SearchHit(
                            kind="lore",
                            file_id=entry_id,
                            path=f"Lore / {title} metadata",
                            line=1,
                            excerpt=f"{label}: {value}",
                        )
                    )
            for index, line in enumerate(body.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(
                        SearchHit(
                            kind="lore",
                            file_id=entry_id,
                            path=f"Lore / {title}",
                            line=index,
                            excerpt=line.strip(),
                        )
                    )
        return hits

    def _iter_metadata_search_values(self, metadata: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        for key, raw_value in metadata.items():
            label = f"{prefix}.{key}" if prefix else key
            if raw_value is None:
                continue
            if isinstance(raw_value, dict):
                values.extend(self._iter_metadata_search_values(raw_value, label))
            elif isinstance(raw_value, list):
                # A list may hold record items (#698): one searchable pair per
                # record item (member values joined), scalars batched as
                # before — never str(dict), which buries the text in a Python
                # repr, and never one pair per member, which floods the hit
                # list from a single entry.
                scalar_text = ", ".join(
                    str(item) for item in raw_value if item is not None and not isinstance(item, dict)
                )
                if scalar_text:
                    values.append((label, scalar_text))
                for position, item in enumerate(raw_value):
                    if isinstance(item, dict):
                        item_text = " · ".join(
                            str(member) for member in item.values() if member not in (None, "")
                        )
                        if item_text:
                            values.append((f"{label}[{position}]", item_text))
            else:
                text = str(raw_value)
                if text:
                    values.append((label, text))
        return values

    def _resolve_reference_titles(
        self,
        metadata: dict[str, Any],
        entry_type: str,
        schema: MetadataSchema,
        node_index: NodeIndex,
    ) -> dict[str, Any]:
        entry_definition = schema.entry_types.get(entry_type)
        if entry_definition is None:
            return metadata
        resolved = dict(metadata)
        for field_id in entry_definition.fields:
            field = schema.fields.get(field_id)
            if field is None:
                continue
            value = resolved.get(field_id)
            if value is None:
                continue
            if field.type == "entity_ref" and isinstance(value, str):
                target = node_index.by_id.get(value)
                if target and target.title:
                    resolved[field_id] = target.title
            elif field.type == "entity_ref_list" and isinstance(value, list):
                resolved[field_id] = [
                    (node_index.by_id.get(item).title if isinstance(item, str) and node_index.by_id.get(item) and node_index.by_id.get(item).title else item)
                    for item in value
                ]
        return resolved

    def _scene_display_paths(self) -> dict[str, str]:
        class _Paths(StructureVisitor):
            """`scene_id → "Act / Chapter / Scene"` title breadcrumb, root title
            omitted, for every node carrying a scene_id."""

            def __init__(self) -> None:
                self.paths: dict[str, str] = {}

            def visit_node(
                self, node: StructureNode, ancestors: tuple[StructureNode, ...]
            ) -> None:
                if not node.scene_id:
                    return
                titles = [a.title for a in ancestors if a.type != "root"]
                if node.type != "root":
                    titles.append(node.title)
                self.paths[node.scene_id] = " / ".join(titles)

        visitor = _Paths()
        TreeStructureService.walk(self.read_structure().root, visitor)
        return visitor.paths
