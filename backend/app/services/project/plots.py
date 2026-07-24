"""Plot node slice of ProjectService.

Plot nodes are markdown files under `<project>/plot/`. Structured data lives in
front matter; optional prose stays in the markdown body for template notes and
author-facing explanations.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.models_plot import (
    CreatePlotNodeRequest,
    PlotBoardLayout,
    PlotBoardSpec,
    PlotNode,
    PlotNodeList,
    PlotNodeSummary,
    PlotTemplateInstanceSpec,
    PlotTemplateSpec,
    SavePlotNodeRequest,
)
from app.services.project.errors import ProjectServiceError


class PlotEntriesMixin:
    def list_plot_nodes(self) -> PlotNodeList:
        index = self._build_node_index()
        entries: list[PlotNodeSummary] = []
        for entry in index.by_id.values():
            if entry.kind != "plot":
                continue
            try:
                front_matter = self._read_front_matter_only(entry.path, strict=True)
            except ProjectServiceError:
                continue
            entries.append(
                PlotNodeSummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=self._plot_entry_type(front_matter),
                    system=self._plot_system(front_matter),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.entry_type, entry.title.lower(), entry.id))
        return PlotNodeList(entries=entries)

    def create_plot_node(self, request: CreatePlotNodeRequest) -> PlotNode:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "plot")
        node_id = self._new_id("plot")
        path = self._filepath_for_new_node(root / "plot", request.title)
        self._write_plot_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            request.body,
            metadata=self._normalise_metadata(request.metadata, path),
            template=self._default_template(request.entry_type, request.template),
            template_instance=self._default_template_instance(request.entry_type, request.template_instance),
            board=self._default_board(request.entry_type, request.board),
            layout=request.layout,
        )
        return self.read_plot_node(node_id)

    def read_plot_node(self, node_id: str) -> PlotNode:
        index_entry = self._build_node_index().by_id.get(node_id)
        if index_entry is not None and index_entry.kind == "plot":
            path = index_entry.path
        else:
            path = self._path_for_node_id(node_id, "plot")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        resolved_id = self._node_id_for_path(path, front_matter)
        entry_type = self._plot_entry_type(front_matter)
        schema = self.read_metadata_schema()
        metadata = self._strip_unknown_metadata_fields(
            self._normalise_metadata(front_matter.get("metadata"), path),
            entry_type,
            schema,
        )
        metadata = self._strip_dangling_references(metadata, schema, self._build_node_index())
        return PlotNode(
            id=resolved_id,
            title=str(front_matter.get("title") or resolved_id),
            revision=self._revision(path),
            entry_type=entry_type,
            body=body.rstrip(),
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(body, node_id=resolved_id, entry_type=entry_type, schema=schema),
            template=self._parse_plot_template(front_matter.get("template")),
            template_instance=self._parse_plot_template_instance(front_matter.get("template_instance")),
            board=self._parse_plot_board(front_matter.get("board")),
            layout=self._parse_plot_layout(front_matter.get("layout")),
            system=self._plot_system(front_matter),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_plot_node(self, node_id: str, request: SavePlotNodeRequest) -> PlotNode:
        path = self._path_for_node_id(node_id, "plot")
        front_matter = self._read_front_matter_only(path, strict=True)
        resolved_id = self._node_id_for_path(path, front_matter)
        if self._plot_system(front_matter):
            raise ProjectServiceError("A system plot node cannot be edited; duplicate it first.", 403)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Plot node changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "plot")
        metadata = self._normalise_metadata(request.metadata, path)
        self._write_plot_file(
            path,
            resolved_id,
            request.title,
            request.entry_type,
            request.body,
            metadata=metadata,
            template=self._default_template(request.entry_type, request.template),
            template_instance=self._default_template_instance(request.entry_type, request.template_instance),
            board=self._default_board(request.entry_type, request.board),
            layout=request.layout,
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_plot_node(resolved_id)

    def delete_plot_node(self, node_id: str) -> PlotNodeList:
        path = self._path_for_node_id(node_id, "plot")
        if path.exists():
            front_matter = self._read_front_matter_only(path, strict=True)
            if self._plot_system(front_matter):
                raise ProjectServiceError("A system plot node cannot be deleted.", 403)
            path.unlink()
        return self.list_plot_nodes()

    def _seed_builtin_plot_templates(self, root: Any) -> None:
        plot_dir = root / "plot"
        plot_dir.mkdir(parents=True, exist_ok=True)
        for filename, node_id, title, body, points in self._builtin_plot_templates():
            path = plot_dir / filename
            if path.exists():
                continue
            self._write_plot_file(
                path,
                node_id,
                title,
                "plot:template",
                body,
                template=PlotTemplateSpec(plot_points=points),
                system=True,
            )

    # ----- helpers --------------------------------------------------------

    def _write_plot_file(
        self,
        path: Any,
        node_id: str,
        title: str,
        entry_type: str,
        body: str = "",
        *,
        metadata: dict[str, Any] | None = None,
        template: PlotTemplateSpec | None = None,
        template_instance: PlotTemplateInstanceSpec | None = None,
        board: PlotBoardSpec | None = None,
        layout: PlotBoardLayout | None = None,
        system: bool = False,
    ) -> None:
        extra: dict[str, Any] = {}
        if template is not None:
            extra["template"] = template.model_dump(exclude_none=True)
        if template_instance is not None:
            extra["template_instance"] = template_instance.model_dump(exclude_none=True)
        if board is not None:
            extra["board"] = board.model_dump(exclude_none=True)
        if layout is not None:
            extra["layout"] = layout.model_dump(exclude_none=True)
        if system:
            extra["system"] = True
        self._write_node_entry_file(
            path,
            node_id,
            title,
            entry_type,
            metadata or {},
            body,
            extra=extra,
            omit_empty_metadata=True,
        )

    @staticmethod
    def _plot_entry_type(front_matter: dict[str, Any]) -> str:
        raw = front_matter.get("entry_type") or "plot:board"
        return raw if isinstance(raw, str) else "plot:board"

    @staticmethod
    def _plot_system(front_matter: dict[str, Any]) -> bool:
        return front_matter.get("system") is True

    @staticmethod
    def _parse_plot_template(raw: Any) -> PlotTemplateSpec | None:
        if not isinstance(raw, dict):
            return None
        try:
            return PlotTemplateSpec.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _parse_plot_template_instance(raw: Any) -> PlotTemplateInstanceSpec | None:
        if not isinstance(raw, dict):
            return None
        try:
            return PlotTemplateInstanceSpec.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _parse_plot_board(raw: Any) -> PlotBoardSpec | None:
        if not isinstance(raw, dict):
            return None
        try:
            return PlotBoardSpec.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _parse_plot_layout(raw: Any) -> PlotBoardLayout | None:
        if not isinstance(raw, dict):
            return None
        try:
            return PlotBoardLayout.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _default_template(entry_type: str, value: PlotTemplateSpec | None) -> PlotTemplateSpec | None:
        if value is not None:
            return value
        return PlotTemplateSpec() if entry_type == "plot:template" else None

    @staticmethod
    def _default_template_instance(
        entry_type: str, value: PlotTemplateInstanceSpec | None
    ) -> PlotTemplateInstanceSpec | None:
        if value is not None:
            return value
        return PlotTemplateInstanceSpec() if entry_type == "plot:template_instance" else None

    @staticmethod
    def _default_board(entry_type: str, value: PlotBoardSpec | None) -> PlotBoardSpec | None:
        if value is not None:
            return value
        return PlotBoardSpec() if entry_type == "plot:board" else None

    @staticmethod
    def _builtin_plot_templates() -> list[tuple[str, str, str, str, list[Any]]]:
        from app.models_plot import PlotTemplatePoint

        return [
            (
                "Three Act Structure.md",
                "plot_template_three_act",
                "Three Act Structure",
                "A generic three-part structure template. Duplicate into the book plot folder before editing.",
                [
                    PlotTemplatePoint(id="setup_pressure", title="Setup pressure", function_claim="Establishes the central pressure before commitment."),
                    PlotTemplatePoint(id="first_turn", title="First turn", function_claim="Makes the old path unavailable."),
                    PlotTemplatePoint(id="midpoint_reversal", title="Midpoint reversal", function_claim="Changes the power balance or reframes the goal."),
                    PlotTemplatePoint(id="crisis", title="Crisis", function_claim="Forces the hard choice before resolution."),
                    PlotTemplatePoint(id="resolution", title="Resolution", function_claim="Shows the consequence of the final choice."),
                ],
            ),
            (
                "Heroine Journey.md",
                "plot_template_heroine_journey",
                "Heroine Journey",
                "A generic internal-integration journey template. Duplicate into the book plot folder before editing.",
                [
                    PlotTemplatePoint(id="separation", title="Separation", function_claim="The protagonist is pushed away from an old identity or belonging."),
                    PlotTemplatePoint(id="descent", title="Descent", function_claim="Pressure exposes the limits of the old survival strategy."),
                    PlotTemplatePoint(id="reconnection", title="Reconnection", function_claim="The protagonist claims or rebuilds a needed source of belonging."),
                    PlotTemplatePoint(id="integration", title="Integration", function_claim="Inner and outer choices align in action."),
                ],
            ),
            (
                "Mystery Spine.md",
                "plot_template_mystery_spine",
                "Mystery Spine",
                "A generic fair-play mystery spine. Duplicate into the book plot folder before editing.",
                [
                    PlotTemplatePoint(id="crime_or_question", title="Crime or question", function_claim="Creates the explicit puzzle the reader tracks."),
                    PlotTemplatePoint(id="first_clue", title="First clue", function_claim="Provides inspectable evidence, not just atmosphere."),
                    PlotTemplatePoint(id="red_herring", title="Red herring", function_claim="Supports a plausible but wrong interpretation."),
                    PlotTemplatePoint(id="reveal_chain", title="Reveal chain", function_claim="Lets the solution feel earned before confirmation."),
                    PlotTemplatePoint(id="solution", title="Solution", function_claim="Resolves the puzzle with evidence already made available."),
                ],
            ),
        ]
