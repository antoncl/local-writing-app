"""Plot-board node models.

The plot feature uses one node kind, `plot`, with three concrete entry types:
`plot:template`, `plot:template_instance`, and `plot:board`. Templates and
template instances may carry prose bodies; structured plot data lives in front
matter so AI/context code can resolve it without scraping prose.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.models.entries import Scene, StructureDocument

PlotClaimType = Literal[
    "satisfies",
    "partially_satisfies",
    "subverts",
    "foreshadows",
    "pays_off",
    "raises_question",
    "rejects",
    "custom",
]

PlotTemplateFamily = Literal[
    "act",
    "journey",
    "cycle",
    "genre",
    "puzzle",
    "relationship",
    "character_arc",
    "custom",
]
PlotTemplatePrescriptiveness = Literal["descriptive", "diagnostic", "prescriptive"]
PlotTemplateIPRisk = Literal["low", "medium", "high", "unknown"]
PlotTemplateBuiltinPolicy = Literal["seed", "seed_generic", "reference_only", "user_authored"]
PlotPointNoteStatus = Literal[
    "unplanned",
    "planned",
    "drafted",
    "satisfied",
    "intentionally_omitted",
]


class SourceRef(BaseModel):
    id: str = Field(min_length=1)
    title: str = ""
    url: str | None = None
    citation: str = ""
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotTemplatePoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    function_claim: str = ""
    guidance: str = ""
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_point_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        if not next_data.get("title") and next_data.get("label"):
            next_data["title"] = next_data["label"]
        if not next_data.get("function_claim"):
            raw_function = next_data.get("function")
            if isinstance(raw_function, dict) and raw_function.get("claim"):
                next_data["function_claim"] = raw_function["claim"]
        return next_data

    @model_validator(mode="after")
    def _backfill_title(self) -> PlotTemplatePoint:
        if not self.title:
            self.title = self.id
        return self


class PlotTemplateSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    slug: str = ""
    display_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    family: PlotTemplateFamily = "custom"
    description: str = ""
    cultural_context: str = ""
    prescriptiveness: PlotTemplatePrescriptiveness = "diagnostic"
    ai_use_guidance: str = ""
    global_diagnostic_questions: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    ip_risk: PlotTemplateIPRisk = "unknown"
    builtin_policy: PlotTemplateBuiltinPolicy = "user_authored"
    template_version: str = ""
    locale: str = ""
    plot_points: list[PlotTemplatePoint] = Field(
        default_factory=list,
        validation_alias=AliasChoices("plot_points", "points", "beats"),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotPointInstanceNote(BaseModel):
    local_label: str = ""
    author_intent: str = ""
    expected_role: str = ""
    open_questions: list[str] = Field(default_factory=list)
    status: PlotPointNoteStatus = "unplanned"
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotTemplateInstancePoint(BaseModel):
    plot_point_id: str = Field(min_length=1)
    title: str = ""
    local_label: str = ""
    function_claim: str = ""
    notes: str = ""
    author_intent: str = ""
    expected_role: str = ""
    open_questions: list[str] = Field(default_factory=list)
    status: PlotPointNoteStatus = "unplanned"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _backfill_note_fields(self) -> PlotTemplateInstancePoint:
        if not self.local_label and self.title:
            self.local_label = self.title
        if not self.title and self.local_label:
            self.title = self.local_label
        return self


class PlotTemplateInstanceSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    template_id: str = Field(
        default="",
        validation_alias=AliasChoices("template_id", "template_ref"),
    )
    title: str = ""
    enabled_point_ids: list[str] = Field(default_factory=list)
    plot_points: list[PlotTemplateInstancePoint] = Field(default_factory=list)
    point_notes: dict[str, PlotPointInstanceNote] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_design_doc_point_notes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        raw_notes = next_data.get("point_notes")
        if "plot_points" not in next_data and isinstance(raw_notes, dict):
            points: list[dict[str, Any]] = []
            for point_id, raw_note in raw_notes.items():
                if not isinstance(point_id, str) or not point_id:
                    continue
                note = dict(raw_note) if isinstance(raw_note, dict) else {}
                points.append(
                    {
                        "plot_point_id": point_id,
                        "title": note.get("local_label") or "",
                        "local_label": note.get("local_label") or "",
                        "notes": note.get("notes") or "",
                        "author_intent": note.get("author_intent") or "",
                        "expected_role": note.get("expected_role") or "",
                        "open_questions": note.get("open_questions") or [],
                        "status": note.get("status") or "unplanned",
                        "metadata": note.get("metadata") or {},
                    }
                )
            next_data["plot_points"] = points
        return next_data

    @model_validator(mode="after")
    def _sync_point_notes(self) -> PlotTemplateInstanceSpec:
        for point in self.plot_points:
            existing = self.point_notes.get(point.plot_point_id)
            if existing is None:
                self.point_notes[point.plot_point_id] = PlotPointInstanceNote(
                    local_label=point.local_label or point.title,
                    notes=point.notes,
                    author_intent=point.author_intent,
                    expected_role=point.expected_role,
                    open_questions=point.open_questions,
                    status=point.status,
                    metadata=point.metadata,
                )
                continue
            if not point.local_label and existing.local_label:
                point.local_label = existing.local_label
            if not point.title and existing.local_label:
                point.title = existing.local_label
            if not point.notes and existing.notes:
                point.notes = existing.notes
            if not point.author_intent and existing.author_intent:
                point.author_intent = existing.author_intent
            if not point.expected_role and existing.expected_role:
                point.expected_role = existing.expected_role
            if not point.open_questions and existing.open_questions:
                point.open_questions = existing.open_questions
            if point.status == "unplanned" and existing.status != "unplanned":
                point.status = existing.status
        return self


class PlotLine(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    template_instance_id: str | None = None
    color: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotBoardCard(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    synopsis: str = ""
    node_ref: str | None = None
    structure_column_id: str | None = None
    primary_plotline_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotPointClaim(BaseModel):
    id: str = Field(min_length=1)
    card_id: str = Field(min_length=1)
    template_instance_id: str = Field(min_length=1)
    plot_point_id: str = Field(min_length=1)
    plotline_id: str | None = None
    claim_type: PlotClaimType = "satisfies"
    claim_label: str | None = None
    strength: Literal["weak", "medium", "strong"] | None = None
    confidence: float | None = None
    evidence: str | None = None
    rationale: str | None = None
    ai_notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotRelationship(BaseModel):
    id: str = Field(min_length=1)
    from_card_id: str = Field(min_length=1)
    to_card_id: str = Field(min_length=1)
    kind: Literal["causes", "blocks", "reveals", "setup_payoff", "echoes", "contrasts", "custom"] = "custom"
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotBoardSpec(BaseModel):
    version: int = 1
    template_instance_ids: list[str] = Field(default_factory=list)
    plotlines: list[PlotLine] = Field(default_factory=list)
    cards: list[PlotBoardCard] = Field(default_factory=list)
    claims: list[PlotPointClaim] = Field(default_factory=list)
    relationships: list[PlotRelationship] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotContextClaimCard(BaseModel):
    id: str
    title: str
    synopsis: str = ""
    scene_id: str | None = None
    structure_node_id: str | None = None
    structure_title: str | None = None
    manuscript_index: int | None = None
    primary_plotline_id: str | None = None
    primary_plotline: PlotLine | None = None


class PlotContextClaim(BaseModel):
    id: str
    card_id: str
    card: PlotContextClaimCard | None = None
    template_instance_id: str
    plot_point_id: str
    plotline_id: str | None = None
    plotline: PlotLine | None = None
    claim_type: PlotClaimType = "satisfies"
    claim_label: str | None = None
    strength: Literal["weak", "medium", "strong"] | None = None
    evidence: str | None = None
    rationale: str | None = None
    ai_notes: str | None = None


class PlotContextCard(BaseModel):
    id: str
    title: str
    synopsis: str = ""
    scene_id: str | None = None
    structure_node_id: str | None = None
    structure_title: str | None = None
    manuscript_index: int | None = None
    primary_plotline_id: str | None = None
    primary_plotline: PlotLine | None = None
    claims: list[PlotContextClaim] = Field(default_factory=list)


class PlotContextPoint(BaseModel):
    plot_point_id: str
    title: str = ""
    local_label: str = ""
    function_claim: str = ""
    guidance: str = ""
    notes: str = ""
    author_intent: str = ""
    expected_role: str = ""
    open_questions: list[str] = Field(default_factory=list)
    status: PlotPointNoteStatus = "unplanned"
    claims: list[PlotContextClaim] = Field(default_factory=list)


class PlotContextTemplateInstance(BaseModel):
    id: str
    title: str
    template_id: str = ""
    template_slug: str = ""
    template_family: PlotTemplateFamily = "custom"
    template_description: str = ""
    ai_use_guidance: str = ""
    global_diagnostic_questions: list[str] = Field(default_factory=list)
    plot_points: list[PlotContextPoint] = Field(default_factory=list)


class PlotContextRelationship(BaseModel):
    id: str
    from_card_id: str
    to_card_id: str
    kind: Literal["causes", "blocks", "reveals", "setup_payoff", "echoes", "contrasts", "custom"] = "custom"
    label: str | None = None


class PlotContextPacket(BaseModel):
    board_id: str
    board_title: str
    scope_scene_id: str | None = None
    include_future: bool = False
    cards: list[PlotContextCard] = Field(default_factory=list)
    claims: list[PlotContextClaim] = Field(default_factory=list)
    template_instances: list[PlotContextTemplateInstance] = Field(default_factory=list)
    plotlines: list[PlotLine] = Field(default_factory=list)
    relationships: list[PlotContextRelationship] = Field(default_factory=list)
    omitted_counts: dict[str, int] = Field(default_factory=dict)


class PlotLayoutNode(BaseModel):
    id: str
    kind: str
    position: dict[str, float] = Field(default_factory=dict)
    cfg: dict[str, Any] = Field(default_factory=dict)


class PlotLayoutEdge(BaseModel):
    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


class PlotViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1


class PlotBoardLayout(BaseModel):
    nodes: list[PlotLayoutNode] = Field(default_factory=list)
    edges: list[PlotLayoutEdge] = Field(default_factory=list)
    viewport: PlotViewport | None = None


class PlotNodeSummary(BaseModel):
    id: str
    title: str
    entry_type: str = "plot:board"
    system: bool = False
    source_layer_id: str = ""
    source_layer_label: str = ""


class PlotNode(BaseModel):
    id: str
    title: str
    revision: str
    entry_type: str = "plot:board"
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    computed_metadata: dict[str, Any] = Field(default_factory=dict)
    template: PlotTemplateSpec | None = None
    template_instance: PlotTemplateInstanceSpec | None = None
    board: PlotBoardSpec | None = None
    layout: PlotBoardLayout | None = None
    system: bool = False
    source_layer_id: str = ""
    source_layer_label: str = ""


class PlotNodeList(BaseModel):
    entries: list[PlotNodeSummary] = Field(default_factory=list)


class CreatePlotNodeRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "plot:board"
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    template: PlotTemplateSpec | None = None
    template_instance: PlotTemplateInstanceSpec | None = None
    board: PlotBoardSpec | None = None
    layout: PlotBoardLayout | None = None


class SavePlotNodeRequest(BaseModel):
    title: str = Field(min_length=1)
    base_revision: str | None = None
    entry_type: str = "plot:board"
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    template: PlotTemplateSpec | None = None
    template_instance: PlotTemplateInstanceSpec | None = None
    board: PlotBoardSpec | None = None
    layout: PlotBoardLayout | None = None


class PromotePlotCardRequest(BaseModel):
    card_id: str = Field(min_length=1)
    title: str | None = None
    parent_id: str | None = None
    base_revision: str | None = None


class PromotePlotCardResponse(BaseModel):
    plot: PlotNode
    scene: Scene
    structure: StructureDocument
