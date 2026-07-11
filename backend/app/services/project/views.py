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

from collections.abc import Iterator
from typing import Any

from app.models_views import (
    CreateViewRequest,
    SaveViewRequest,
    UpdateViewUiRequest,
    ViewExpr,
    ViewLayout,
    ViewNode,
    ViewNodeList,
    ViewNodeSummary,
    ViewPresentation,
    ViewSpec,
    ViewUiState,
)
from app.services.project.errors import ProjectServiceError


class ViewsMixin:
    def _iter_view_entries(self) -> Iterator[tuple[Any, dict[str, Any], ViewSpec | None]]:
        """One node-index pass over stored views, yielding (index entry, front
        matter, parsed spec). list_views and the ref-cycle check share it so a
        view's file is read + parsed once per call by a single loop instead of
        two divergent ones (#95). Unreadable views are skipped."""
        for entry in self._build_node_index().by_id.values():
            if entry.kind != "view":
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            yield entry, front_matter, self._parse_view_spec(front_matter.get("spec"))

    def list_views(self) -> ViewNodeList:
        entries: list[ViewNodeSummary] = []
        for entry, front_matter, spec in self._iter_view_entries():
            entries.append(
                ViewNodeSummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=self._view_entry_type(front_matter),
                    view_kind=spec.kind if spec else "",
                    presentation=self._view_presentation(front_matter),
                    spec=spec,
                    ui=self._parse_view_ui(front_matter.get("ui")),
                    system=self._view_system(front_matter),
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
            ui=self._parse_view_ui(front_matter.get("ui")),
            system=self._view_system(front_matter),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_view(self, view_id: str, request: SaveViewRequest) -> ViewNode:
        path = self._path_for_node_id(view_id, "view")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        # ADR-0036: a system-provided default view is read-only — spec edits go
        # through Duplicate, not Edit. Fold state still updates via update_view_ui.
        if self._view_system(front_matter):
            raise ProjectServiceError("A system default view cannot be edited; duplicate it first.", 403)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("View changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "view")
        self._check_view_ref_cycles(node_id, request.spec)
        # Preserve fold/ui state — it lives on an independent lifecycle (the
        # lock-free /ui endpoint), so a spec save must not wipe it (ADR-0036).
        self._write_view_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            request.spec,
            request.presentation,
            request.layout,
            ui=self._parse_view_ui(front_matter.get("ui")),
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_view(node_id)

    def update_view_ui(self, view_id: str, request: UpdateViewUiRequest) -> ViewNode:
        """Lock-free fold/ui write (ADR-0036): rewrites ONLY the `ui` blob,
        preserving spec/presentation/layout/title/system. It takes no
        base_revision and does not consult the spec revision, so a fold toggle
        never 409s against a concurrent designer save — the two lifecycles are
        independent. (Default-view materialization for a `view_default_<kind>`
        id is deferred to the frontend null-cut slice, where `defaultView`/the
        kind-root spec lives; today this 404s on an absent view.)"""
        path = self._path_for_node_id(view_id, "view")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        spec = self._parse_view_spec(front_matter.get("spec"))
        if spec is None:
            raise ProjectServiceError(f"View {node_id} has no valid spec.", 422)
        self._write_view_file(
            path,
            node_id,
            str(front_matter.get("title") or node_id),
            self._view_entry_type(front_matter),
            spec,
            self._view_presentation(front_matter),
            self._parse_view_layout(front_matter.get("layout")),
            ui=request.ui,
            system=self._view_system(front_matter),
        )
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
        ui: ViewUiState | None = None,
        system: bool = False,
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
        # Fold/ui state (ADR-0036) — only when non-empty; `_write_node_entry_file`
        # skips falsy extra values, so an empty collapsed list drops cleanly.
        if ui is not None and ui.collapsed:
            extra["ui"] = ui.model_dump(exclude_none=True)
        # `system` marks the read-only default view; only write it when true
        # (default False needs no on-disk footprint).
        if system:
            extra["system"] = True
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
    def _view_system(front_matter: dict[str, Any]) -> bool:
        return front_matter.get("system") is True

    @staticmethod
    def _parse_view_ui(raw: Any) -> ViewUiState | None:
        """Parse the optional fold/ui blob (ADR-0036). Stored verbatim; a
        malformed one is dropped (fold state is disposable) rather than failing
        the read. None ⇒ no persisted fold state (all groups expanded)."""
        from pydantic import ValidationError

        if not isinstance(raw, dict):
            return None
        try:
            return ViewUiState.model_validate(raw)
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
            if node.nest is not None:
                walk(node.nest.parents)
                walk(node.nest.children)
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
        for entry, _front_matter, existing in self._iter_view_entries():
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
