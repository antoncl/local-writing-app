from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    CreateProjectRequest,
    CreateSceneRequest,
    CreateTodoRequest,
    DirectoryListing,
    OpenProjectRequest,
    ProjectInfo,
    ProjectValidation,
    SaveSceneRequest,
    Scene,
    SearchRequest,
    SearchResponse,
    StructureDocument,
    TodoDocument,
    UpdateTodoRequest,
)
from app.services.project_service import ProjectService, ProjectServiceError


app = FastAPI(title="Local Writing Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = ProjectService()


@contextmanager
def translate_errors():
    try:
        yield
    except ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/project/create", response_model=ProjectInfo)
def create_project(request: CreateProjectRequest) -> ProjectInfo:
    with translate_errors():
        return service.create_project(Path(request.root_path), request.title)


@app.post("/api/project/open", response_model=ProjectInfo)
def open_project(request: OpenProjectRequest) -> ProjectInfo:
    with translate_errors():
        return service.open_project(Path(request.root_path))


@app.get("/api/project", response_model=ProjectInfo)
def get_project() -> ProjectInfo:
    with translate_errors():
        return service.current_project()


@app.get("/api/directories", response_model=DirectoryListing)
def list_directories(path: str | None = Query(default=None)) -> DirectoryListing:
    with translate_errors():
        return service.list_directories(Path(path) if path else None)


@app.post("/api/project/validate", response_model=ProjectValidation)
def validate_project() -> ProjectValidation:
    with translate_errors():
        return service.validate_project()


@app.post("/api/project/repair", response_model=ProjectValidation)
def repair_project() -> ProjectValidation:
    with translate_errors():
        return service.repair_project()


@app.get("/api/structure", response_model=StructureDocument)
def get_structure() -> StructureDocument:
    with translate_errors():
        return service.read_structure()


@app.post("/api/scenes", response_model=Scene)
def create_scene(request: CreateSceneRequest) -> Scene:
    with translate_errors():
        return service.create_scene(request)


@app.get("/api/scenes/{scene_id}", response_model=Scene)
def get_scene(scene_id: str) -> Scene:
    with translate_errors():
        return service.read_scene(scene_id)


@app.put("/api/scenes/{scene_id}", response_model=Scene)
def save_scene(scene_id: str, request: SaveSceneRequest) -> Scene:
    with translate_errors():
        return service.save_scene(scene_id, request)


@app.delete("/api/scenes/{scene_id}", response_model=StructureDocument)
def delete_scene(scene_id: str) -> StructureDocument:
    with translate_errors():
        return service.delete_scene(scene_id)


@app.get("/api/todos", response_model=TodoDocument)
def get_todos() -> TodoDocument:
    with translate_errors():
        return service.read_todos()


@app.post("/api/todos", response_model=TodoDocument)
def create_todo(request: CreateTodoRequest) -> TodoDocument:
    with translate_errors():
        return service.create_todo(request)


@app.patch("/api/todos/{todo_id}", response_model=TodoDocument)
def update_todo(todo_id: str, request: UpdateTodoRequest) -> TodoDocument:
    with translate_errors():
        return service.update_todo(todo_id, request)


@app.delete("/api/todos/{todo_id}", response_model=TodoDocument)
def delete_todo(todo_id: str) -> TodoDocument:
    with translate_errors():
        return service.delete_todo(todo_id)


@app.post("/api/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    with translate_errors():
        return service.search(request)
