"""Plot-planning routes (ADR-0048 S4a/S4b/S5a): plotlines, cards, the board
singleton, and templates.

The board, plotlines, cards, and templates are distinct sub-resources
(`/api/plot/board`, `/api/plot/plotlines/...`, `/api/plot/cards/...`,
`/api/plot/templates/...`) so no entry id can shadow another route.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CardEntry,
    CardList,
    CreateCardRequest,
    CreatePlotlineRequest,
    PlotBoard,
    PlotlineEntry,
    PlotlineList,
    PlotTemplate,
    PlotTemplateList,
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


@router.put("/api/plot/templates/{entry_id}", response_model=PlotTemplate)
def save_plot_template(project: CurrentProject, entry_id: str, request: SavePlotTemplateRequest) -> PlotTemplate:
    with translate_errors():
        return project.save_plot_template(entry_id, request)


@router.delete("/api/plot/templates/{entry_id}", response_model=PlotTemplateList)
def delete_plot_template(project: CurrentProject, entry_id: str) -> PlotTemplateList:
    with translate_errors():
        return project.delete_plot_template(entry_id)
