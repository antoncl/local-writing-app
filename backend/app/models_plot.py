"""Plot-board node models.

The plot feature uses one node kind, `plot`, with three concrete entry types:
`plot:template`, `plot:template_instance`, and `plot:board`. Templates and
template instances may carry prose bodies; structured plot data lives in front
matter so AI/context code can resolve it without scraping prose.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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


class PlotTemplatePoint(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    function_claim: str = ""
    description: str = ""
    guidance: str = ""
    required: bool = True
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotTemplateSpec(BaseModel):
    version: int = 1
    plot_points: list[PlotTemplatePoint] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotTemplateInstancePoint(BaseModel):
    plot_point_id: str = Field(min_length=1)
    title: str = ""
    function_claim: str = ""
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotTemplateInstanceSpec(BaseModel):
    template_id: str = ""
    plot_points: list[PlotTemplateInstancePoint] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
