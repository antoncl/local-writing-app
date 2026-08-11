"""Plot-planning routes (ADR-0048 S4a/S4b/S5a/S7-Slice2): plotlines, cards, the
board singleton, templates, and template instances.

The board, plotlines, cards, templates, and instances are distinct sub-resources
(`/api/plot/board`, `/api/plot/plotlines/...`, `/api/plot/cards/...`,
`/api/plot/templates/...`, `/api/plot/instances/...`) so no entry id can shadow
another route.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CardEntry,
    CardList,
    CreateCardRequest,
    CreatePlotlineRequest,
    CreateTemplateInstanceRequest,
    PlotBoard,
    PlotBoardProjection,
    PlotContext,
    PlotlineEntry,
    PlotlineList,
    PlotTemplate,
    PlotTemplateList,
    RealizeCardRequest,
    SaveCardRequest,
    SavePlotBoardRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
    SaveTemplateInstanceRequest,
    TemplateInstanceEntry,
    TemplateInstanceList,
)
from app.runtime import CurrentProject, translate_errors

router = APIRouter()


@router.get("/api/plot/board", response_model=PlotBoard)
def get_plot_board(project: CurrentProject) -> PlotBoard:
    """Open the plot board, creating it on first open (ADR-0048 §3)."""
    with translate_errors():
        return project.read_plot_board()


@router.put("/api/plot/board", response_model=PlotBoard)
def save_plot_board(project: CurrentProject, request: SavePlotBoardRequest) -> PlotBoard:
    with translate_errors():
        return project.save_plot_board(request)


@router.get("/api/plot/board/projection", response_model=PlotBoardProjection)
def get_plot_board_projection(project: CurrentProject) -> PlotBoardProjection:
    """The board's render model — plotlines + cards (with their refs) + the
    opaque layout, in one read (ADR-0048 S7a)."""
    with translate_errors():
        return project.read_plot_board_projection()


@router.get("/api/plot/board/context", response_model=PlotContext)
def get_plot_context(project: CurrentProject, as_of: str | None = None) -> PlotContext:
    """What the AI sees to reason about the plot (ADR-0048 S8a): the board's plot
    state — plotlines, arcs with full beat rosters, and cards with synopses / beat
    links / causal edges — spoiler-gated by manuscript reveal order.

    `as_of` (a card or scene id) anchors the gate: cards up to and including its
    reveal position are shown, later cards are withheld and only counted. Omit it
    for the whole board. This is the "what the AI sees" preview; the same read
    feeds Slice 8b's card brainstorm as prompt context."""
    with translate_errors():
        return project.read_plot_context(as_of)


@router.get("/api/plot/plotlines", response_model=PlotlineList)
def list_plotlines(project: CurrentProject) -> PlotlineList:
    with translate_errors():
        return project.list_plotlines()


@router.post("/api/plot/plotlines", response_model=PlotlineEntry)
def create_plotline(project: CurrentProject, request: CreatePlotlineRequest) -> PlotlineEntry:
    with translate_errors():
        return project.create_plotline(request)


@router.get("/api/plot/plotlines/{entry_id}", response_model=PlotlineEntry)
def get_plotline(project: CurrentProject, entry_id: str) -> PlotlineEntry:
    with translate_errors():
        return project.read_plotline(entry_id)


@router.put("/api/plot/plotlines/{entry_id}", response_model=PlotlineEntry)
def save_plotline(project: CurrentProject, entry_id: str, request: SavePlotlineRequest) -> PlotlineEntry:
    with translate_errors():
        return project.save_plotline(entry_id, request)


@router.delete("/api/plot/plotlines/{entry_id}", response_model=PlotlineList)
def delete_plotline(project: CurrentProject, entry_id: str) -> PlotlineList:
    with translate_errors():
        return project.delete_plotline(entry_id)


@router.get("/api/plot/cards", response_model=CardList)
def list_cards(project: CurrentProject) -> CardList:
    with translate_errors():
        return project.list_cards()


@router.post("/api/plot/cards", response_model=CardEntry)
def create_card(project: CurrentProject, request: CreateCardRequest) -> CardEntry:
    with translate_errors():
        return project.create_card(request)


@router.get("/api/plot/cards/{entry_id}", response_model=CardEntry)
def get_card(project: CurrentProject, entry_id: str) -> CardEntry:
    with translate_errors():
        return project.read_card(entry_id)


@router.put("/api/plot/cards/{entry_id}", response_model=CardEntry)
def save_card(project: CurrentProject, entry_id: str, request: SaveCardRequest) -> CardEntry:
    with translate_errors():
        return project.save_card(entry_id, request)


@router.delete("/api/plot/cards/{entry_id}", response_model=CardList)
def delete_card(project: CurrentProject, entry_id: str) -> CardList:
    with translate_errors():
        return project.delete_card(entry_id)


@router.post("/api/plot/cards/{entry_id}/realize", response_model=CardEntry)
def realize_card(project: CurrentProject, entry_id: str, request: RealizeCardRequest) -> CardEntry:
    """Create a scene from a card and attach it (ADR-0048 §1, *realize*)."""
    with translate_errors():
        return project.realize_card(entry_id, request)


@router.post("/api/plot/seed-from-manuscript", response_model=CardList)
def seed_cards_from_manuscript(project: CurrentProject) -> CardList:
    """Create one attached card per scene that has none (ADR-0048 §1/§S5)."""
    with translate_errors():
        return project.seed_cards_from_manuscript()


@router.get("/api/plot/templates", response_model=PlotTemplateList)
def list_plot_templates(project: CurrentProject) -> PlotTemplateList:
    with translate_errors():
        return project.list_plot_templates()


@router.get("/api/plot/templates/{entry_id}", response_model=PlotTemplate)
def get_plot_template(project: CurrentProject, entry_id: str) -> PlotTemplate:
    with translate_errors():
        return project.read_plot_template(entry_id)


@router.post("/api/plot/templates/{entry_id}/fork", response_model=PlotTemplate)
def fork_plot_template(project: CurrentProject, entry_id: str) -> PlotTemplate:
    """Clone an inherited Library / ancestor template into this project (ADR-0049 §5)."""
    with translate_errors():
        return project.fork_plot_template(entry_id)


@router.post("/api/plot/templates/{entry_id}/instantiate", response_model=TemplateInstanceEntry)
def instantiate_plot_template(project: CurrentProject, entry_id: str) -> TemplateInstanceEntry:
    """Apply a template to this book — snapshot its beats into a new, book-local,
    specializable instance (ADR-0048 §3)."""
    with translate_errors():
        return project.instantiate_plot_template(entry_id)


@router.put("/api/plot/templates/{entry_id}", response_model=PlotTemplate)
def save_plot_template(project: CurrentProject, entry_id: str, request: SavePlotTemplateRequest) -> PlotTemplate:
    with translate_errors():
        return project.save_plot_template(entry_id, request)


@router.delete("/api/plot/templates/{entry_id}", response_model=PlotTemplateList)
def delete_plot_template(project: CurrentProject, entry_id: str) -> PlotTemplateList:
    with translate_errors():
        return project.delete_plot_template(entry_id)


@router.get("/api/plot/instances", response_model=TemplateInstanceList)
def list_template_instances(project: CurrentProject) -> TemplateInstanceList:
    with translate_errors():
        return project.list_template_instances()


@router.post("/api/plot/instances", response_model=TemplateInstanceEntry)
def create_template_instance(project: CurrentProject, request: CreateTemplateInstanceRequest) -> TemplateInstanceEntry:
    """Create an ad-hoc instance — a plot with no template behind it (ADR-0048 §3)."""
    with translate_errors():
        return project.create_template_instance(request)


@router.get("/api/plot/instances/{entry_id}", response_model=TemplateInstanceEntry)
def get_template_instance(project: CurrentProject, entry_id: str) -> TemplateInstanceEntry:
    with translate_errors():
        return project.read_template_instance(entry_id)


@router.put("/api/plot/instances/{entry_id}", response_model=TemplateInstanceEntry)
def save_template_instance(
    project: CurrentProject, entry_id: str, request: SaveTemplateInstanceRequest
) -> TemplateInstanceEntry:
    with translate_errors():
        return project.save_template_instance(entry_id, request)


@router.delete("/api/plot/instances/{entry_id}", response_model=TemplateInstanceList)
def delete_template_instance(project: CurrentProject, entry_id: str) -> TemplateInstanceList:
    with translate_errors():
        return project.delete_template_instance(entry_id)
