"""Scene CRUD, embedded-todo, and mutation-marker routes (#170 main.py split)."""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CreateSceneRequest,
    FinalizeSceneRequest,
    RewriteMutationUnitRequest,
    SaveSceneRequest,
    Scene,
    StructureDocument,
    UpdateEmbeddedTodoRequest,
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


@router.post("/api/scenes/{scene_id}/finalize", response_model=Scene)
def finalize_scene(project: CurrentProject, scene_id: str, request: FinalizeSceneRequest) -> Scene:
    """Commit the roleplay finalize/cleanup projection (ADR-0070 S3): snapshot
    the scene (`kept`), then replace its body with the AI-produced clean prose.
    The AI generation itself runs beforehand through the ordinary generate
    endpoint (so the finalize prompt stays author-customizable); this route is
    only the destructive, snapshot-guarded write."""
    with translate_errors():
        return project.finalize_scene(scene_id, request.body, request.dynamic_context)


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


# The one route the in-app editor DOES call outside the prose editor: the lore
# card scrubbed to a stop edits that stop's unit (ADR-0042 §5, ADR-0089 S5),
# and the scene may not be open in any pane.
@router.put("/api/scenes/{scene_id}/mutations/units/{unit_id}", response_model=Scene)
def rewrite_mutation_unit(
    project: CurrentProject, scene_id: str, unit_id: str, request: RewriteMutationUnitRequest
) -> Scene:
    """Replace a mutation unit's rows wholesale (ADR-0089 S5)."""
    with translate_errors():
        return project.rewrite_mutation_unit(scene_id, unit_id, request)


