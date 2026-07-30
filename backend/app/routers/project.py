"""Project, structure, and research-structure routes (#170 main.py split)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from app.models import (
    AncestorCandidate,
    ClientErrorReport,
    CreateDirectoryRequest,
    CreateProjectRequest,
    CreateStructureNodeRequest,
    DirectoryEntry,
    DirectoryListing,
    DirectoryRoot,
    ImportLooseScenesRequest,
    LooseScene,
    MoveStructureNodeRequest,
    OpenProjectRequest,
    PathProbe,
    ProjectInfo,
    ProjectNode,
    ProjectValidation,
    ProspectiveProjectNode,
    ProspectiveProjectNodeRequest,
    RenameStructureNodeRequest,
    ResearchNote,
    SaveProjectNodeRequest,
    SaveResearchNoteRequest,
    StructureDocument,
    StructureNodeDeletePreview,
    UpdateProjectSettingsRequest,
)
from app.runtime import CurrentProject, translate_errors
from app.services.project.node_index_gate import node_index_gate
from app.services.project_service import ProjectService

router = APIRouter()


@router.post("/api/log", status_code=204)
def log_client_error(project: CurrentProject, report: ClientErrorReport) -> None:
    """Append a browser-reported runtime error to the open project's log (#386).

    Fire-and-forget from the UI's side: recording swallows its own write errors,
    so this never fails the operation the client was reporting on.
    """
    project.record_client_error(report)


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# The two routes below are the only ones that do NOT take `CurrentProject`:
# they are where a scope comes *from* — the client passes an explicit
# `root_path`, does not yet know it as a project, and this is what makes it one.
# Since #413 the wire carries the open project's root on every *subsequent*
# request, so these no longer record what is open; they keep their real jobs
# (migrate, validate, touch recents) and drop the node-index memo, which is the
# open event ADR-0040/#392 hang the memo's lifetime on. Dropping it here (not in
# the per-request resolver, which builds a throwaway service every call) is what
# makes a re-open after an external backup-restore rebuild from disk rather than
# serve the pre-restore index — the browser's F5 re-runs `/open`, no server
# restart needed.

@router.post("/api/project/create", response_model=ProjectInfo)
def create_project(request: CreateProjectRequest) -> ProjectInfo:
    from app.services import machine_settings as ms_service

    with translate_errors():
        created = ProjectService.created_at(
            Path(request.root_path), request.title, request.inherits
        )
        info = created.current_project()
        node_index_gate.invalidate()
        ms_service.touch_recent_project(Path(info.root_path), info.title)
        return info


@router.post("/api/project/open", response_model=ProjectInfo)
def open_project(request: OpenProjectRequest) -> ProjectInfo:
    from app.services import machine_settings as ms_service

    with translate_errors():
        opened = ProjectService.opened_at(Path(request.root_path))
        info = opened.current_project()
        node_index_gate.invalidate()
        ms_service.touch_recent_project(Path(info.root_path), info.title)
        return info


@router.get("/api/project", response_model=ProjectInfo)
def get_project(project: CurrentProject) -> ProjectInfo:
    with translate_errors():
        return project.current_project()


@router.get("/api/project/node", response_model=ProjectNode)
def get_project_node(project: CurrentProject) -> ProjectNode:
    with translate_errors():
        return project.read_project_node()


@router.put("/api/project/node", response_model=ProjectNode)
def save_project_node(project: CurrentProject, request: SaveProjectNodeRequest) -> ProjectNode:
    with translate_errors():
        return project.save_project_node(request)


@router.patch("/api/project/settings", response_model=ProjectInfo)
def update_project_settings(project: CurrentProject, request: UpdateProjectSettingsRequest) -> ProjectInfo:
    with translate_errors():
        return project.update_project_settings(request)


@router.get("/api/directories", response_model=DirectoryListing)
def list_directories(project: CurrentProject, path: str | None = Query(default=None)) -> DirectoryListing:
    with translate_errors():
        return project.list_directories(Path(path) if path else None)


# Pure-filesystem picker helpers (#530): jump-off roots, a non-throwing probe
# for the typed-path field, and inline folder creation. Distinct paths from the
# listing above, so declaration order is immaterial.
@router.get("/api/directories/roots", response_model=list[DirectoryRoot])
def list_directory_roots(project: CurrentProject) -> list[DirectoryRoot]:
    with translate_errors():
        return project.list_directory_roots()


@router.get("/api/directories/probe", response_model=PathProbe)
def probe_directory(project: CurrentProject, path: str = Query(default="")) -> PathProbe:
    with translate_errors():
        return project.probe_path(path)


@router.post("/api/directories", response_model=DirectoryEntry)
def create_directory(project: CurrentProject, request: CreateDirectoryRequest) -> DirectoryEntry:
    with translate_errors():
        return project.create_directory(Path(request.parent), request.name)


# The wizard's location step (#318) asks which ancestors a project *would*
# inherit from before it exists. Like the picker helpers above it is a
# path-based read that touches no project state — `prospective_ancestor_candidates`
# uses only the passed path, so an absent scope (first run, nothing open) is
# fine and no scope is produced. Every row returns `inherited=False`.
@router.get("/api/project/ancestor-candidates", response_model=list[AncestorCandidate])
def project_ancestor_candidates(
    project: CurrentProject, path: str = Query(min_length=1)
) -> list[AncestorCandidate]:
    with translate_errors():
        return project.prospective_ancestor_candidates(Path(path))


# The wizard's review step (#318 slice 4) resolves the project node's authored
# fields — merged schema, inherited values, and per-field source — over the
# ticked ancestors *before* the project exists. POST because it carries the
# declaration list. Like the candidates route it is a path-based read touching
# no project state, so an absent scope (first run) is fine.
@router.post("/api/project/prospective-node", response_model=ProspectiveProjectNode)
def prospective_project_node(
    project: CurrentProject, request: ProspectiveProjectNodeRequest
) -> ProspectiveProjectNode:
    with translate_errors():
        return project.prospective_project_node(Path(request.root_path), request.inherits)


@router.post("/api/project/validate", response_model=ProjectValidation)
def validate_project(project: CurrentProject) -> ProjectValidation:
    with translate_errors():
        return project.validate_project()


@router.post("/api/project/repair", response_model=ProjectValidation)
def repair_project(project: CurrentProject) -> ProjectValidation:
    with translate_errors():
        return project.repair_project()


@router.get("/api/structure", response_model=StructureDocument)
def get_structure(project: CurrentProject) -> StructureDocument:
    with translate_errors():
        return project.read_structure()


@router.post("/api/structure/nodes", response_model=StructureDocument)
def create_structure_node(project: CurrentProject, request: CreateStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return project.create_structure_node(request)


@router.get("/api/structure/loose-scenes", response_model=list[LooseScene])
def list_loose_scenes(project: CurrentProject) -> list[LooseScene]:
    # Scene files on disk that no manuscript node references — the import offer,
    # split off the validation report (#635). A read: forces a cold rebuild so
    # freshly-dropped files show, but touches no project state.
    with translate_errors():
        return project.list_loose_scenes()


@router.post("/api/structure/import-loose", response_model=StructureDocument)
def import_loose_scenes(project: CurrentProject, request: ImportLooseScenesRequest) -> StructureDocument:
    with translate_errors():
        return project.import_loose_scenes(request.scene_ids)


@router.patch("/api/structure/nodes/{node_id}", response_model=StructureDocument)
def rename_structure_node(project: CurrentProject, node_id: str, request: RenameStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return project.rename_structure_node(node_id, request.title)


@router.post("/api/structure/nodes/{node_id}/move", response_model=StructureDocument)
def move_structure_node(project: CurrentProject, node_id: str, request: MoveStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return project.move_structure_node(node_id, request.target_parent_id, request.position)


@router.get("/api/structure/nodes/{node_id}/cascade-preview", response_model=StructureNodeDeletePreview)
def cascade_delete_preview(project: CurrentProject, node_id: str) -> StructureNodeDeletePreview:
    with translate_errors():
        return project.cascade_delete_preview(node_id)


@router.delete("/api/structure/nodes/{node_id}", response_model=StructureDocument)
def delete_structure_node(project: CurrentProject, node_id: str) -> StructureDocument:
    with translate_errors():
        return project.delete_structure_node(node_id)


# ----- Research structure -----
#
# Mirrors /api/structure for the research tree (docs/research-strategy.md
# slice 1). Same request/response shapes; the routes share the
# manuscript-structure request models because the tree CRUD vocabulary
# (title, entry_type, parent_id, target_parent_id, position) is identical.

@router.get("/api/research-structure", response_model=StructureDocument)
def get_research_structure(project: CurrentProject) -> StructureDocument:
    with translate_errors():
        return project.read_research_structure()


@router.post("/api/research-structure/nodes", response_model=StructureDocument)
def create_research_node(project: CurrentProject, request: CreateStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return project.create_research_node(request)


@router.patch("/api/research-structure/nodes/{node_id}", response_model=StructureDocument)
def rename_research_node(project: CurrentProject, node_id: str, request: RenameStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return project.rename_research_node(node_id, request.title)


@router.post("/api/research-structure/nodes/{node_id}/move", response_model=StructureDocument)
def move_research_node(project: CurrentProject, node_id: str, request: MoveStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return project.move_research_node(node_id, request.target_parent_id, request.position)


@router.get(
    "/api/research-structure/nodes/{node_id}/cascade-preview",
    response_model=StructureNodeDeletePreview,
)
def cascade_research_delete_preview(project: CurrentProject, node_id: str) -> StructureNodeDeletePreview:
    with translate_errors():
        return project.cascade_research_delete_preview(node_id)


@router.delete("/api/research-structure/nodes/{node_id}", response_model=StructureDocument)
def delete_research_node(project: CurrentProject, node_id: str) -> StructureDocument:
    with translate_errors():
        return project.delete_research_node(node_id)


@router.get("/api/research/notes/{note_id}", response_model=ResearchNote)
def get_research_note(project: CurrentProject, note_id: str) -> ResearchNote:
    with translate_errors():
        return project.read_research_note(note_id)


@router.put("/api/research/notes/{note_id}", response_model=ResearchNote)
def put_research_note(project: CurrentProject, note_id: str, request: SaveResearchNoteRequest) -> ResearchNote:
    with translate_errors():
        return project.save_research_note(note_id, request)


