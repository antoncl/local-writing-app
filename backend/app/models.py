from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    title: str = Field(default="Untitled Project", min_length=1)
    # Optional — when omitted, the project's parent folder is used. The
    # frontend no longer surfaces this; kept on the request for back-compat
    # and to keep the validation path open for tooling.
    projects_base_folder: str | None = None


class OpenProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    projects_base_folder: str | None = None


AIPolicy = Literal["off", "local-only", "cloud-allowed"]


class ProjectInfo(BaseModel):
    title: str
    root_path: str
    projects_base_folder: str | None = None
    ai_policy: AIPolicy = "off"
    ai_default_provider: str | None = None
    ai_default_model_class: str | None = None


class UpdateProjectSettingsRequest(BaseModel):
    projects_base_folder: str | None = None
    ai_policy: AIPolicy | None = None
    ai_default_provider: str | None = None
    ai_default_model_class: str | None = None


class ProjectValidation(BaseModel):
    valid: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    migrations_applied: list[str] = Field(default_factory=list)


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListing(BaseModel):
    path: str
    parent_path: str | None = None
    directories: list[DirectoryEntry] = Field(default_factory=list)


class StructureNode(BaseModel):
    id: str
    type: str
    title: str
    scene_id: str | None = None
    computed_metadata: dict[str, Any] = Field(default_factory=dict)
    children: list["StructureNode"] = Field(default_factory=list)


class StructureDocument(BaseModel):
    root: StructureNode


MetadataValue = str | int | float | bool | None | list[Any] | dict[str, Any]


class MetadataFieldDefinition(BaseModel):
    name: str
    type: Literal[
        "text",
        "long_text",
        "number",
        "boolean",
        "date",
        "select",
        "multi_select",
        "entity_ref",
        "entity_ref_list",
        "tags",
        "computed",
    ]
    options: list[str] = Field(default_factory=list)
    target: dict[str, str] | None = None
    computed: dict[str, str] | None = None


PromptInputType = Literal[
    "text",
    "long_text",
    "number",
    "boolean",
    "select",
    "entity_ref",
    "entity_ref_list",
    "context_pick",
]


class PromptInputDefinition(BaseModel):
    name: str = Field(min_length=1)
    type: PromptInputType = "text"
    label: str | None = None
    default: Any | None = None
    options: list[str] = Field(default_factory=list)
    required: bool = False
    # When type is entity_ref / entity_ref_list, `target` constrains which
    # entries the dispatch-form picker offers. Same shape as the existing
    # `target` on entity_ref metadata fields: {"kind": "scene"|"lore"} and
    # optionally {"entry_type": "<sub-type-id>"}.
    #
    # When type is context_pick, `target` carries the per-input config that
    # the runtime picker reads. Shape (see docs/context-picker.md):
    #   {
    #     "kinds": ["scene", "lore", "snippet", "assistant"],
    #     "entry_types": {"lore": ["character", "place"]},  # optional, per kind
    #     "presets": ["full_outline", "full_text"],  # optional
    #     "multiple": true,  # default true
    #   }
    target: dict[str, Any] | None = None


class PromptContextStrategy(BaseModel):
    target: dict[str, Any] | None = None
    scan_surface: list[str] = Field(default_factory=list)
    output: dict[str, Any] | None = None


class PromptEntryTypeExtras(BaseModel):
    system_prompt: str | None = None
    model_class: str | None = None
    provider_policy: AIPolicy | None = None
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    context_strategy: PromptContextStrategy | None = None


class EntryTypeDefinition(BaseModel):
    name: str
    kind: str
    parent: str | None = None
    abstract: bool = False
    fields: list[str] = Field(default_factory=list)
    own_fields: list[str] = Field(default_factory=list)
    display_template: str = "{title}"
    has_body: bool = True
    body_editor: Literal["wysiwyg", "code"] = "wysiwyg"
    body_language: Literal["markdown", "jinja2", "plain"] = "markdown"
    prompt: PromptEntryTypeExtras | None = None


class MetadataSchema(BaseModel):
    version: int = 1
    entry_types: dict[str, EntryTypeDefinition] = Field(default_factory=dict)
    fields: dict[str, MetadataFieldDefinition] = Field(default_factory=dict)


class MetadataSchemaLayer(BaseModel):
    id: str
    label: str
    folder_path: str
    schema_path: str
    exists: bool = False


class MetadataSchemaLayers(BaseModel):
    layers: list[MetadataSchemaLayer] = Field(default_factory=list)


class MetadataDefinitionSource(BaseModel):
    layer_id: str
    layer_label: str
    schema_path: str | None = None
    built_in: bool = False


class MetadataSchemaOverview(BaseModel):
    effective_schema: MetadataSchema
    layers: list[MetadataSchemaLayer] = Field(default_factory=list)
    entry_type_sources: dict[str, MetadataDefinitionSource] = Field(default_factory=dict)
    field_sources: dict[str, MetadataDefinitionSource] = Field(default_factory=dict)


class UpsertMetadataFieldRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    field: MetadataFieldDefinition
    entry_type: str = "scene"
    allow_existing: bool = True


class UpsertMetadataEntryTypeRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    entry_type_id: str = Field(min_length=1)
    entry_type: EntryTypeDefinition
    allow_existing: bool = True


class DeleteMetadataEntryTypeRequest(BaseModel):
    entry_type_id: str = Field(min_length=1)


class MoveMetadataFieldRequest(BaseModel):
    field_id: str = Field(min_length=1)
    target_layer_id: str = Field(min_length=1)
    entry_type: str = "scene"


class RenameMetadataFieldRequest(BaseModel):
    old_field_id: str = Field(min_length=1)
    new_field_id: str = Field(min_length=1)
    entry_type: str = "scene"


class DeleteMetadataFieldRequest(BaseModel):
    field_id: str = Field(min_length=1)
    entry_type: str = "scene"


class Scene(BaseModel):
    id: str
    title: str
    body_markdown: str
    revision: str
    status: str = "draft"
    entry_type: str = "scene"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class CreateSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    parent_id: str | None = None


class CreateStructureNodeRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = Field(min_length=1)
    parent_id: str | None = None


class RenameStructureNodeRequest(BaseModel):
    title: str = Field(min_length=1)


class MoveStructureNodeRequest(BaseModel):
    target_parent_id: str = Field(min_length=1)
    position: int = Field(default=0, ge=0)


class SaveSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    body_markdown: str
    base_revision: str | None = None
    status: str = "draft"
    entry_type: str = "scene"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class ProjectNode(BaseModel):
    """The project's own node (file: project.md). Singleton per folder.

    For a flat (single-book) project, this carries the book's metadata
    and blurb. Per decisions_project_nesting, when nesting lands the same
    model represents universe/series/book by different field values —
    no separate "book" kind needed.
    """

    id: str = "project"
    title: str
    body_markdown: str = ""
    revision: str = ""
    entry_type: str = "project"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class SaveProjectNodeRequest(BaseModel):
    title: str = Field(min_length=1)
    body_markdown: str = ""
    base_revision: str | None = None
    entry_type: str = "project"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class LoreEntrySummary(BaseModel):
    id: str
    title: str
    body_markdown: str = ""
    entry_type: str = "lore_note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class LoreEntry(BaseModel):
    id: str
    title: str
    body_markdown: str
    revision: str
    entry_type: str = "lore_note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class LoreEntryList(BaseModel):
    entries: list[LoreEntrySummary] = Field(default_factory=list)


class KnownTags(BaseModel):
    tags: list[str] = Field(default_factory=list)


class CreateLoreEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "lore_note"


class SaveLoreEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    body_markdown: str
    base_revision: str | None = None
    entry_type: str = "lore_note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class PromptEntrySummary(BaseModel):
    id: str
    title: str
    body_markdown: str = ""
    entry_type: str = "prompt"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    # Per-entry input declarations. Each prompt declares the parameters its
    # template body references via `{{ input.<name> }}`. Used to be on the
    # entry-type's PromptEntryTypeExtras; now lives where the template that
    # uses it lives. The Type-level inputs field stays in the model for
    # backwards-compatibility on read but is no longer consulted at runtime.
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    source_layer_id: str = ""
    source_layer_label: str = ""


class PromptEntry(BaseModel):
    id: str
    title: str
    body_markdown: str
    revision: str
    entry_type: str = "prompt"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class PromptEntryList(BaseModel):
    entries: list[PromptEntrySummary] = Field(default_factory=list)


class CreatePromptEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "prompt"


class SavePromptEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    body_markdown: str
    base_revision: str | None = None
    entry_type: str = "prompt"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    inputs: list[PromptInputDefinition] = Field(default_factory=list)


class AssistantEntrySummary(BaseModel):
    id: str
    title: str
    entry_type: str = "assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class AssistantEntry(BaseModel):
    id: str
    title: str
    revision: str
    entry_type: str = "assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class AssistantEntryList(BaseModel):
    entries: list[AssistantEntrySummary] = Field(default_factory=list)


class CreateAssistantEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "assistant"
    # "" → machine layer (the default). Otherwise the layer-id (project root
    # hash) where the file should land.
    layer_id: str = ""


class SaveAssistantEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    base_revision: str | None = None
    entry_type: str = "assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class ReorderAssistantsRequest(BaseModel):
    # "" → machine layer. Otherwise the layer id (hash of folder path) as
    # returned in source_layer_id on each entry.
    layer_id: str = ""
    ordered_ids: list[str] = Field(default_factory=list)


class TodoItem(BaseModel):
    id: str
    text: str
    status: Literal["open", "done"] = "open"
    scope: Literal["project", "scene"] = "project"
    scene_id: str | None = None
    anchor_id: str | None = None


class TodoDocument(BaseModel):
    items: list[TodoItem] = Field(default_factory=list)


class CreateTodoRequest(BaseModel):
    text: str = Field(min_length=1)
    scope: Literal["project", "scene"] = "project"
    scene_id: str | None = None
    anchor_id: str | None = None


class UpdateTodoRequest(BaseModel):
    text: str | None = None
    status: Literal["open", "done"] | None = None
    scope: Literal["project", "scene"] | None = None
    scene_id: str | None = None


class ReferenceCandidate(BaseModel):
    id: str
    title: str
    kind: str
    entry_type: str
    summary: str = ""
    found: bool = True
    source_layer_id: str = ""
    source_layer_label: str = ""


class ReferenceResolveRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class ReferenceResolveResponse(BaseModel):
    candidates: list[ReferenceCandidate] = Field(default_factory=list)


class ReferenceCandidatesResponse(BaseModel):
    candidates: list[ReferenceCandidate] = Field(default_factory=list)


class Backlink(BaseModel):
    id: str
    title: str
    kind: str
    entry_type: str
    field_id: str
    field_name: str


class BacklinksResponse(BaseModel):
    target_id: str
    backlinks: list[Backlink] = Field(default_factory=list)


class StructureNodeDeletePreview(BaseModel):
    target_id: str
    target_title: str
    target_type: str
    descendant_scene_count: int = 0
    descendant_container_count: int = 0
    backlinks: list[Backlink] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = ""
    include_scenes: bool = True
    include_lore: bool = True
    include_open_todos: bool = False


class SearchHit(BaseModel):
    kind: Literal["scene", "lore", "project"] = "scene"
    file_id: str
    path: str
    line: int
    excerpt: str
    todo_id: str | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)


# --- AI / machine settings ---


class ProviderCredentialsView(BaseModel):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_host: str = ""


class RecentProject(BaseModel):
    path: str
    title: str
    opened_at: str   # ISO 8601


class MachineSettingsView(BaseModel):
    version: int
    providers: ProviderCredentialsView
    default_provider: str
    default_models: dict[str, str]
    default_projects_folder: str = ""
    recent_projects: list[RecentProject] = Field(default_factory=list)
    config_path: str


class ProviderCredentialsPatch(BaseModel):
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    ollama_host: str | None = None


class MachineSettingsUpdate(BaseModel):
    providers: ProviderCredentialsPatch | None = None
    default_provider: str | None = None
    default_models: dict[str, str] | None = None
    default_projects_folder: str | None = None
    # Replace the recent-projects list (e.g. user removed a stale entry).
    # None = leave untouched; an explicit list rewrites it verbatim.
    recent_projects: list[RecentProject] | None = None


class AIHealthRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    assistant_id: str | None = None


class AIHealthResponse(BaseModel):
    provider: str
    model: str
    ok: bool
    latency_ms: int
    policy: AIPolicy
    error: str | None = None


class AIProviderInfo(BaseModel):
    """Lightweight provider listing for the picker's provider dropdown."""

    name: str
    display_name: str


class AIProviderList(BaseModel):
    providers: list[AIProviderInfo]


class AIModelInfo(BaseModel):
    """Wire-format mirror of `ModelDescriptor` (in
    `app.services.ai.profiles.base`). Strings instead of enums so the
    JSON shape stays stable across enum additions."""

    id: str
    display_name: str
    provider: str
    context_window: int
    tier: str
    capabilities: list[str]
    deprecated: bool = False
    sunset_date: str | None = None
    successor: str | None = None
    cost_in_per_mtok: float | None = None
    cost_out_per_mtok: float | None = None
    cache_read_multiplier: float | None = None


class AIProviderModelList(BaseModel):
    provider: str
    models: list[AIModelInfo]


class AITierResolution(BaseModel):
    """Result of asking a provider profile to resolve a tier to a model id.

    `model_id` is null when the tier has no candidates (e.g. requesting
    PREMIUM from Ollama, or any tier when the provider's discovery is
    offline and bake-in is empty)."""

    provider: str
    tier: str
    model_id: str | None


class AIPreviewRequest(BaseModel):
    template_source: str = Field(min_length=1)
    # Empty string is allowed: chat-routed prompts don't need a scene context.
    # build_preview skips scene resolution in that case and `scene` becomes None.
    target_scene_id: str = ""
    session_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    text_before: str = ""
    text_after: str = ""
    selection: str = ""
    commit: bool = False


class PreviewContentBlock(BaseModel):
    text: str
    cache_break_after: bool


class PreviewMessage(BaseModel):
    role: str
    blocks: list[PreviewContentBlock]


class AIPreviewResponse(BaseModel):
    messages: list[PreviewMessage]
    warnings: list[str] = Field(default_factory=list)
    char_count: int
    session_id: str | None = None
    rendered: bool


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AIChatRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    assistant_id: str | None = None
    system_prompt: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    max_tokens: int | None = None
    # Optional chat session id. When present the server runs the implicit-
    # context expander on the last user message, appends new detections to
    # ChatSession.journal, and packs the journal into a cache-stable block
    # between system_prompt and conversation history.
    chat_id: str | None = None


class AIChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    provider: str
    model: str
    latency_ms: int
    policy: AIPolicy
    ok: bool
    error: str | None = None
    stop_reason: str | None = None
    truncated: bool = False
    # Lore entries newly auto-detected on THIS turn (for the audit UI chip
    # strip). Empty when no detections fired. Snapshots — frontend doesn't
    # need to look up titles separately.
    journal_added: list["ChatSessionJournalEntry"] = Field(default_factory=list)


class AIGenerateRequest(BaseModel):
    template_source: str = Field(min_length=1)
    target_scene_id: str = Field(min_length=1)
    session_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    text_before: str = ""
    text_after: str = ""
    selection: str = ""
    commit: bool = False
    provider: str | None = None
    model: str | None = None
    assistant_id: str | None = None
    max_tokens: int | None = None


class AIGenerateResponse(BaseModel):
    content: str
    rendered_messages: list[PreviewMessage] = Field(default_factory=list)
    rendered_warnings: list[str] = Field(default_factory=list)
    char_count: int
    provider: str
    model: str
    latency_ms: int
    policy: AIPolicy
    ok: bool
    error: str | None = None
    stop_reason: str | None = None
    truncated: bool = False
    session_id: str | None = None


class AIContextPresetResponse(BaseModel):
    kind: str
    content: str


# --- Persistent chat sessions (Phase 3) ---


class ChatSessionJournalEntry(BaseModel):
    """One lore entry auto-detected into the chat's implicit context.

    The journal is append-only across the session: once an entity has been
    detected (textually or via depth-1 expansion of another detection), it
    stays in scope for every subsequent turn. This monotonic shape lets the
    prompt cache breakpoint after the journal ratchet forward as the
    journal grows, without invalidating earlier turns' caches.

    `title` and `entry_type` are snapshots at detection time so the audit
    UI keeps showing what the user saw, even if the lore entry is later
    renamed or retyped.

    `source` records WHY the entry entered scope. Useful for the audit UI
    and for debugging surprising auto-includes.
    """
    entry_id: str
    title: str = ""
    entry_type: str = ""
    added_at_turn: int = 0
    source: Literal["user_message", "rendered_prompt", "depth1_expansion"] = "user_message"


class ChatSessionMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    thinking: str = ""
    truncated: bool = False
    # Lore entries that the implicit-context expander auto-detected on the
    # turn this assistant message belongs to. Captured for the audit UI so
    # reopening the chat preserves the "added when you said X" trail.
    # Always empty on user messages (detection happens between user and
    # assistant, attributed to the assistant turn).
    journal_added: list[ChatSessionJournalEntry] = Field(default_factory=list)


class ChatSessionContextItem(BaseModel):
    """A context attachment carried with the chat across turns.

    `kind` identifies the source — "scene" / "lore" / "snippet" point at an
    entry by id; "preset" carries a builtin preset name (e.g. "full_outline").
    """
    kind: Literal["scene", "lore", "snippet", "preset"]
    id: str
    entry_type: str = ""
    title: str = ""


class ChatSession(BaseModel):
    id: str
    title: str
    # The locked preset for this chat. Once messages exist, prompt_entry_id,
    # assistant_id, and system_prompt cannot change — switching requires starting
    # a new chat. This keeps the Anthropic cache prefix stable across turns.
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""
    pinned: bool = False
    created_at: str
    updated_at: str
    context_items: list[ChatSessionContextItem] = Field(default_factory=list)
    messages: list[ChatSessionMessage] = Field(default_factory=list)
    # Per-input draft values keyed by input.name. Persisted so reopening
    # a half-configured chat (drafts entered but not yet sent) restores
    # what the user typed. After first send, the values are locked
    # along with system_prompt (template was rendered with them).
    inputs: dict[str, Any] = Field(default_factory=dict)
    # Append-only log of entities auto-detected into this chat's implicit
    # context. Grows as the user types new names across turns. See
    # ChatSessionJournalEntry for the per-entry shape.
    journal: list[ChatSessionJournalEntry] = Field(default_factory=list)


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    prompt_entry_id: str = ""
    assistant_id: str = ""
    pinned: bool = False
    created_at: str
    updated_at: str
    message_count: int = 0


class ChatSessionList(BaseModel):
    sessions: list[ChatSessionSummary]


class CreateChatSessionRequest(BaseModel):
    title: str = ""
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""


class SaveChatSessionRequest(BaseModel):
    title: str
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""
    pinned: bool = False
    context_items: list[ChatSessionContextItem] = Field(default_factory=list)
    messages: list[ChatSessionMessage] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    journal: list[ChatSessionJournalEntry] = Field(default_factory=list)


StructureNode.model_rebuild()
# AIChatResponse declares journal_added as a forward reference because
# ChatSessionJournalEntry is defined later in the file (in the chat-session
# section). Resolve it once everything is in scope.
AIChatResponse.model_rebuild()
