"""Project, structure, and research-structure routes (#170 main.py split)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from app.models import (
    CreateProjectRequest,
    CreateStructureNodeRequest,
    DirectoryListing,
    MoveStructureNodeRequest,
    OpenProjectRequest,
    ProjectInfo,
    ProjectNode,
    ProjectValidation,
    RenameStructureNodeRequest,
    ResearchNote,
    SaveProjectNodeRequest,
    SaveResearchNoteRequest,
    StructureDocument,
    StructureNodeDeletePreview,
    UpdateProjectSettingsRequest,
)
from app.runtime import service, translate_errors

router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/project/create", response_model=ProjectInfo)
def create_project(request: CreateProjectRequest) -> ProjectInfo:
    from app.services import machine_settings as ms_service

    with translate_errors():
        info = service.create_project(
            Path(request.root_path),
            request.title,
            Path(request.projects_base_folder) if request.projects_base_folder else None,
        )
        ms_service.touch_recent_project(Path(info.root_path), info.title)
        return info


@router.post("/api/project/open", response_model=ProjectInfo)
def open_project(request: OpenProjectRequest) -> ProjectInfo:
    from app.services import machine_settings as ms_service

    with translate_errors():
        info = service.open_project(
            Path(request.root_path),
            Path(request.projects_base_folder) if request.projects_base_folder else None,
        )
        ms_service.touch_recent_project(Path(info.root_path), info.title)
        return info


@router.get("/api/project", response_model=ProjectInfo)
def get_project() -> ProjectInfo:
    with translate_errors():
        return service.current_project()


@router.get("/api/project/node", response_model=ProjectNode)
def get_project_node() -> ProjectNode:
    with translate_errors():
        return service.read_project_node()


@router.put("/api/project/node", response_model=ProjectNode)
def save_project_node(request: SaveProjectNodeRequest) -> ProjectNode:
    with translate_errors():
        return service.save_project_node(request)


@router.patch("/api/project/settings", response_model=ProjectInfo)
def update_project_settings(request: UpdateProjectSettingsRequest) -> ProjectInfo:
    with translate_errors():
        return service.update_project_settings(request)


@router.get("/api/directories", response_model=DirectoryListing)
def list_directories(path: str | None = Query(default=None)) -> DirectoryListing:
    with translate_errors():
        return service.list_directories(Path(path) if path else None)


@router.post("/api/project/validate", response_model=ProjectValidation)
def validate_project() -> ProjectValidation:
    with translate_errors():
        return service.validate_project()


@router.post("/api/project/repair", response_model=ProjectValidation)
def repair_project() -> ProjectValidation:
    with translate_errors():
        return service.repair_project()


@router.get("/api/structure", response_model=StructureDocument)
def get_structure() -> StructureDocument:
    with translate_errors():
        return service.read_structure()


@router.post("/api/structure/nodes", response_model=StructureDocument)
def create_structure_node(request: CreateStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return service.create_structure_node(request)


@router.patch("/api/structure/nodes/{node_id}", response_model=StructureDocument)
def rename_structure_node(node_id: str, request: RenameStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return service.rename_structure_node(node_id, request.title)


@router.post("/api/structure/nodes/{node_id}/move", response_model=StructureDocument)
def move_structure_node(node_id: str, request: MoveStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return service.move_structure_node(node_id, request.target_parent_id, request.position)


@router.get("/api/structure/nodes/{node_id}/cascade-preview", response_model=StructureNodeDeletePreview)
def cascade_delete_preview(node_id: str) -> StructureNodeDeletePreview:
    with translate_errors():
        return service.cascade_delete_preview(node_id)


@router.delete("/api/structure/nodes/{node_id}", response_model=StructureDocument)
def delete_structure_node(node_id: str) -> StructureDocument:
    with translate_errors():
        return service.delete_structure_node(node_id)


# ----- Research structure -----
#
# Mirrors /api/structure for the research tree (docs/research-strategy.md
# slice 1). Same request/response shapes; the routes share the
# manuscript-structure request models because the tree CRUD vocabulary
# (title, entry_type, parent_id, target_parent_id, position) is identical.

@router.get("/api/research-structure", response_model=StructureDocument)
def get_research_structure() -> StructureDocument:
    with translate_errors():
        return service.read_research_structure()


@router.post("/api/research-structure/nodes", response_model=StructureDocument)
def create_research_node(request: CreateStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return service.create_research_node(request)


@router.patch("/api/research-structure/nodes/{node_id}", response_model=StructureDocument)
def rename_research_node(
    node_id: str, request: RenameStructureNodeRequest
) -> StructureDocument:
    with translate_errors():
        return service.rename_research_node(node_id, request.title)


@router.post("/api/research-structure/nodes/{node_id}/move", response_model=StructureDocument)
def move_research_node(
    node_id: str, request: MoveStructureNodeRequest
) -> StructureDocument:
    with translate_errors():
        return service.move_research_node(node_id, request.target_parent_id, request.position)


@router.get(
    "/api/research-structure/nodes/{node_id}/cascade-preview",
    response_model=StructureNodeDeletePreview,
)
def cascade_research_delete_preview(node_id: str) -> StructureNodeDeletePreview:
    with translate_errors():
        return service.cascade_research_delete_preview(node_id)


@router.delete("/api/research-structure/nodes/{node_id}", response_model=StructureDocument)
def delete_research_node(node_id: str) -> StructureDocument:
    with translate_errors():
        return service.delete_research_node(node_id)


@router.get("/api/research/notes/{note_id}", response_model=ResearchNote)
def get_research_note(note_id: str) -> ResearchNote:
    with translate_errors():
        return service.read_research_note(note_id)


@router.put("/api/research/notes/{note_id}", response_model=ResearchNote)
def put_research_note(note_id: str, request: SaveResearchNoteRequest) -> ResearchNote:
    with translate_errors():
        return service.save_research_note(note_id, request)


