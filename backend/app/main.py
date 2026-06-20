from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.models import (
    AIChatRequest,
    AIChatResponse,
    AIContextPresetResponse,
    AIGenerateRequest,
    AIGenerateResponse,
    AssistantEntry,
    AssistantEntryList,
    AIHealthRequest,
    AIHealthResponse,
    AIModelInfo,
    AIProviderInfo,
    AIProviderList,
    AIProviderModelList,
    AITierResolution,
    AIPreviewRequest,
    AIPreviewResponse,
    ChatSession,
    ChatSessionList,
    CreateChatSessionRequest,
    SaveChatSessionRequest,
    PreviewContentBlock,
    PreviewMessage,
    BacklinksResponse,
    CreateLoreEntryRequest,
    CreateProjectRequest,
    CreateAssistantEntryRequest,
    CreatePromptEntryRequest,
    ReorderAssistantsRequest,
    CreateSceneRequest,
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
    ProjectNode,
    ProjectValidation,
    PromptEntry,
    PromptEntryList,
    ReferenceCandidatesResponse,
    ReferenceResolveRequest,
    ReferenceResolveResponse,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SaveAssistantEntryRequest,
    SaveProjectNodeRequest,
    SavePromptEntryRequest,
    SaveSceneRequest,
    Scene,
    SearchRequest,
    SearchResponse,
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
from app.services.ai.profiles import CapabilityTier, ModelDescriptor
from app.services.ai.profiles.registry import known_provider_names, profile_for
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


def _preview_error_detail(exc: PreviewError) -> Any:
    """Shape the FastAPI HTTPException detail for a PreviewError.

    Plain string when there's no location info (compat with the original
    behavior); a structured dict when Jinja gave us a line. The frontend's
    `formatErrorDetail` falls back to the `message` field, so old callers
    still see something sensible.
    """
    if exc.line is None and exc.col is None:
        return exc.message
    detail: dict[str, Any] = {"message": exc.message}
    if exc.line is not None:
        detail["line"] = exc.line
    if exc.col is not None:
        detail["col"] = exc.col
    return detail


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/project/create", response_model=ProjectInfo)
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


@app.post("/api/project/open", response_model=ProjectInfo)
def open_project(request: OpenProjectRequest) -> ProjectInfo:
    from app.services import machine_settings as ms_service

    with translate_errors():
        info = service.open_project(
            Path(request.root_path),
            Path(request.projects_base_folder) if request.projects_base_folder else None,
        )
        ms_service.touch_recent_project(Path(info.root_path), info.title)
        return info


@app.get("/api/project", response_model=ProjectInfo)
def get_project() -> ProjectInfo:
    with translate_errors():
        return service.current_project()


@app.get("/api/project/node", response_model=ProjectNode)
def get_project_node() -> ProjectNode:
    with translate_errors():
        return service.read_project_node()


@app.put("/api/project/node", response_model=ProjectNode)
def save_project_node(request: SaveProjectNodeRequest) -> ProjectNode:
    with translate_errors():
        return service.save_project_node(request)


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


@app.get("/api/assistants", response_model=AssistantEntryList)
def list_assistant_entries() -> AssistantEntryList:
    with translate_errors():
        return service.list_assistant_entries()


@app.post("/api/assistants", response_model=AssistantEntry)
def create_assistant_entry(request: CreateAssistantEntryRequest) -> AssistantEntry:
    with translate_errors():
        return service.create_assistant_entry(request)


@app.get("/api/assistants/{entry_id}", response_model=AssistantEntry)
def get_assistant_entry(entry_id: str) -> AssistantEntry:
    with translate_errors():
        return service.read_assistant_entry(entry_id)


@app.put("/api/assistants/{entry_id}", response_model=AssistantEntry)
def save_assistant_entry(entry_id: str, request: SaveAssistantEntryRequest) -> AssistantEntry:
    with translate_errors():
        return service.save_assistant_entry(entry_id, request)


@app.delete("/api/assistants/{entry_id}", response_model=AssistantEntryList)
def delete_assistant_entry(entry_id: str) -> AssistantEntryList:
    with translate_errors():
        return service.delete_assistant_entry(entry_id)


@app.post("/api/assistants/order", response_model=AssistantEntryList)
def reorder_assistant_entries(request: ReorderAssistantsRequest) -> AssistantEntryList:
    with translate_errors():
        return service.reorder_assistant_entries(request)


# --- Persistent chat sessions (Phase 3) ---


@app.get("/api/chats", response_model=ChatSessionList)
def list_chat_sessions() -> ChatSessionList:
    with translate_errors():
        return service.list_chat_sessions()


@app.post("/api/chats", response_model=ChatSession)
def create_chat_session(request: CreateChatSessionRequest) -> ChatSession:
    with translate_errors():
        return service.create_chat_session(request)


@app.get("/api/chats/{chat_id}", response_model=ChatSession)
def get_chat_session(chat_id: str) -> ChatSession:
    with translate_errors():
        return service.read_chat_session(chat_id)


@app.put("/api/chats/{chat_id}", response_model=ChatSession)
def save_chat_session(chat_id: str, request: SaveChatSessionRequest) -> ChatSession:
    with translate_errors():
        return service.save_chat_session(chat_id, request)


@app.delete("/api/chats/{chat_id}", response_model=ChatSessionList)
def delete_chat_session(chat_id: str) -> ChatSessionList:
    with translate_errors():
        return service.delete_chat_session(chat_id)


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


@dataclass
class _ResolvedCall:
    provider: str
    model: str
    temperature: float
    max_tokens: int
    thinking_enabled: bool = False


def _resolve_call_params(
    settings: machine_settings_service.MachineSettings,
    *,
    assistant_id: str | None,
    provider_override: str | None,
    model_override: str | None,
    max_tokens_override: int | None,
) -> _ResolvedCall:
    """Resolve provider / model / temperature / max_tokens from a request.

    Priority for each field, highest first:
      1. Explicit override on the request (provider, model, max_tokens).
      2. The assistant indicated by assistant_id, or the entry flagged
         is_default in the file-backed roster.
      3. The legacy default_provider / default_models matrix on settings.
    """
    assistant = service.resolve_assistant(assistant_id)
    if assistant is not None:
        meta = assistant.metadata or {}
        a_provider = meta.get("ai_provider")
        a_model = meta.get("ai_model")
        provider = provider_override or (str(a_provider) if isinstance(a_provider, str) else "")
        model = model_override or (str(a_model) if isinstance(a_model, str) else "")
        try:
            temperature = float(meta.get("ai_temperature", 0.7))
        except (TypeError, ValueError):
            temperature = 0.7
        if max_tokens_override is not None:
            max_tokens = max_tokens_override
        else:
            try:
                max_tokens = int(meta.get("ai_max_tokens", 4096))
            except (TypeError, ValueError):
                max_tokens = 4096
        return _ResolvedCall(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_enabled=bool(meta.get("ai_thinking", False)),
        )
    provider = provider_override or settings.default_provider
    model = model_override or settings.default_models.get(provider or "", "")
    return _ResolvedCall(
        provider=provider,
        model=model,
        temperature=0.7,
        max_tokens=max_tokens_override if max_tokens_override is not None else 4096,
    )


def _build_settings_view(masked: dict[str, Any]) -> MachineSettingsView:
    return MachineSettingsView(
        version=masked["version"],
        providers=masked["providers"],
        default_provider=masked["default_provider"],
        default_models=masked["default_models"],
        default_projects_folder=masked.get("default_projects_folder", ""),
        recent_projects=masked.get("recent_projects", []),
        config_path=str(machine_settings_service.config_path()),
    )


@app.get("/api/settings/machine", response_model=MachineSettingsView)
def get_machine_settings() -> MachineSettingsView:
    current = machine_settings_service.load_settings()
    masked = machine_settings_service.mask_credentials(current)
    return _build_settings_view(masked)


@app.put("/api/settings/machine", response_model=MachineSettingsView)
def update_machine_settings(request: MachineSettingsUpdate) -> MachineSettingsView:
    current = machine_settings_service.load_settings()
    patch = request.model_dump(exclude_unset=True)
    updated = machine_settings_service.merge_update(current, patch)
    machine_settings_service.save_settings(updated)
    masked = machine_settings_service.mask_credentials(updated)
    return _build_settings_view(masked)


# --- AI: health check ---


@app.post("/api/ai/health", response_model=AIHealthResponse)
def ai_health(request: AIHealthRequest) -> AIHealthResponse:
    settings = machine_settings_service.load_settings()
    resolved = _resolve_call_params(
        settings,
        assistant_id=request.assistant_id,
        provider_override=request.provider,
        model_override=request.model,
        max_tokens_override=None,
    )
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"
    return ai_providers.health_check(
        provider_name=resolved.provider,
        model=resolved.model,
        settings=settings,
        policy=policy,
    )


def _descriptor_to_wire(descriptor: ModelDescriptor) -> AIModelInfo:
    return AIModelInfo(
        id=descriptor.id,
        display_name=descriptor.display_name,
        provider=descriptor.provider,
        context_window=descriptor.context_window,
        tier=descriptor.tier.value,
        capabilities=sorted(c.value for c in descriptor.capabilities),
        deprecated=descriptor.deprecated,
        sunset_date=descriptor.sunset_date.isoformat() if descriptor.sunset_date else None,
        successor=descriptor.successor,
        cost_in_per_mtok=descriptor.cost_in_per_mtok,
        cost_out_per_mtok=descriptor.cost_out_per_mtok,
        cache_read_multiplier=descriptor.cache_read_multiplier,
    )


@app.get("/api/ai/providers", response_model=AIProviderList)
def list_ai_providers() -> AIProviderList:
    """List the providers the assistant builder can pick from."""

    from app.services.machine_settings import PROVIDER_DISPLAY_NAMES

    return AIProviderList(
        providers=[
            AIProviderInfo(
                name=name,
                display_name=PROVIDER_DISPLAY_NAMES.get(name, name.title()),
            )
            for name in known_provider_names()
        ]
    )


@app.get("/api/ai/providers/{provider}/models", response_model=AIProviderModelList)
async def list_ai_provider_models(
    provider: str, force_refresh: bool = Query(default=False)
) -> AIProviderModelList:
    """Return the provider's model catalogue.

    Falls back to bake-in data if live discovery fails (offline, bad key
    — see `ProviderProfile.list_models()` semantics). `force_refresh`
    bypasses any in-memory cache the profile holds."""

    if provider not in known_provider_names():
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    settings = machine_settings_service.load_settings()
    profile = profile_for(provider, settings)
    descriptors = await profile.list_models(force_refresh=force_refresh)
    return AIProviderModelList(
        provider=provider,
        models=[_descriptor_to_wire(d) for d in descriptors],
    )


@app.get(
    "/api/ai/providers/{provider}/resolve-tier",
    response_model=AITierResolution,
)
async def resolve_ai_provider_tier(
    provider: str, tier: str = Query(...)
) -> AITierResolution:
    """Ask a provider to resolve a capability tier to a concrete model id.

    Frontend calls this at save time so the assistant entry stores the
    literal model. Returns null `model_id` if the tier has no candidates
    (e.g. PREMIUM on Ollama)."""

    if provider not in known_provider_names():
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    try:
        tier_enum = CapabilityTier(tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {tier}") from exc
    settings = machine_settings_service.load_settings()
    profile = profile_for(provider, settings)
    descriptors = await profile.list_models()
    model_id = profile.model_for_tier(tier_enum, descriptors)
    return AITierResolution(provider=provider, tier=tier, model_id=model_id)


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
            raise HTTPException(
                status_code=exc.status_code,
                detail=_preview_error_detail(exc),
            ) from exc

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
    resolved = _resolve_call_params(
        settings,
        assistant_id=request.assistant_id,
        provider_override=request.provider,
        model_override=request.model,
        max_tokens_override=request.max_tokens,
    )
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"

    result = ai_providers.chat(
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=request.system_prompt,
        messages=[m.model_dump() for m in request.messages],
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
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
            raise HTTPException(
                status_code=exc.status_code,
                detail=_preview_error_detail(exc),
            ) from exc

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
    resolved = _resolve_call_params(
        settings,
        assistant_id=request.assistant_id,
        provider_override=request.provider,
        model_override=request.model,
        max_tokens_override=request.max_tokens,
    )
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"

    result = ai_providers.chat(
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=system_prompt,
        messages=chat_messages,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
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


# --- AI: streaming variants (NDJSON) ---
#
# Each line of the response is a JSON object. Events:
#   {"type":"delta","text":"..."}                            (zero or more)
#   {"type":"thinking","text":"..."}                         (zero or more)
#   {"type":"done","provider":"...","model":"...",
#    "latency_ms":N,"stop_reason":"...","truncated":bool,
#    "policy":"...","session_id":"...","char_count":N}       (exactly one, on success)
#   {"type":"error","error":"...","provider":"...",
#    "model":"...","latency_ms":N,"policy":"..."}            (exactly one, on failure)


def _ndjson(line: dict[str, Any]) -> str:
    return json.dumps(line, ensure_ascii=False) + "\n"


def _stream_provider_events(
    events: Iterator[ai_providers.StreamEvent],
    *,
    policy: str,
    extra_done: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Adapt provider events to NDJSON lines. Suppresses empty deltas."""
    extra_done = extra_done or {}
    try:
        for ev in events:
            if isinstance(ev, ai_providers.StreamDelta):
                if ev.text:
                    yield _ndjson({"type": "delta", "text": ev.text})
            elif isinstance(ev, ai_providers.StreamThinking):
                if ev.text:
                    yield _ndjson({"type": "thinking", "text": ev.text})
            elif isinstance(ev, ai_providers.StreamDone):
                yield _ndjson({
                    "type": "done",
                    "provider": ev.provider,
                    "model": ev.model,
                    "latency_ms": ev.latency_ms,
                    "stop_reason": ev.stop_reason,
                    "truncated": ev.truncated,
                    "policy": policy,
                    **extra_done,
                })
            elif isinstance(ev, ai_providers.StreamError):
                yield _ndjson({
                    "type": "error",
                    "error": ev.error,
                    "provider": ev.provider,
                    "model": ev.model,
                    "latency_ms": ev.latency_ms,
                    "policy": policy,
                })
    except Exception as exc:  # noqa: BLE001 — last-resort guard so the stream always terminates
        yield _ndjson({
            "type": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "provider": "",
            "model": "",
            "latency_ms": 0,
            "policy": policy,
        })


@app.post("/api/ai/chat/stream")
def ai_chat_stream(request: AIChatRequest) -> StreamingResponse:
    settings = machine_settings_service.load_settings()
    resolved = _resolve_call_params(
        settings,
        assistant_id=request.assistant_id,
        provider_override=request.provider,
        model_override=request.model,
        max_tokens_override=request.max_tokens,
    )
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"

    events = ai_providers.chat_stream(
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=request.system_prompt,
        messages=[m.model_dump() for m in request.messages],
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        thinking_enabled=resolved.thinking_enabled,
        settings=settings,
        policy=policy,
    )
    return StreamingResponse(
        _stream_provider_events(events, policy=policy),
        media_type="application/x-ndjson",
    )


@app.post("/api/ai/generate/stream")
def ai_generate_stream(request: AIGenerateRequest) -> StreamingResponse:
    # Render template first — if this fails, return an HTTP error like the
    # non-streaming endpoint does. The stream itself only carries provider events.
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
            raise HTTPException(
                status_code=exc.status_code,
                detail=_preview_error_detail(exc),
            ) from exc

    system_prompt, chat_messages = build_chat_payload(rendered)
    if not chat_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                "Template produced no user/assistant messages — nothing to send to "
                "the model. The template must contain at least one {% role \"user\" %} "
                "block with non-empty content."
            ),
        )
    char_count = sum(len(b.text) for m in rendered.messages for b in m.blocks)

    settings = machine_settings_service.load_settings()
    resolved = _resolve_call_params(
        settings,
        assistant_id=request.assistant_id,
        provider_override=request.provider,
        model_override=request.model,
        max_tokens_override=request.max_tokens,
    )
    try:
        project_info = service.current_project()
        policy = project_info.ai_policy
    except ProjectServiceError:
        policy = "off"

    events = ai_providers.chat_stream(
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=system_prompt,
        messages=chat_messages,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        thinking_enabled=resolved.thinking_enabled,
        settings=settings,
        policy=policy,
    )
    return StreamingResponse(
        _stream_provider_events(
            events,
            policy=policy,
            extra_done={"session_id": session_id, "char_count": char_count},
        ),
        media_type="application/x-ndjson",
    )


@app.get("/api/ai/context-preset", response_model=AIContextPresetResponse)
def ai_context_preset(kind: str = Query(...)) -> AIContextPresetResponse:
    from app.services.ai.context_presets import VALID_PRESETS, render_preset

    if kind not in VALID_PRESETS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown context preset '{kind}'. Valid: {list(VALID_PRESETS)}.",
        )
    with translate_errors():
        content = render_preset(service, kind)
    return AIContextPresetResponse(kind=kind, content=content)
