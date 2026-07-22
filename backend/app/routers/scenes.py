"""Scene CRUD, embedded-todo, and mutation-marker routes (#170 main.py split)."""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CreateSceneRequest,
    SaveSceneRequest,
    Scene,
    StructureDocument,
    UpdateEmbeddedTodoRequest,
    UpdateMutationRequest,
)
from app.runtime import CurrentProject, translate_errors

router = APIRouter()


@router.post("/api/scenes", response_model=Scene)
def create_scene(project: CurrentProject, request: CreateSceneRequest) -> Scene:
    with translate_errors():
        return project.create_scene(request)


@router.get("/api/scenes/{scene_id}", response_model=Scene)
def get_scene(project: CurrentProject, scene_id: str) -> Scene:
    with translate_errors():
        return project.read_scene(scene_id)


@router.get("/api/scenes/{scene_id}/effective-names")
def get_scene_effective_names(project: CurrentProject, scene_id: str) -> dict[str, list[str]]:
    """Each lore entry's effective name-set (title + aliases) as of this scene —
    the source for the effective-name-aware implicit-context matcher (#61)."""
    with translate_errors():
        return project.effective_names(scene_id)


@router.put("/api/scenes/{scene_id}", response_model=Scene)
def save_scene(project: CurrentProject, scene_id: str, request: SaveSceneRequest) -> Scene:
    with translate_errors():
        return project.save_scene(scene_id, request)


@router.delete("/api/scenes/{scene_id}", response_model=StructureDocument)
def delete_scene(project: CurrentProject, scene_id: str) -> StructureDocument:
    with translate_errors():
        return project.delete_scene(scene_id)


@router.patch("/api/scenes/{scene_id}/todos/{todo_id}", response_model=Scene)
def update_embedded_todo(
    project: CurrentProject,
    scene_id: str,
    todo_id: str,
    request: UpdateEmbeddedTodoRequest,
) -> Scene:
    """Rewrite a single in-prose embedded-todo marker without a full body save."""
    with translate_errors():
        return project.update_embedded_todo(scene_id, todo_id, request)


@router.delete("/api/scenes/{scene_id}/todos/{todo_id}", response_model=Scene)
def delete_embedded_todo(project: CurrentProject, scene_id: str, todo_id: str) -> Scene:
    """Remove a single in-prose embedded-todo marker, keeping its wrapped text."""
    with translate_errors():
        return project.delete_embedded_todo(scene_id, todo_id)


# The two single-marker mutation routes below are the intentful API mirror of the
# embedded-todo update/delete routes (#54), exercised by the backend tests
# (test_lore_mutation_routes / test_lore_mutations). The in-app editor does NOT
# call them — it rewrites/removes mutation pills directly in the ProseMirror doc
# and saves the whole body — so they're currently only a programmatic/test surface.
# Kept for parity and future non-editor callers; they return the re-read Scene so
# any open pane could reconcile if one ever did use them.
@router.patch("/api/scenes/{scene_id}/mutations/{marker_id}", response_model=Scene)
def update_mutation(project: CurrentProject, scene_id: str, marker_id: str, request: UpdateMutationRequest) -> Scene:
    """Rewrite a single in-prose lore-mutation marker without a full body save (#33)."""
    with translate_errors():
        return project.update_mutation(scene_id, marker_id, request)


@router.delete("/api/scenes/{scene_id}/mutations/{marker_id}", response_model=Scene)
def delete_mutation(project: CurrentProject, scene_id: str, marker_id: str) -> Scene:
    """Remove a single in-prose lore-mutation marker (#33)."""
    with translate_errors():
        return project.delete_mutation(scene_id, marker_id)


