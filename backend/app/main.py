from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    AIChatRequest,
    AIChatResponse,
    AIGenerateRequest,
    AIGenerateResponse,
    AIHealthRequest,
    AIHealthResponse,
    AIPreviewRequest,
    AIPreviewResponse,
    PreviewContentBlock,
    PreviewMessage,
    BacklinksResponse,
    CreateLoreEntryRequest,
    CreateProjectRequest,
    CreatePromptEntryRequest,
    CreateSceneRequest,
    CreateSnippetEntryRequest,
    CreateStructureNodeRequest,
    CreateTodoRequest,
    MachineSettingsUpdate,
    MachineSettingsView,
    MoveStructureNodeRequest,
    RenameStructureNodeRequest,
    DeleteMetadataEntryTypeRequest,
    DeleteMetadataFieldRequest,
    DirectoryListing,
    KnownTags,
    LoreEntry,
    LoreEntryList,
    MetadataSchema,
    MetadataSchemaLayers,
    MetadataSchemaOverview,
    MoveMetadataFieldRequest,
    OpenProjectRequest,
    ProjectInfo,
    ProjectValidation,
    PromptEntry,
    PromptEntryList,
    ReferenceCandidatesResponse,
    ReferenceResolveRequest,
    ReferenceResolveResponse,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveSceneRequest,
    SaveSnippetEntryRequest,
    Scene,
    SearchRequest,
    SearchResponse,
    SnippetEntry,
    SnippetEntryList,
    StructureDocument,
    StructureNodeDeletePreview,
    TodoDocument,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
    UpdateProjectSettingsRequest,
    UpdateTodoRequest,
)
from app.services import machine_settings as machine_settings_service
from app.services.ai import providers as ai_providers
from app.services.ai.preview import PreviewError, build_chat_payload, build_preview
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
        return service.create_project(Path(request.root_path), request.title, Path(request.projects_base_folder))


@app.post("/api/project/open", response_model=ProjectInfo)
def open_project(request: OpenProjectRequest) -> ProjectInfo:
    with translate_errors():
        return service.open_project(Path(request.root_path), Path(request.projects_base_folder))


@app.get("/api/project", response_model=ProjectInfo)
def get_project() -> ProjectInfo:
    with translate_errors():
        return service.current_project()


@app.patch("/api/project/settings", response_model=ProjectInfo)
def update_project_settings(request: UpdateProjectSettingsRequest) -> ProjectInfo:
    with translate_errors():
        return service.update_project_settings(request)


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


@app.post("/api/structure/nodes", response_model=StructureDocument)
def create_structure_node(request: CreateStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return service.create_structure_node(request)


@app.patch("/api/structure/nodes/{node_id}", response_model=StructureDocument)
def rename_structure_node(node_id: str, request: RenameStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return service.rename_structure_node(node_id, request.title)


@app.post("/api/structure/nodes/{node_id}/move", response_model=StructureDocument)
def move_structure_node(node_id: str, request: MoveStructureNodeRequest) -> StructureDocument:
    with translate_errors():
        return service.move_structure_node(node_id, request.target_parent_id, request.position)


@app.get("/api/structure/nodes/{node_id}/cascade-preview", response_model=StructureNodeDeletePreview)
def cascade_delete_preview(node_id: str) -> StructureNodeDeletePreview:
    with translate_errors():
        return service.cascade_delete_preview(node_id)


@app.delete("/api/structure/nodes/{node_id}", response_model=StructureDocument)
def delete_structure_node(node_id: str) -> StructureDocument:
    with translate_errors():
        return service.delete_structure_node(node_id)


@app.get("/api/metadata/schema", response_model=MetadataSchema)
def get_metadata_schema() -> MetadataSchema:
    with translate_errors():
        return service.read_metadata_schema()


@app.get("/api/metadata/schema/layers", response_model=MetadataSchemaLayers)
def get_metadata_schema_layers() -> MetadataSchemaLayers:
    with translate_errors():
        return service.read_metadata_schema_layers()


@app.get("/api/metadata/schema/overview", response_model=MetadataSchemaOverview)
def get_metadata_schema_overview() -> MetadataSchemaOverview:
    with translate_errors():
        return service.read_metadata_schema_overview()


@app.get("/api/tags", response_model=KnownTags)
def get_known_tags() -> KnownTags:
    with translate_errors():
        return service.read_known_tags()


@app.put("/api/metadata/schema/entry-types", response_model=MetadataSchema)
def upsert_metadata_entry_type(request: UpsertMetadataEntryTypeRequest) -> MetadataSchema:
    with translate_errors():
        return service.upsert_metadata_entry_type(request)


@app.delete("/api/metadata/schema/entry-types", response_model=MetadataSchema)
def delete_metadata_entry_type(request: DeleteMetadataEntryTypeRequest) -> MetadataSchema:
    with translate_errors():
        return service.delete_metadata_entry_type(request)


@app.put("/api/metadata/schema/fields", response_model=MetadataSchema)
def upsert_metadata_field(request: UpsertMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.upsert_metadata_field(request)


@app.post("/api/metadata/schema/fields/move", response_model=MetadataSchema)
def move_metadata_field(request: MoveMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.move_metadata_field(request)


@app.post("/api/metadata/schema/fields/rename", response_model=MetadataSchema)
def rename_metadata_field(request: RenameMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.rename_metadata_field(request)


@app.delete("/api/metadata/schema/fields", response_model=MetadataSchema)
def delete_metadata_field(request: DeleteMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.delete_metadata_field(request)


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


@app.get("/api/lore", response_model=LoreEntryList)
def list_lore_entries() -> LoreEntryList:
    with translate_errors():
        return service.list_lore_entries()


@app.post("/api/lore", response_model=LoreEntry)
def create_lore_entry(request: CreateLoreEntryRequest) -> LoreEntry:
    with translate_errors():
        return service.create_lore_entry(request)


@app.get("/api/lore/{entry_id}", response_model=LoreEntry)
def get_lore_entry(entry_id: str) -> LoreEntry:
    with translate_errors():
        return service.read_lore_entry(entry_id)


@app.put("/api/lore/{entry_id}", response_model=LoreEntry)
def save_lore_entry(entry_id: str, request: SaveLoreEntryRequest) -> LoreEntry:
    with translate_errors():
        return service.save_lore_entry(entry_id, request)


@app.delete("/api/lore/{entry_id}", response_model=LoreEntryList)
def delete_lore_entry(entry_id: str) -> LoreEntryList:
    with translate_errors():
        return service.delete_lore_entry(entry_id)


@app.get("/api/prompts", response_model=PromptEntryList)
def list_prompt_entries() -> PromptEntryList:
    with translate_errors():
        return service.list_prompt_entries()


@app.post("/api/prompts", response_model=PromptEntry)
def create_prompt_entry(request: CreatePromptEntryRequest) -> PromptEntry:
    with translate_errors():
        return service.create_prompt_entry(request)


@app.get("/api/prompts/{entry_id}", response_model=PromptEntry)
def get_prompt_entry(entry_id: str) -> PromptEntry:
    with translate_errors():
        return service.read_prompt_entry(entry_id)


@app.put("/api/prompts/{entry_id}", response_model=PromptEntry)
def save_prompt_entry(entry_id: str, request: SavePromptEntryRequest) -> PromptEntry:
    with translate_errors():
        return service.save_prompt_entry(entry_id, request)


@app.delete("/api/prompts/{entry_id}", response_model=PromptEntryList)
def delete_prompt_entry(entry_id: str) -> PromptEntryList:
    with translate_errors():
        return service.delete_prompt_entry(entry_id)


@app.get("/api/snippets", response_model=SnippetEntryList)
def list_snippet_entries() -> SnippetEntryList:
    with translate_errors():
        return service.list_snippet_entries()


@app.post("/api/snippets", response_model=SnippetEntry)
def create_snippet_entry(request: CreateSnippetEntryRequest) -> SnippetEntry:
    with translate_errors():
        return service.create_snippet_entry(request)


@app.get("/api/snippets/{entry_id}", response_model=SnippetEntry)
def get_snippet_entry(entry_id: str) -> SnippetEntry:
    with translate_errors():
        return service.read_snippet_entry(entry_id)


@app.put("/api/snippets/{entry_id}", response_model=SnippetEntry)
def save_snippet_entry(entry_id: str, request: SaveSnippetEntryRequest) -> SnippetEntry:
    with translate_errors():
        return service.save_snippet_entry(entry_id, request)


@app.delete("/api/snippets/{entry_id}", response_model=SnippetEntryList)
def delete_snippet_entry(entry_id: str) -> SnippetEntryList:
    with translate_errors():
        return service.delete_snippet_entry(entry_id)


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


@app.post("/api/references/resolve", response_model=ReferenceResolveResponse)
def resolve_references(request: ReferenceResolveRequest) -> ReferenceResolveResponse:
    with translate_errors():
        return service.resolve_references(request.ids)


@app.get("/api/references/candidates", response_model=ReferenceCandidatesResponse)
def list_reference_candidates(
    kind: str | None = Query(default=None),
    entry_type: str | None = Query(default=None),
    exclude_id: str | None = Query(default=None),
) -> ReferenceCandidatesResponse:
    with translate_errors():
        return service.list_reference_candidates(kind=kind, entry_type=entry_type, exclude_id=exclude_id)


@app.get("/api/references/backlinks", response_model=BacklinksResponse)
def list_backlinks(id: str = Query()) -> BacklinksResponse:
    with translate_errors():
        return service.list_backlinks(id)


@app.post("/api/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    with translate_errors():
        return service.search(request)


# --- Machine settings (AI provider config; never travels with the project) ---


@app.get("/api/settings/machine", response_model=MachineSettingsView)
def get_machine_settings() -> MachineSettingsView:
    current = machine_settings_service.load_settings()
    masked = machine_settings_service.mask_credentials(current)
    return MachineSettingsView(
        version=masked["version"],
        providers=masked["providers"],
        default_provider=masked["default_provider"],
        default_models=masked["default_models"],
        config_path=str(machine_settings_service.config_path()),
    )


@app.put("/api/settings/machine", response_model=MachineSettingsView)
def update_machine_settings(request: MachineSettingsUpdate) -> MachineSettingsView:
    current = machine_settings_service.load_settings()
    patch = request.model_dump(exclude_unset=True)
    updated = machine_settings_service.merge_update(current, patch)
    machine_settings_service.save_settings(updated)
    masked = machine_settings_service.mask_credentials(updated)
    return MachineSettingsView(
        version=masked["version"],
        providers=masked["providers"],
        default_provider=masked["default_provider"],
        default_models=masked["default_models"],
        config_path=str(machine_settings_service.config_path()),
    )


# --- AI: health check ---


@app.post("/api/ai/health", response_model=AIHealthResponse)
def ai_health(request: AIHealthRequest) -> AIHealthResponse:
    settings = machine_settings_service.load_settings()
    provider_name = request.provider or settings.default_provider
    model = request.model or settings.default_models.get(provider_name, "")
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"
    return ai_providers.health_check(
        provider_name=provider_name,
        model=model,
        settings=settings,
        policy=policy,
    )


@app.post("/api/ai/preview", response_model=AIPreviewResponse)
def ai_preview(request: AIPreviewRequest) -> AIPreviewResponse:
    with translate_errors():
        # `current_project` raises ProjectServiceError if no project is open;
        # translate_errors handles that. Preview itself raises PreviewError for
        # template / target failures, which we convert here.
        try:
            rendered, session_id = build_preview(
                project_service=service,
                template_source=request.template_source,
                target_scene_id=request.target_scene_id,
                session_id=request.session_id,
                inputs=request.inputs,
                text_before=request.text_before,
                text_after=request.text_after,
                selection=request.selection,
                commit=request.commit,
            )
        except PreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    messages = [
        PreviewMessage(
            role=m.role,
            blocks=[
                PreviewContentBlock(text=b.text, cache_break_after=b.cache_break_after)
                for b in m.blocks
            ],
        )
        for m in rendered.messages
    ]
    char_count = sum(len(b.text) for m in messages for b in m.blocks)
    return AIPreviewResponse(
        messages=messages,
        warnings=rendered.warnings,
        char_count=char_count,
        session_id=session_id,
        rendered=True,
    )


# --- AI: chat completion (first real model call) ---


@app.post("/api/ai/chat", response_model=AIChatResponse)
def ai_chat(request: AIChatRequest) -> AIChatResponse:
    settings = machine_settings_service.load_settings()
    provider_name = request.provider or settings.default_provider
    model = request.model or settings.default_models.get(provider_name or "", "")
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"

    result = ai_providers.chat(
        provider_name=provider_name,
        model=model,
        system_prompt=request.system_prompt,
        messages=[m.model_dump() for m in request.messages],
        max_tokens=request.max_tokens,
        settings=settings,
        policy=policy,
    )
    # Both Anthropic and OpenAI signal "hit max_tokens" — different names.
    truncated = result.stop_reason in {"max_tokens", "length"}
    return AIChatResponse(
        role="assistant",
        content=result.content,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        policy=policy,
        ok=result.ok,
        error=result.error,
        stop_reason=result.stop_reason,
        truncated=truncated,
    )


# --- AI: generate (template + provider, the full pipeline) ---


@app.post("/api/ai/generate", response_model=AIGenerateResponse)
def ai_generate(request: AIGenerateRequest) -> AIGenerateResponse:
    with translate_errors():
        try:
            rendered, session_id = build_preview(
                project_service=service,
                template_source=request.template_source,
                target_scene_id=request.target_scene_id,
                session_id=request.session_id,
                inputs=request.inputs,
                text_before=request.text_before,
                text_after=request.text_after,
                selection=request.selection,
                commit=request.commit,
            )
        except PreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    system_prompt, chat_messages = build_chat_payload(rendered)

    preview_messages = [
        PreviewMessage(
            role=m.role,
            blocks=[
                PreviewContentBlock(text=b.text, cache_break_after=b.cache_break_after)
                for b in m.blocks
            ],
        )
        for m in rendered.messages
    ]
    char_count = sum(len(b.text) for m in preview_messages for b in m.blocks)

    if not chat_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                "Template produced no user/assistant messages — nothing to send to "
                "the model. The template must contain at least one {% role \"user\" %} "
                "block with non-empty content."
            ),
        )

    settings = machine_settings_service.load_settings()
    provider_name = request.provider or settings.default_provider
    model = request.model or settings.default_models.get(provider_name or "", "")
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"

    result = ai_providers.chat(
        provider_name=provider_name,
        model=model,
        system_prompt=system_prompt,
        messages=chat_messages,
        max_tokens=request.max_tokens,
        settings=settings,
        policy=policy,
    )
    truncated = result.stop_reason in {"max_tokens", "length"}

    return AIGenerateResponse(
        content=result.content,
        rendered_messages=preview_messages,
        rendered_warnings=rendered.warnings,
        char_count=char_count,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        policy=policy,
        ok=result.ok,
        error=result.error,
        stop_reason=result.stop_reason,
        truncated=truncated,
        session_id=session_id,
    )
