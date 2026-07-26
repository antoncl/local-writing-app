"""Plot node slice of ProjectService.

Plot nodes are markdown files under `<project>/plot/`. Structured data lives in
front matter; optional prose stays in the markdown body for template notes and
author-facing explanations.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.models.entries import CreateSceneRequest
from app.models_plot import (
    CreatePlotNodeRequest,
    PlotBoardLayout,
    PlotBoardSpec,
    PlotContextCard,
    PlotContextClaim,
    PlotContextPacket,
    PlotContextPoint,
    PlotContextRelationship,
    PlotContextTemplateInstance,
    PlotNode,
    PlotNodeList,
    PlotNodeSummary,
    PlotTemplateInstanceSpec,
    PlotTemplateSpec,
    PromotePlotCardRequest,
    PromotePlotCardResponse,
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
        entries.sort(
            key=lambda entry: (entry.entry_type, entry.title.lower(), entry.id)
        )
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
            template_instance=self._default_template_instance(
                request.entry_type, request.template_instance
            ),
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
        plot_family = self._plot_data_family(entry_type, schema=schema)
        metadata = self._strip_unknown_metadata_fields(
            self._normalise_metadata(front_matter.get("metadata"), path),
            entry_type,
            schema,
        )
        metadata = self._strip_dangling_references(
            metadata, schema, self._build_node_index()
        )
        return PlotNode(
            id=resolved_id,
            title=str(front_matter.get("title") or resolved_id),
            revision=self._revision(path),
            entry_type=entry_type,
            body=body.rstrip(),
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(
                body, node_id=resolved_id, entry_type=entry_type, schema=schema
            ),
            template=self._parse_plot_template(
                front_matter.get("template"),
                node_id=resolved_id,
                required=plot_family == "template",
            ),
            template_instance=self._parse_plot_template_instance(
                front_matter.get("template_instance"),
                node_id=resolved_id,
                required=plot_family == "template_instance",
            ),
            board=self._parse_plot_board(
                front_matter.get("board"),
                node_id=resolved_id,
                required=plot_family == "board",
            ),
            layout=self._parse_plot_layout(
                front_matter.get("layout"), node_id=resolved_id
            ),
            system=self._plot_system(front_matter),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_plot_node(self, node_id: str, request: SavePlotNodeRequest) -> PlotNode:
        path = self._path_for_node_id(node_id, "plot")
        front_matter = self._read_front_matter_only(path, strict=True)
        resolved_id = self._node_id_for_path(path, front_matter)
        if self._plot_system(front_matter):
            raise ProjectServiceError(
                "A system plot node cannot be edited; duplicate it first.", 403
            )
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError(
                "Plot node changed on disk after it was opened.", 409
            )
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
            template_instance=self._default_template_instance(
                request.entry_type, request.template_instance
            ),
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
            self._delete_node_file(path)
        return self.list_plot_nodes()

    def promote_plot_card(
        self, node_id: str, request: PromotePlotCardRequest
    ) -> PromotePlotCardResponse:
        path = self._path_for_node_id(node_id, "plot")
        front_matter = self._read_front_matter_only(path, strict=True)
        if self._plot_system(front_matter):
            raise ProjectServiceError(
                "A system plot node cannot be edited; duplicate it first.", 403
            )

        plot_node = self.read_plot_node(node_id)
        if plot_node.entry_type != "plot:board" or plot_node.board is None:
            raise ProjectServiceError(f"Plot node {node_id} is not a board.", 422)
        if request.base_revision and request.base_revision != plot_node.revision:
            raise ProjectServiceError(
                "Plot node changed on disk after it was opened.", 409
            )

        card_index = next(
            (
                index
                for index, candidate in enumerate(plot_node.board.cards)
                if candidate.id == request.card_id
            ),
            None,
        )
        if card_index is None:
            raise ProjectServiceError(
                f"Plot card {request.card_id} does not exist.", 404
            )

        card = plot_node.board.cards[card_index]
        if card.node_ref:
            raise ProjectServiceError("Plot card is already linked to a scene.", 422)

        title = (request.title or card.title).strip()
        if not title:
            raise ProjectServiceError("Scene title cannot be empty.", 422)
        parent_id = request.parent_id or card.structure_column_id
        scene = self.create_scene(CreateSceneRequest(title=title, parent_id=parent_id))

        next_board = plot_node.board.model_copy(deep=True)
        next_board.cards[card_index] = card.model_copy(
            update={"title": title, "node_ref": scene.id}
        )
        self._write_plot_file(
            path,
            plot_node.id,
            plot_node.title,
            plot_node.entry_type,
            plot_node.body,
            metadata=plot_node.metadata,
            template=plot_node.template,
            template_instance=plot_node.template_instance,
            board=next_board,
            layout=plot_node.layout,
        )
        return PromotePlotCardResponse(
            plot=self.read_plot_node(plot_node.id),
            scene=scene,
            structure=self.read_structure(),
        )

    def read_plot_context(
        self,
        board_id: str,
        *,
        scene_id: str | None = None,
        include_future: bool = False,
    ) -> PlotContextPacket:
        board_node = self.read_plot_node(board_id)
        if board_node.entry_type != "plot:board" or board_node.board is None:
            raise ProjectServiceError(f"Plot node {board_id} is not a board.", 422)

        structure = None
        scene_order: dict[str, int] = {}
        structure_nodes: dict[str, Any] = {}
        try:
            structure = self.read_structure()
            scene_order, structure_nodes = self._plot_scene_order(structure.root)
        except Exception:
            structure = None

        target_index = scene_order.get(scene_id or "") if scene_id else None
        visible_cards: list[PlotContextCard] = []
        visible_card_ids: set[str] = set()
        omitted_future_cards = 0
        omitted_unordered_cards = 0

        for card in board_node.board.cards:
            card_scene_id, structure_node = self._plot_card_scene(
                card, scene_order, structure_nodes
            )
            manuscript_index = scene_order.get(card_scene_id or "")
            visible = include_future
            if not visible and scene_id and target_index is not None:
                visible = (
                    manuscript_index is not None and manuscript_index <= target_index
                )
            if not visible:
                if manuscript_index is None:
                    omitted_unordered_cards += 1
                else:
                    omitted_future_cards += 1
                continue
            visible_card_ids.add(card.id)
            visible_cards.append(
                PlotContextCard(
                    id=card.id,
                    title=card.title,
                    synopsis=card.synopsis,
                    scene_id=card_scene_id,
                    structure_node_id=getattr(structure_node, "id", None),
                    structure_title=getattr(structure_node, "title", None),
                    manuscript_index=manuscript_index,
                    primary_plotline_id=card.primary_plotline_id,
                )
            )

        visible_claims = [
            PlotContextClaim(
                id=claim.id,
                card_id=claim.card_id,
                template_instance_id=claim.template_instance_id,
                plot_point_id=claim.plot_point_id,
                plotline_id=claim.plotline_id,
                claim_type=claim.claim_type,
                claim_label=claim.claim_label,
                strength=claim.strength,
                evidence=claim.evidence,
                rationale=claim.rationale,
                ai_notes=claim.ai_notes,
            )
            for claim in board_node.board.claims
            if claim.card_id in visible_card_ids
        ]
        visible_claim_ids = {claim.id for claim in visible_claims}
        visible_relationships = [
            PlotContextRelationship(
                id=relationship.id,
                from_card_id=relationship.from_card_id,
                to_card_id=relationship.to_card_id,
                kind=relationship.kind,
                label=relationship.label,
            )
            for relationship in board_node.board.relationships
            if relationship.from_card_id in visible_card_ids
            and relationship.to_card_id in visible_card_ids
        ]
        template_instances = self._plot_context_template_instances(visible_claims)
        referenced_plotlines = {
            value
            for value in (
                [card.primary_plotline_id for card in visible_cards]
                + [claim.plotline_id for claim in visible_claims]
            )
            if value
        }
        plotlines = [
            plotline
            for plotline in board_node.board.plotlines
            if plotline.id in referenced_plotlines
        ]
        return PlotContextPacket(
            board_id=board_node.id,
            board_title=board_node.title,
            scope_scene_id=scene_id,
            include_future=include_future,
            cards=visible_cards,
            claims=visible_claims,
            template_instances=template_instances,
            plotlines=plotlines,
            relationships=visible_relationships,
            omitted_counts={
                "future_cards": omitted_future_cards,
                "unordered_cards": omitted_unordered_cards,
                "claims": len(board_node.board.claims) - len(visible_claim_ids),
                "relationships": len(board_node.board.relationships)
                - len(visible_relationships),
            },
        )

    def read_plot_context_for_selection(
        self,
        node_id: str,
        *,
        scene_id: str | None = None,
        include_future: bool = False,
    ) -> PlotContextPacket:
        plot_node = self.read_plot_node(node_id)
        if plot_node.entry_type == "plot:board":
            return self.read_plot_context(
                plot_node.id,
                scene_id=scene_id,
                include_future=include_future,
            )
        if plot_node.entry_type == "plot:template_instance":
            board_id = self._plot_board_id_for_template_instance(plot_node.id)
            if not board_id:
                raise ProjectServiceError(
                    f"Plot template instance {plot_node.id} is not linked to a board.",
                    422,
                )
            packet = self.read_plot_context(
                board_id,
                scene_id=scene_id,
                include_future=include_future,
            )
            return self._filter_plot_context_to_template_instance(
                packet,
                plot_node.id,
            )
        raise ProjectServiceError(
            f"Plot node {node_id} cannot be used as prompt plot context.",
            422,
        )

    def _plot_board_id_for_template_instance(self, instance_id: str) -> str | None:
        for summary in self.list_plot_nodes().entries:
            if summary.entry_type != "plot:board":
                continue
            try:
                board_node = self.read_plot_node(summary.id)
            except ProjectServiceError:
                continue
            board = board_node.board
            if board is None:
                continue
            if instance_id in board.template_instance_ids:
                return board_node.id
            if any(plotline.template_instance_id == instance_id for plotline in board.plotlines):
                return board_node.id
            if any(claim.template_instance_id == instance_id for claim in board.claims):
                return board_node.id
        return None

    def _filter_plot_context_to_template_instance(
        self,
        packet: PlotContextPacket,
        template_instance_id: str,
    ) -> PlotContextPacket:
        claims = [
            claim
            for claim in packet.claims
            if claim.template_instance_id == template_instance_id
        ]
        card_ids = {claim.card_id for claim in claims}
        cards = [card for card in packet.cards if card.id in card_ids]
        relationships = [
            relationship
            for relationship in packet.relationships
            if relationship.from_card_id in card_ids and relationship.to_card_id in card_ids
        ]
        plotlines = [
            plotline
            for plotline in packet.plotlines
            if plotline.template_instance_id == template_instance_id
            or any(claim.plotline_id == plotline.id for claim in claims)
            or any(card.primary_plotline_id == plotline.id for card in cards)
        ]
        template_instances = [
            instance
            for instance in packet.template_instances
            if instance.id == template_instance_id
        ]
        if not template_instances:
            instance = self._plot_context_template_instance(template_instance_id, None)
            if instance is not None:
                template_instances = [instance]

        omitted = dict(packet.omitted_counts)
        omitted["other_template_instances"] = max(
            0, len(packet.template_instances) - len(template_instances)
        )
        omitted["other_claims"] = max(0, len(packet.claims) - len(claims))
        omitted["other_cards"] = max(0, len(packet.cards) - len(cards))
        omitted["other_relationships"] = max(
            0, len(packet.relationships) - len(relationships)
        )
        return packet.model_copy(
            update={
                "cards": cards,
                "claims": claims,
                "template_instances": template_instances,
                "plotlines": plotlines,
                "relationships": relationships,
                "omitted_counts": omitted,
            }
        )

    def _seed_builtin_plot_templates(self, root: Any) -> None:
        plot_dir = root / "plot"
        plot_dir.mkdir(parents=True, exist_ok=True)
        inherited_ids = self._inherited_plot_node_ids(root)
        for builtin in self._builtin_plot_templates():
            filename = builtin["filename"]
            node_id = builtin["node_id"]
            title = builtin["title"]
            path = plot_dir / filename
            if node_id in inherited_ids:
                continue
            if path.exists():
                try:
                    front_matter = self._read_front_matter_only(path, strict=False)
                except ProjectServiceError:
                    continue
                if front_matter.get("id") != node_id or not self._plot_system(
                    front_matter
                ):
                    continue
            self._write_plot_file(
                path,
                node_id,
                title,
                "plot:template",
                builtin["body"],
                template=builtin["template"],
                system=True,
            )

    # ----- helpers --------------------------------------------------------

    def _inherited_plot_node_ids(self, root: Any) -> set[str]:
        root_path = root.resolve()
        ids: set[str] = set()
        for layer in self.collect_layers(root_path):
            if layer.folder == root_path:
                continue
            for path in sorted((layer.folder / "plot").glob("*.md")):
                try:
                    front_matter = self._read_front_matter_only(path, strict=False)
                except ProjectServiceError:
                    continue
                raw_id = front_matter.get("id")
                if isinstance(raw_id, str) and raw_id.strip():
                    ids.add(raw_id.strip())
        return ids

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

    def _plot_data_family(
        self, entry_type: str, *, schema: Any | None = None
    ) -> str | None:
        ancestry = self.entry_type_ancestry(entry_type, schema=schema)
        if "plot:template" in ancestry:
            return "template"
        if "plot:template_instance" in ancestry:
            return "template_instance"
        if "plot:board" in ancestry:
            return "board"
        return None

    @staticmethod
    def _invalid_plot_data(
        node_id: str, section: str, exc: ValidationError | None = None
    ) -> ProjectServiceError:
        message = f"Plot node {node_id} has invalid {section} data."
        if exc is not None and exc.errors():
            message = f"{message} {exc.errors()[0].get('msg', '')}".strip()
        return ProjectServiceError(message, 422)

    def _parse_plot_template(
        self,
        raw: Any,
        *,
        node_id: str,
        required: bool = False,
    ) -> PlotTemplateSpec | None:
        if raw is None:
            if required:
                raise ProjectServiceError(
                    f"Plot node {node_id} is missing template data.", 422
                )
            return None
        if not isinstance(raw, dict):
            raise self._invalid_plot_data(node_id, "template")
        try:
            return PlotTemplateSpec.model_validate(raw)
        except ValidationError as exc:
            raise self._invalid_plot_data(node_id, "template", exc) from exc

    def _parse_plot_template_instance(
        self,
        raw: Any,
        *,
        node_id: str,
        required: bool = False,
    ) -> PlotTemplateInstanceSpec | None:
        if raw is None:
            if required:
                raise ProjectServiceError(
                    f"Plot node {node_id} is missing template_instance data.", 422
                )
            return None
        if not isinstance(raw, dict):
            raise self._invalid_plot_data(node_id, "template_instance")
        try:
            return PlotTemplateInstanceSpec.model_validate(raw)
        except ValidationError as exc:
            raise self._invalid_plot_data(node_id, "template_instance", exc) from exc

    def _parse_plot_board(
        self,
        raw: Any,
        *,
        node_id: str,
        required: bool = False,
    ) -> PlotBoardSpec | None:
        if raw is None:
            if required:
                raise ProjectServiceError(
                    f"Plot node {node_id} is missing board data.", 422
                )
            return None
        if not isinstance(raw, dict):
            raise self._invalid_plot_data(node_id, "board")
        try:
            return PlotBoardSpec.model_validate(raw)
        except ValidationError as exc:
            raise self._invalid_plot_data(node_id, "board", exc) from exc

    def _parse_plot_layout(self, raw: Any, *, node_id: str) -> PlotBoardLayout | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise self._invalid_plot_data(node_id, "layout")
        try:
            return PlotBoardLayout.model_validate(raw)
        except ValidationError as exc:
            raise self._invalid_plot_data(node_id, "layout", exc) from exc

    def _default_template(
        self, entry_type: str, value: PlotTemplateSpec | None
    ) -> PlotTemplateSpec | None:
        if value is not None:
            return value
        return (
            PlotTemplateSpec()
            if self._plot_data_family(entry_type) == "template"
            else None
        )

    def _default_template_instance(
        self, entry_type: str, value: PlotTemplateInstanceSpec | None
    ) -> PlotTemplateInstanceSpec | None:
        if value is not None:
            return value
        return (
            PlotTemplateInstanceSpec()
            if self._plot_data_family(entry_type) == "template_instance"
            else None
        )

    def _default_board(
        self, entry_type: str, value: PlotBoardSpec | None
    ) -> PlotBoardSpec | None:
        if value is not None:
            return value
        return (
            PlotBoardSpec() if self._plot_data_family(entry_type) == "board" else None
        )

    def _plot_context_template_instances(
        self, claims: list[PlotContextClaim]
    ) -> list[PlotContextTemplateInstance]:
        point_ids_by_instance: dict[str, set[str]] = {}
        for claim in claims:
            point_ids_by_instance.setdefault(claim.template_instance_id, set()).add(
                claim.plot_point_id
            )

        out: list[PlotContextTemplateInstance] = []
        for instance_id, used_point_ids in sorted(point_ids_by_instance.items()):
            instance = self._plot_context_template_instance(instance_id, used_point_ids)
            if instance is not None:
                out.append(instance)
        return out

    def _plot_context_template_instance(
        self,
        instance_id: str,
        used_point_ids: set[str] | None,
    ) -> PlotContextTemplateInstance | None:
        try:
            instance_node = self.read_plot_node(instance_id)
        except ProjectServiceError:
            return None
        if instance_node.template_instance is None:
            return None
        template_points: dict[str, Any] = {}
        template_spec: PlotTemplateSpec | None = None
        template_id = instance_node.template_instance.template_id
        if template_id:
            try:
                template_node = self.read_plot_node(template_id)
                if template_node.template is not None:
                    template_spec = template_node.template
                    template_points = {
                        point.id: point
                        for point in template_node.template.plot_points
                    }
            except ProjectServiceError:
                template_points = {}

        instance_points = {
            point.plot_point_id: point
            for point in instance_node.template_instance.plot_points
        }
        enabled = set(instance_node.template_instance.enabled_point_ids)
        point_note_ids = set(instance_node.template_instance.point_notes)
        if used_point_ids is None:
            point_ids = enabled or set(template_points) | set(instance_points) | point_note_ids
        else:
            point_ids = used_point_ids

        points: list[PlotContextPoint] = []
        for point_id in self._ordered_plot_point_ids(
            point_ids,
            template_spec,
            instance_node.template_instance,
        ):
            if enabled and point_id not in enabled:
                continue
            base = template_points.get(point_id)
            local = instance_points.get(point_id)
            note = instance_node.template_instance.point_notes.get(point_id)
            points.append(
                PlotContextPoint(
                    plot_point_id=point_id,
                    local_label=(
                        getattr(note, "local_label", "")
                        if note is not None
                        else getattr(local, "local_label", "")
                    ),
                    title=(
                        getattr(local, "title", "")
                        or (
                            getattr(note, "local_label", "")
                            if note is not None
                            else ""
                        )
                        or getattr(base, "title", "")
                        or point_id
                    ),
                    function_claim=(
                        getattr(local, "function_claim", "")
                        or getattr(base, "function_claim", "")
                    ),
                    guidance=getattr(base, "guidance", ""),
                    notes=(
                        getattr(note, "notes", "")
                        if note is not None
                        else getattr(local, "notes", "")
                    ),
                    author_intent=(
                        getattr(note, "author_intent", "")
                        if note is not None
                        else getattr(local, "author_intent", "")
                    ),
                    expected_role=(
                        getattr(note, "expected_role", "")
                        if note is not None
                        else getattr(local, "expected_role", "")
                    ),
                    open_questions=(
                        getattr(note, "open_questions", [])
                        if note is not None
                        else getattr(local, "open_questions", [])
                    ),
                    status=(
                        getattr(note, "status", "unplanned")
                        if note is not None
                        else getattr(local, "status", "unplanned")
                    ),
                )
            )

        return PlotContextTemplateInstance(
            id=instance_node.id,
            title=instance_node.title,
            template_id=template_id,
            template_slug=getattr(template_spec, "slug", "")
            if template_spec is not None
            else "",
            template_family=getattr(template_spec, "family", "custom")
            if template_spec is not None
            else "custom",
            template_description=getattr(template_spec, "description", "")
            if template_spec is not None
            else "",
            ai_use_guidance=getattr(template_spec, "ai_use_guidance", "")
            if template_spec is not None
            else "",
            global_diagnostic_questions=(
                getattr(template_spec, "global_diagnostic_questions", [])
                if template_spec is not None
                else []
            ),
            plot_points=points,
        )

    @staticmethod
    def _ordered_plot_point_ids(
        point_ids: set[str],
        template_spec: PlotTemplateSpec | None,
        template_instance: Any,
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def add(point_id: Any) -> None:
            if not isinstance(point_id, str) or point_id not in point_ids or point_id in seen:
                return
            ordered.append(point_id)
            seen.add(point_id)

        if template_spec is not None:
            for point in template_spec.plot_points:
                add(getattr(point, "id", None))

        for point in getattr(template_instance, "plot_points", None) or []:
            add(getattr(point, "plot_point_id", None))
        for point_id in getattr(template_instance, "point_notes", {}) or {}:
            add(point_id)
        for point_id in sorted(point_ids - seen):
            add(point_id)

        return ordered

    @staticmethod
    def _plot_scene_order(root: Any) -> tuple[dict[str, int], dict[str, Any]]:
        scene_order: dict[str, int] = {}
        structure_nodes: dict[str, Any] = {}

        def walk(node: Any) -> None:
            node_id = getattr(node, "id", None)
            if isinstance(node_id, str) and node_id:
                structure_nodes[node_id] = node
            node_scene_id = getattr(node, "scene_id", None)
            if isinstance(node_scene_id, str) and node_scene_id:
                if node_scene_id not in scene_order:
                    scene_order[node_scene_id] = len(scene_order)
                structure_nodes.setdefault(node_scene_id, node)
            for child in getattr(node, "children", None) or []:
                walk(child)

        walk(root)
        return scene_order, structure_nodes

    @staticmethod
    def _plot_card_scene(
        card: Any,
        scene_order: dict[str, int],
        structure_nodes: dict[str, Any],
    ) -> tuple[str | None, Any]:
        node_ref = getattr(card, "node_ref", None)
        if isinstance(node_ref, str) and node_ref:
            if node_ref in scene_order:
                return node_ref, structure_nodes.get(node_ref)
            structure_node = structure_nodes.get(node_ref)
            if structure_node is not None:
                scene_id = getattr(structure_node, "scene_id", None)
                return scene_id if isinstance(scene_id, str) else None, structure_node
        return None, None

    @staticmethod
    def _builtin_plot_templates() -> list[dict[str, Any]]:
        from app.services.project.plot_builtin_templates import builtin_plot_templates

        return builtin_plot_templates()
