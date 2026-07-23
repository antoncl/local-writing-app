"""Lore, prompt, and mutation-set entry routes (#170 main.py split)."""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    CreateLoreEntryRequest,
    CreateMutationSetEntryRequest,
    CreatePromptEntryRequest,
    EffectiveStateResponse,
    LoreEntry,
    LoreEntryList,
    MoveLoreNoteToResearchResponse,
    MutationMarkerList,
    MutationSetEntry,
    MutationSetEntryList,
    PromptEntry,
    PromptEntryList,
    SaveLoreEntryRequest,
    SaveMutationSetEntryRequest,
    SavePromptEntryRequest,
)
from app.runtime import CurrentProject, translate_errors

router = APIRouter()


@router.get("/api/lore", response_model=LoreEntryList)
def list_lore_entries(project: CurrentProject) -> LoreEntryList:
    with translate_errors():
        return project.list_lore_entries()


@router.post("/api/lore", response_model=LoreEntry)
def create_lore_entry(project: CurrentProject, request: CreateLoreEntryRequest) -> LoreEntry:
    with translate_errors():
        return project.create_lore_entry(request)


@router.get("/api/lore/{entry_id}", response_model=LoreEntry)
def get_lore_entry(project: CurrentProject, entry_id: str) -> LoreEntry:
    with translate_errors():
        return project.read_lore_entry(entry_id)


@router.get("/api/lore/{entity_id}/mutations", response_model=MutationMarkerList)
def list_entity_mutations(project: CurrentProject, entity_id: str) -> MutationMarkerList:
    """Manuscript-ordered mutation timeline for a lore entity (#33)."""
    with translate_errors():
        return project.entity_mutations(entity_id)


@router.get("/api/lore/{entity_id}/live-mutations", response_model=MutationMarkerList)
def list_live_entity_mutations(project: CurrentProject, entity_id: str, scene: str, pos: int | None = None) -> MutationMarkerList:
    """The entity's start records still open (live, not yet closed) at (scene,
    position) — the source for the `/mutate close` picker (#59)."""
    with translate_errors():
        return project.live_mutations(entity_id, scene, pos)


@router.get("/api/lore/{entity_id}/effective", response_model=EffectiveStateResponse)
def get_entity_effective_state(
    project: CurrentProject,
    entity_id: str,
    scene: str,
    pos: int | None = None,
    exclude: str = "",
) -> EffectiveStateResponse:
    """Effective mutation overrides for a lore entity as of (scene, position) —
    drives the lore-card time-slider (#33). `exclude` (comma-separated record
    ids) skips those records: the list-edit authoring baseline when re-editing
    a unit (#71, ADR-0017)."""
    with translate_errors():
        excluded = {part.strip() for part in exclude.split(",") if part.strip()}
        values = project.effective_state(entity_id, scene, pos, exclude=excluded)
        return EffectiveStateResponse(
            entity_id=entity_id, scene_id=scene, position=pos, values=values
        )


@router.put("/api/lore/{entry_id}", response_model=LoreEntry)
def save_lore_entry(project: CurrentProject, entry_id: str, request: SaveLoreEntryRequest) -> LoreEntry:
    with translate_errors():
        return project.save_lore_entry(entry_id, request)


@router.delete("/api/lore/{entry_id}", response_model=LoreEntryList)
def delete_lore_entry(project: CurrentProject, entry_id: str) -> LoreEntryList:
    with translate_errors():
        return project.delete_lore_entry(entry_id)


@router.post(
    "/api/lore/{entry_id}/move-to-research",
    response_model=MoveLoreNoteToResearchResponse,
)
def move_lore_note_to_research(project: CurrentProject, entry_id: str) -> MoveLoreNoteToResearchResponse:
    """Convert a lore_note to a research/note (slice 5 of
    docs/research-strategy.md). Returns the new note id, updated
    research tree, dropped metadata field ids (aliases / related_entries
    / context_policy are intentional v1 data loss), and refreshed lore
    list so callers update both panes in one round-trip."""
    with translate_errors():
        return project.move_lore_note_to_research(entry_id)


@router.get("/api/prompts", response_model=PromptEntryList)
def list_prompt_entries(project: CurrentProject) -> PromptEntryList:
    with translate_errors():
        return project.list_prompt_entries()


@router.post("/api/prompts", response_model=PromptEntry)
def create_prompt_entry(project: CurrentProject, request: CreatePromptEntryRequest) -> PromptEntry:
    with translate_errors():
        return project.create_prompt_entry(request)


@router.get("/api/prompts/{entry_id}", response_model=PromptEntry)
def get_prompt_entry(project: CurrentProject, entry_id: str) -> PromptEntry:
    with translate_errors():
        return project.read_prompt_entry(entry_id)


@router.put("/api/prompts/{entry_id}", response_model=PromptEntry)
def save_prompt_entry(project: CurrentProject, entry_id: str, request: SavePromptEntryRequest) -> PromptEntry:
    with translate_errors():
        return project.save_prompt_entry(entry_id, request)


@router.delete("/api/prompts/{entry_id}", response_model=PromptEntryList)
def delete_prompt_entry(project: CurrentProject, entry_id: str) -> PromptEntryList:
    with translate_errors():
        return project.delete_prompt_entry(entry_id)


@router.get("/api/mutation-sets", response_model=MutationSetEntryList)
def list_mutation_set_entries(project: CurrentProject) -> MutationSetEntryList:
    """Reusable mutation sets (#62) — the Mutations pane list."""
    with translate_errors():
        return project.list_mutation_set_entries()


@router.post("/api/mutation-sets", response_model=MutationSetEntry)
def create_mutation_set_entry(project: CurrentProject, request: CreateMutationSetEntryRequest) -> MutationSetEntry:
    with translate_errors():
        return project.create_mutation_set_entry(request)


@router.get("/api/mutation-sets/{entry_id}", response_model=MutationSetEntry)
def get_mutation_set_entry(project: CurrentProject, entry_id: str) -> MutationSetEntry:
    with translate_errors():
        return project.read_mutation_set_entry(entry_id)


@router.put("/api/mutation-sets/{entry_id}", response_model=MutationSetEntry)
def save_mutation_set_entry(project: CurrentProject, entry_id: str, request: SaveMutationSetEntryRequest) -> MutationSetEntry:
    with translate_errors():
        return project.save_mutation_set_entry(entry_id, request)


@router.delete("/api/mutation-sets/{entry_id}", response_model=MutationSetEntryList)
def delete_mutation_set_entry(project: CurrentProject, entry_id: str) -> MutationSetEntryList:
    with translate_errors():
        return project.delete_mutation_set_entry(entry_id)


