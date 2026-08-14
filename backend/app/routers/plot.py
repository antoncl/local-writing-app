"""Plot-planning routes (ADR-0048 S4a/S4b/S5a/S7-Slice2; ADR-0053): plotlines,
cards, the board singleton, and templates.

The board, plotlines, cards, and templates are distinct sub-resources
(`/api/plot/board`, `/api/plot/plotlines/...`, `/api/plot/cards/...`,
`/api/plot/templates/...`) so no entry id can shadow another route. A plotline is
a plot-template instance (ADR-0053 §1): instantiating a template mints one, and an
ad-hoc plotline is just a plotline created with no beats — there is no separate
`/instances` resource.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CardEntry,
    CardList,
    CreateCardRequest,
    CreatePlotlineRequest,
    CreatePlotTemplateRequest,
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


@router.post("/api/plot/templates", response_model=PlotTemplate)
def create_plot_template(project: CurrentProject, request: CreatePlotTemplateRequest) -> PlotTemplate:
    """Blank-create an owned `plot:template` (the non-fork path, #918)."""
    with translate_errors():
        return project.create_plot_template(request)


@router.get("/api/plot/templates/{entry_id}", response_model=PlotTemplate)
def get_plot_template(project: CurrentProject, entry_id: str) -> PlotTemplate:
    with translate_errors():
        return project.read_plot_template(entry_id)


@router.post("/api/plot/templates/{entry_id}/fork", response_model=PlotTemplate)
def fork_plot_template(project: CurrentProject, entry_id: str) -> PlotTemplate:
    """Clone an inherited Library / ancestor template into this project (ADR-0049 §5)."""
    with translate_errors():
        return project.fork_plot_template(entry_id)


@router.post("/api/plot/templates/{entry_id}/instantiate", response_model=PlotlineEntry)
def instantiate_plot_template(project: CurrentProject, entry_id: str) -> PlotlineEntry:
    """Apply a template to this book — snapshot its beats into a new, book-local,
    specializable plotline (ADR-0048 §3; ADR-0053 §2)."""
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
