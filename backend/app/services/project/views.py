"""Saved-view slice of ProjectService (0.5.0, epic #35 / #78).

A saved view is a frontmatter-only Node kind (`view`): a ViewSpec (anchor
`kind` + a set-algebra `expr` + `sort`) plus a `presentation` hint. Storage
mirrors mutation sets — layered Node markdown files under `<project>/views/`
with **no prose body**: the spec + presentation live in front matter (via
`_write_node_entry_file`'s `extra=`). `ProjectService` composes this mixin;
shared IO/index helpers resolve through the MRO (see `mutation_sets.py`).

0.5.0 step 1 lands storage + CRUD + a `view_ref` cycle check at save. There is
no evaluator yet — nothing consumes a stored spec's membership at runtime.
"""

from __future__ import annotations

from typing import Any

from app.models_views import (
    CreateViewRequest,
    SaveViewRequest,
    ViewExpr,
    ViewLayout,
    ViewNode,
    ViewNodeList,
    ViewNodeSummary,
    ViewPresentation,
    ViewSpec,
)
from app.services.project.errors import ProjectServiceError


class ViewsMixin:
    def list_views(self) -> ViewNodeList:
        index = self._build_node_index()
        entries: list[ViewNodeSummary] = []
        for entry in index.by_id.values():
            if entry.kind != "view":
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            spec = self._parse_view_spec(front_matter.get("spec"))
            entries.append(
                ViewNodeSummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=self._view_entry_type(front_matter),
                    view_kind=spec.kind if spec else "",
                    presentation=self._view_presentation(front_matter),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return ViewNodeList(entries=entries)

    def create_view(self, request: CreateViewRequest) -> ViewNode:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "view")
        self._check_view_ref_cycles(None, request.spec)
        view_id = self._new_id("view")
        (root / "views").mkdir(parents=True, exist_ok=True)
        self._write_view_file(
            self._filepath_for_new_node(root / "views", request.title),
            view_id,
            request.title,
            request.entry_type,
            request.spec,
            request.presentation,
            request.layout,
        )
        return self.read_view(view_id)

    def read_view(self, view_id: str) -> ViewNode:
        index_entry = self._build_node_index().by_id.get(view_id)
        if index_entry is not None and index_entry.kind == "view":
            path = index_entry.path
        else:
            path = self._path_for_node_id(view_id, "view")
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        spec = self._parse_view_spec(front_matter.get("spec"))
        if spec is None:
            raise ProjectServiceError(f"View {node_id} has no valid spec.", 422)
        return ViewNode(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=self._view_entry_type(front_matter),
            spec=spec,
            presentation=self._view_presentation(front_matter),
            layout=self._parse_view_layout(front_matter.get("layout")),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_view(self, view_id: str, request: SaveViewRequest) -> ViewNode:
        path = self._path_for_node_id(view_id, "view")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("View changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "view")
        self._check_view_ref_cycles(node_id, request.spec)
        self._write_view_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            request.spec,
            request.presentation,
            request.layout,
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_view(node_id)

    def delete_view(self, view_id: str) -> ViewNodeList:
        path = self._path_for_node_id(view_id, "view")
        if path.exists():
            path.unlink()
        return self.list_views()

    # ----- helpers --------------------------------------------------------

    def _write_view_file(
        self,
        path: Any,
        node_id: str,
        title: str,
        entry_type: str,
        spec: ViewSpec,
        presentation: ViewPresentation,
        layout: ViewLayout | None = None,
    ) -> None:
        # exclude_none keeps the on-disk spec compact — a leaf serializes as
        # `{type: lore:character}`, not every unset ViewExpr slot.
        extra: dict[str, Any] = {
            "spec": spec.model_dump(exclude_none=True),
            "presentation": presentation,
        }
        # Only write layout when the designer supplied one — keeps designer-less
        # / programmatic views clean (they fall back to auto-layout on open).
        if layout is not None:
            extra["layout"] = layout.model_dump(exclude_none=True)
        self._write_node_entry_file(
            path,
            node_id,
            title,
            entry_type,
            {},
            "",  # body-less: the spec lives in front matter, not a prose body
            extra=extra,
            omit_empty_metadata=True,
        )

    @staticmethod
    def _view_entry_type(front_matter: dict[str, Any]) -> str:
        raw = front_matter.get("entry_type") or "view:view"
        return raw if isinstance(raw, str) else "view:view"

    @staticmethod
    def _view_presentation(front_matter: dict[str, Any]) -> ViewPresentation:
        raw = front_matter.get("presentation")
        return raw if raw in ("tree", "grouped", "flat") else "flat"

    @staticmethod
    def _parse_view_spec(raw: Any) -> ViewSpec | None:
        from pydantic import ValidationError

        if not isinstance(raw, dict):
            return None
        try:
            return ViewSpec.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _parse_view_layout(raw: Any) -> ViewLayout | None:
        """Parse the optional designer layout blob; a malformed one is dropped
        (the designer just auto-lays-out the expr) rather than failing the read."""
        from pydantic import ValidationError

        if not isinstance(raw, dict):
            return None
        try:
            return ViewLayout.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _collect_view_refs(expr: ViewExpr | None) -> set[str]:
        """Every `view_ref` id anywhere in an expr tree (recursively)."""
        refs: set[str] = set()

        def walk(node: ViewExpr | None) -> None:
            if node is None:
                return
            if node.view_ref:
                refs.add(node.view_ref)
            for child in node.union or ():
                walk(child)
            for child in node.intersect or ():
                walk(child)
            if node.difference is not None:
                walk(node.difference.keep)
                walk(node.difference.remove)
            walk(node.complement)
            if node.annotate is not None:
                walk(node.of)

        walk(expr)
        return refs

    @classmethod
    def _spec_view_refs(cls, spec: ViewSpec | None) -> set[str]:
        """Every view_ref reachable from a ViewSpec — the top-level `expr` AND
        every named-handle group's `expr`. A ViewSpec is expr-XOR-groups, so a
        grouped view (named handles) carries its refs only under `groups`;
        walking `expr` alone would let a grouped view's ref cycles slip through."""
        if spec is None:
            return set()
        refs = cls._collect_view_refs(spec.expr)
        for group in spec.groups or ():
            refs |= cls._collect_view_refs(group.expr)
        return refs

    def _check_view_ref_cycles(self, view_id: str | None, spec: ViewSpec) -> None:
        """Reject a save whose view_ref graph would contain a cycle reachable
        from the view being written. Views are nodes, so ref cycles are real and
        would non-terminate any future evaluator (ADR-0021)."""
        graph: dict[str, set[str]] = {}
        for entry in self._build_node_index().by_id.values():
            if entry.kind != "view":
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            existing = self._parse_view_spec(front_matter.get("spec"))
            graph[entry.id] = self._spec_view_refs(existing)

        # A new view has no id yet — a placeholder node nothing else references.
        start = view_id or "__new__"
        graph[start] = self._spec_view_refs(spec)

        on_path: list[str] = []
        on_path_set: set[str] = set()
        settled: set[str] = set()

        def dfs(node: str) -> None:
            if node in on_path_set:
                cycle = [*on_path[on_path.index(node):], node]
                raise ProjectServiceError(
                    "View reference cycle detected: " + " → ".join(cycle) + ".",
                    422,
                )
            if node in settled:
                return
            on_path.append(node)
            on_path_set.add(node)
            for nxt in graph.get(node, set()):
                dfs(nxt)
            on_path.pop()
            on_path_set.discard(node)
            settled.add(node)

        dfs(start)
