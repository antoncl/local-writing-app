from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SelectOption(BaseModel):
    """One choice in a select / multi_select field, or a select prompt input.

    Stored as `{value, label?, color?}`. `value` is what's persisted on
    the entry; `label` (optional) is the display text — defaults to value
    if omitted. `color` is an optional machine-palette swatch id, used by
    the ColoredSelect frontend widget to render a tinted pill.

    Bare strings are accepted as a shortcut (`["draft", "complete"]` →
    `[{"value": "draft"}, {"value": "complete"}]`) so existing YAMLs and
    test fixtures keep working without migration."""

    # Empty string is allowed — many select fields use "" as a "no value
    # chosen" placeholder option. Non-string types are rejected.
    value: str
    label: str | None = None
    color: str | None = None


def _normalize_select_options(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return value
    out: list[Any] = []
    for item in value:
        if isinstance(item, str):
            out.append({"value": item})
        else:
            out.append(item)
    return out


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
    # Scene's current status value (the select-option value, e.g. "draft").
    # Surfaced here so the manuscript tree can render a colored stripe
    # without the frontend doing a per-scene fetch. None for non-leaf
    # nodes (acts/chapters/etc.) and for scenes without a status set.
    status: str | None = None
    # Scene's instance-level color override (metadata.color, a palette
    # swatch id) — lets the tree row reflect per-scene color tweaks.
    color: str | None = None
    computed_metadata: dict[str, Any] = Field(default_factory=dict)
    children: list["StructureNode"] = Field(default_factory=list)


class StructureDocument(BaseModel):
    root: StructureNode


MetadataValue = str | int | float | bool | None | list[Any] | dict[str, Any]


class NodePickerConfig(BaseModel):
    """Per-field constraint for which nodes the picker offers, replacing
    the legacy flat `target: {kind, entry_type}` shape. Matches the
    runtime NodePicker (formerly ContextPicker) config used for
    context_pick prompt inputs, so entity_ref metadata fields and
    prompt-side picks now share one vocabulary.

    Wire format mirrors the frontend's NodePickerConfig type and the
    PromptInputDefinition.target shape used by context_pick inputs."""

    # Allowed kinds. Empty = no kind constraint (anything pickable).
    kinds: list[str] = Field(default_factory=list)
    # Optional per-kind whitelist of entry_type ids. Missing key for a
    # kind means "any entry_type of that kind is allowed."
    entry_types: dict[str, list[str]] = Field(default_factory=dict)
    # Presets a context-pick UI may surface (full_outline, full_text…).
    # Unused for entity_ref metadata fields but kept on the shared
    # model so the same shape serializes both surfaces.
    presets: list[str] = Field(default_factory=list)
    # Multi-pick. None defers to the field type (entity_ref → false,
    # entity_ref_list → true).
    multiple: bool | None = None
    # Author opt-in for context-pick target-marking. Unused for
    # entity_ref metadata fields.
    allow_target_marking: bool | None = None


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
        "color",
    ]
    options: list[SelectOption] = Field(default_factory=list)
    picker_config: NodePickerConfig | None = None
    computed: dict[str, str] | None = None
    # Optional Tabler icon name (without the `ti-` prefix), e.g. "shield-half".
    # Empty/None falls back to the default glyph for the field's type
    # (see the metadata revision design). Display-only; the macro contract
    # is the field key, never the icon.
    icon: str | None = None
    # Optional L1 section label. Fields sharing a `group` render under one
    # labelled header in the rail + type editor. None = ungrouped.
    group: str | None = None
    # Set ONLY on synthetic fields generated from an L2 group application
    # (= the source group id). Never persisted; lets the UI render these as
    # group-derived (read-only, "from <group>") rather than own/inherited.
    group_origin: str | None = None

    @field_validator("options", mode="before")
    @classmethod
    def _accept_bare_strings(cls, value: Any) -> Any:
        return _normalize_select_options(value)


PromptInputType = Literal[
    "text",
    "long_text",
    "number",
    "boolean",
    "select",
    "entity_ref",
    "entity_ref_list",
    "context_pick",
    "color",
]


class PromptInputDefinition(BaseModel):
    name: str = Field(min_length=1)
    type: PromptInputType = "text"
    label: str | None = None
    default: Any | None = None
    options: list[SelectOption] = Field(default_factory=list)
    required: bool = False

    @field_validator("options", mode="before")
    @classmethod
    def _accept_bare_strings(cls, value: Any) -> Any:
        return _normalize_select_options(value)
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


class GroupMember(BaseModel):
    """One member field of a reusable group definition (L2 groups).

    `key` is the suffix combined with a GroupApplication.key_prefix to form
    the generated field's stable key (e.g. prefix "external_" + key "goal"
    → "external_goal"). The rest defines the generated field."""

    key: str
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
        "color",
    ] = "text"
    icon: str | None = None
    options: list[SelectOption] = Field(default_factory=list)
    picker_config: NodePickerConfig | None = None

    @field_validator("options", mode="before")
    @classmethod
    def _accept_bare_strings(cls, value: Any) -> Any:
        return _normalize_select_options(value)


class MetadataGroupDefinition(BaseModel):
    """A reusable group of fields, e.g. GMO = Goal / Motivation / Obstacle.

    Applied to entry types via GroupApplication. Fields resolve dynamically
    from the definition × application, so editing the definition propagates
    to every application (the "live" L2 model)."""

    name: str
    icon: str | None = None
    members: list[GroupMember] = Field(default_factory=list)


class GroupApplication(BaseModel):
    """An entry type's use of a reusable group, with a display label and a
    key prefix — e.g. GMO applied as External (external_) and Internal
    (internal_): two applications of one group, not six hand-made fields."""

    group_id: str
    label: str = ""
    key_prefix: str = ""


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
    # The body shape this entry type opens with in NodeEditor. None →
    # fall back to (none if !has_body, code if body_editor=="code",
    # else prose). Explicit values let new shapes (chat) declare
    # themselves without retrofitting has_body/body_editor semantics.
    # See decisions-node-editor-modularization + decisions-node-editor-body-spec.
    body_shape: Literal["prose", "code", "chat", "none"] | None = None
    # Starter content for new entries of this type. Used by
    # create_prompt_entry as the initial body_markdown so authoring a
    # `roleplay` (or any future type with conventions worth showing off)
    # opens with a working template the author can adapt instead of a
    # blank page.
    default_body: str = ""
    # Per-entry inputs to seed onto new prompt entries of this type.
    # Mirrors `default_body`'s role for the inputs declaration — without
    # this, `roleplay`'s starter template would reference an
    # `input.character` that doesn't exist on a freshly-created prompt.
    default_inputs: list[PromptInputDefinition] = Field(default_factory=list)
    # Type-level color (machine palette swatch id). Resolves to a hex via
    # the machine palette. Child types inherit unless they set their own.
    # Entries of this type fall back to this color when they don't carry
    # an instance-level override. None = no color set; resolver walks
    # the parent chain, then the kind-default table, then yields null.
    color: str | None = None
    # The pre-inheritance color value (mirrors `own_fields` for the fields
    # list). The editor uses this to distinguish "color set on this type"
    # from "color inherited from parent" — letting authors clear their own
    # override without disturbing the parent's value. Computed by the
    # schema inheritance resolver; not authored directly.
    own_color: str | None = None
    prompt: PromptEntryTypeExtras | None = None
    # Reusable group applications (L2). Each expands into generated prefixed
    # fields in the effective schema. Authored on the type; persisted as-is.
    group_applications: list[GroupApplication] = Field(default_factory=list)


class MetadataSchema(BaseModel):
    version: int = 1
    entry_types: dict[str, EntryTypeDefinition] = Field(default_factory=dict)
    fields: dict[str, MetadataFieldDefinition] = Field(default_factory=dict)
    # Reusable group definitions (L2), keyed by group id. Generated fields
    # from group_applications are injected into `fields` at resolution time.
    groups: dict[str, MetadataGroupDefinition] = Field(default_factory=dict)


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
    # Explicit old-value → new-value rename map for select/multi_select
    # options, computed client-side keyed by each option's original value.
    # Reorder-safe (positional pairing would mis-rename on reorder). Values
    # no longer present in the field's options are cleared from entries.
    option_migration: dict[str, str] | None = None


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


class UpsertMetadataGroupRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    group: MetadataGroupDefinition
    allow_existing: bool = True


class DeleteMetadataGroupRequest(BaseModel):
    group_id: str = Field(min_length=1)


class SetGroupApplicationsRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    entry_type_id: str = Field(min_length=1)
    applications: list[GroupApplication] = Field(default_factory=list)


class SetFieldOrderRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    entry_type_id: str = Field(min_length=1)
    # Desired order of the type's own field ids (must be a permutation of the
    # fields currently defined on the type at this layer).
    field_order: list[str] = Field(default_factory=list)


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


class ScopedTag(BaseModel):
    """A known tag with a scope (which kinds / sub-types it's suggested on).

    Scope reuses NodePickerConfig's kinds + per-kind entry_types vocabulary.
    An empty scope means "suggest everywhere" (legacy flat tags upgrade to
    this)."""

    name: str
    scope: NodePickerConfig = Field(default_factory=NodePickerConfig)


class KnownTags(BaseModel):
    tags: list[ScopedTag] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _accept_flat_tags(cls, value: Any) -> Any:
        # Defensive upgrade of the legacy flat shape (list[str]) and any
        # caller still passing bare strings → scoped entries with empty scope.
        if isinstance(value, list):
            return [
                {"name": item, "scope": {}} if isinstance(item, str) else item
                for item in value
            ]
        return value


class TagUsage(BaseModel):
    name: str
    scope: NodePickerConfig = Field(default_factory=NodePickerConfig)
    count: int = 0


class TagsOverview(BaseModel):
    tags: list[TagUsage] = Field(default_factory=list)


class UpdateTagScopeRequest(BaseModel):
    name: str = Field(min_length=1)
    scope: NodePickerConfig = Field(default_factory=NodePickerConfig)


class MergeTagsRequest(BaseModel):
    sources: list[str] = Field(default_factory=list)
    target: str = Field(min_length=1)


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


class Swatch(BaseModel):
    """A named entry in the machine-level color palette.

    `id` is stable — entries, type defaults, and select options reference
    a swatch by id, never by hex. Renaming or recoloring a swatch updates
    everything that references it. `hex` is validated as `#RRGGBB`.
    """

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str = Field(min_length=1)
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class MachineSettingsView(BaseModel):
    version: int
    providers: ProviderCredentialsView
    default_provider: str
    default_models: dict[str, str]
    default_projects_folder: str = ""
    recent_projects: list[RecentProject] = Field(default_factory=list)
    palette: list[Swatch] = Field(default_factory=list)
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
    # Replace the whole palette list. None = leave untouched.
    palette: list[Swatch] | None = None


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
    # When set, the cost estimate uses this assistant's provider/model.
    # Omit for previews that aren't bound to an assistant (e.g. the
    # prompt-editor preview pane) — token counts still come back, only
    # the cost/cache fields are omitted.
    assistant_id: str | None = None


class PreviewContentBlock(BaseModel):
    text: str
    cache_break_after: bool


class PreviewMessage(BaseModel):
    role: str
    blocks: list[PreviewContentBlock]


class PreviewCacheBlock(BaseModel):
    """One cache block derived from `cache_break_after` markers on the
    rendered messages. Labels are position-derived for v1; richer
    naming may come later (template hints, role-based, etc.).
    """

    label: str
    role: str
    tokens: int
    cache_break_after: bool


class AIPreviewResponse(BaseModel):
    messages: list[PreviewMessage]
    warnings: list[str] = Field(default_factory=list)
    char_count: int
    session_id: str | None = None
    rendered: bool
    # Token estimate over the assembled wire bytes. Always populated.
    estimated_tokens: int = 0
    # Per-cache-block breakdown — powers the cache strip UI. Each entry
    # is one run of blocks ending at a `cache_break_after` marker (or
    # the end of the message). Empty when there are no rendered messages.
    cache_blocks: list[PreviewCacheBlock] = Field(default_factory=list)
    # Pre-send input-side cost in USD. Frontend converts to EUR for
    # display (see decisions_currency_display). Null when no assistant
    # is bound or pricing is unknown (Ollama, live discovery failure).
    estimated_cost_usd: float | None = None
    # When an assistant is bound, surface its provider/model so the
    # frontend can label the estimate. Null otherwise.
    provider: str | None = None
    model: str | None = None
    # caching_style from the resolved provider (`none` / `auto` /
    # `explicit`). Drives whether the cache strip shows in the UI.
    # Null when no assistant is bound.
    caching_style: str | None = None


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


class ChatUsage(BaseModel):
    """Per-call token counts mirrored from the dispatch layer's
    `UsageMetrics` dataclass. The three input slots are disjoint —
    sum (input + cached_input + cache_write) for the total billable
    input. Costs come from `compute_cost(UsageMetrics, descriptor)`.
    """

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0


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
    # V2: per-call telemetry. Null on failure paths and when the provider
    # response didn't include usage (rare). Cost is null when pricing
    # isn't known (Ollama, descriptor lookup failure). Frontend converts
    # to EUR for display (see decisions_currency_display).
    usage: ChatUsage | None = None
    cost_usd: float | None = None


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
    # V2 telemetry — see AIChatResponse for the rules.
    usage: ChatUsage | None = None
    cost_usd: float | None = None


class AIContextPresetResponse(BaseModel):
    kind: str
    content: str


class ProjectCostChatRow(BaseModel):
    id: str
    title: str
    cost_usd: float


class ProjectCostResponse(BaseModel):
    """V2: sum of chat session costs in the current project. Frontend
    converts to EUR for display (see decisions_currency_display)."""

    total_usd: float
    chats: list[ProjectCostChatRow] = Field(default_factory=list)


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
    # V2: per-turn token + cost telemetry, captured from the streamed
    # response. Always null on user messages. Frozen value at time-of-
    # send — historical cost doesn't drift when pricing changes.
    usage: ChatUsage | None = None
    cost_usd: float | None = None


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
    # Scene this chat was opened against (e.g. "invoke chat prompt" from a
    # prose scene). The first-send template render passes it as the `scene`
    # binding so prompts that reference scene body/metadata resolve it.
    # Empty for freeform chats and chats started from the Chats pane.
    target_scene_id: str = ""
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
    # V2: running USD cost for this chat session, in the provider's currency
    # (USD; frontend converts to EUR for display). Incremented turn-by-turn
    # via save_chat_session(cost_delta_usd=...). Frozen value at time-of-
    # send — does NOT recompute if model pricing changes.
    cost_usd_total: float = 0.0
    # Per-cache-slot ISO timestamps of the most recent cache write. Slot
    # keys are short labels emitted by the chat dispatch ("system", "lore",
    # etc.). Powers the TTL countdown chips (step 9). Updated when a turn
    # writes to a slot (extracted via UsageMetrics.cache_write_tokens > 0).
    cache_write_times: dict[str, str] = Field(default_factory=dict)


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
    target_scene_id: str = ""


class SaveChatSessionRequest(BaseModel):
    title: str
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""
    target_scene_id: str = ""
    pinned: bool = False
    context_items: list[ChatSessionContextItem] = Field(default_factory=list)
    messages: list[ChatSessionMessage] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    # None = "don't touch the persisted journal". A list (even []) means
    # "this is the new journal value" and is subject to the append-only
    # guard. The chat-send endpoint is the only intended producer of new
    # journal entries; general saves (rename, message append, etc.)
    # should omit the field so the journal persists untouched.
    journal: list[ChatSessionJournalEntry] | None = None
    # V2: optional incremental cost update. When provided (typically by
    # the chat panel after a successful AI turn), it's ADDED to the
    # persisted cost_usd_total. Omit on plain renames / message-list saves.
    cost_delta_usd: float | None = None
    # V2: when provided, each slot name has its cache_write_times entry
    # set to the server's current ISO timestamp. Frontend sends the labels
    # for any slot whose `cache_write_tokens` was > 0 in the response.
    cache_write_slots: list[str] | None = None


StructureNode.model_rebuild()
# AIChatResponse declares journal_added as a forward reference because
# ChatSessionJournalEntry is defined later in the file (in the chat-session
# section). Resolve it once everything is in scope.
AIChatResponse.model_rebuild()
