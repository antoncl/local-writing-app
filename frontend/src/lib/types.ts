// Floating-pane window-manager types, owned by lib/stores/paneLayout. PaneId is
// the open-set of pane keys (the fixed singletons plus dynamic `editor_*` ids);
// PaneState is one pane's position/size/z-order.
export type PaneId = "project" | "outline" | "lore" | "todo" | "search" | string;

export type PaneState = {
  title: string;
  x: number;
  y: number;
  width: number;
  height: number;
  z: number;
};

export type StructureNode = {
  id: string;
  type: string;
  title: string;
  scene_id?: string | null;
  // Scene's current status value (e.g. "draft"). Used by the tree to
  // render a colored left-edge stripe by looking up the matching option
  // in metadataSchema.fields.status. Null for non-leaf nodes.
  status?: string | null;
  // Scene's instance-level color override (palette swatch id).
  color?: string | null;
  computed_metadata?: Record<string, MetadataValue>;
  children: StructureNode[];
};

export type StructureDocument = {
  root: StructureNode;
};

export type Scene = {
  id: string;
  title: string;
  body: string;
  revision: string;
  status: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type LoreEntrySummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type LoreEntry = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

// One leaf in the research tree — prose body + tags-only metadata.
// Mirrors the backend ResearchNote shape; no status / aliases /
// related_entries (see docs/research-strategy.md).
export type ResearchNote = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  // ResearchNote doesn't currently carry computed fields on the backend, but
  // shared consumers (NodeEditor) probe `.computed_metadata?.[k]`.
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type EditableDocument = Scene | LoreEntry | PromptEntry | AssistantEntry | ResearchNote;

// Document-kind discriminator shared across editor components. Broader than
// MetadataSchema.entry_types[*].kind: includes the synthetic shapes the
// editor handles directly (chat / snippet / structure_node).
export type DocumentKind =
  | "scene"
  | "lore"
  | "prompt"
  | "snippet"
  | "assistant"
  | "research"
  | "chat"
  | "project"
  | "structure_node";

export type LoreEntryList = {
  entries: LoreEntrySummary[];
};

export type MoveLoreNoteToResearchResponse = {
  note_id: string;
  tree: StructureDocument;
  dropped_fields: string[];
  lore: LoreEntryList;
};

export type PromptEntrySummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  metadata: EntryMetadata;
  inputs: PromptInputDefinition[];
  source_layer_id?: string;
  source_layer_label?: string;
};

export type PromptEntry = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  inputs: PromptInputDefinition[];
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type PromptEntryList = {
  entries: PromptEntrySummary[];
};

export type AssistantEntrySummary = {
  id: string;
  title: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type AssistantEntry = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  // has_body: false — these are present so AssistantEntry satisfies the
  // EditableDocument shape used by NodeEditor, but they are always
  // empty / undefined for assistant kind.
  body?: string;
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type AssistantEntryList = {
  entries: AssistantEntrySummary[];
};


// A known tag with a scope (which kinds / sub-types it's suggested on).
// Scope reuses NodePickerConfig; empty scope = suggested everywhere.
export type ScopedTag = {
  name: string;
  scope: NodePickerConfig;
};

export type KnownTags = {
  tags: ScopedTag[];
};

export type TagUsage = {
  name: string;
  scope: NodePickerConfig;
  count: number;
};

export type TagsOverview = {
  tags: TagUsage[];
};

export type MetadataValue = string | number | boolean | null | MetadataValue[] | { [key: string]: MetadataValue };

export type EntryMetadata = Record<string, MetadataValue>;

export type MetadataFieldType =
  | "text"
  | "long_text"
  | "number"
  | "boolean"
  | "date"
  | "select"
  | "multi_select"
  | "entity_ref"
  | "entity_ref_list"
  | "tags"
  | "computed"
  | "color";

// One choice in a select / multi_select field, or a select prompt input.
// Stored as `{value, label?, color?}`. Bare strings are accepted on the
// wire (the backend normalizes) but emitted as objects.
export type SelectOption = {
  value: string;
  label?: string | null;
  color?: string | null;
};

export type MetadataFieldDefinition = {
  name: string;
  type: MetadataFieldType;
  options: SelectOption[];
  // For entity_ref / entity_ref_list — constrains which nodes the
  // picker offers. Shape mirrors PromptInputDefinition.target for
  // context_pick inputs, so entity_ref fields and prompt picks share
  // the same NodePicker config vocabulary.
  picker_config?: NodePickerConfig | null;
  computed?: Record<string, string> | null;
  // Optional Tabler icon name (without the `ti-` prefix), e.g. "shield-half".
  // Empty/undefined falls back to the default glyph for the field's type.
  // Display-only — the stable macro contract is the field key, not the icon.
  icon?: string | null;
  // Optional L1 section label. Fields sharing a `group` render under one
  // labelled header in the rail + type editor. Undefined = ungrouped.
  group?: string | null;
  // Set only on synthetic fields generated from an L2 group application
  // (= the source group id). Lets the UI render these as group-derived
  // (read-only, "from <group>") rather than own/inherited. Never persisted.
  group_origin?: string | null;
  // Optional initial value seeded onto new entries of any type that
  // carries this field (#38). Type-matched per `type`; computed fields
  // never carry a default.
  default?: MetadataValue | null;
};

export type PromptInputType =
  | "text"
  | "long_text"
  | "number"
  | "boolean"
  | "select"
  | "entity_ref"
  | "entity_ref_list"
  | "context_pick"
  | "scene_ref"
  | "color";

// Shape carried in PromptInputDefinition.target when type === "context_pick".
// Matches the backend convention documented in
// docs/context-picker.md and the inline comment on models.py.
export type NodePickerConfig = {
  kinds?: ("scene" | "lore" | "snippet" | "assistant" | "research")[];
  entry_types?: Record<string, string[]>;   // kind -> sub-type ids
  presets?: ("full_outline" | "full_text")[];
  multiple?: boolean;
  // When true, the runtime picker shows a ★ toggle on each picked
  // scene chip. The author opts in per input — it tells template code
  // that `scene` may be bound to one of the picked scenes. Single ★ per
  // input is enforced by the picker UI.
  allow_target_marking?: boolean;
};

// What ends up in input.<name> for a context_pick input — a list of
// these light refs. Bodies are NOT carried; they're materialized
// server-side at template render time. `target: true` on a scene
// ref marks it as the implicit `scene` binding for the prompt's
// template (NC-style ★ target). Only one ref per input can be the
// target; the picker UI enforces single-selection.
export type NodePickerRef = {
  id: string;
  kind: "scene" | "lore" | "snippet" | "assistant" | "research" | "preset";
  title: string;
  entry_type?: string;
  target?: boolean;
};

export type PromptInputDefinition = {
  name: string;
  type: PromptInputType;
  label?: string | null;
  default?: MetadataValue;
  options?: SelectOption[];
  required?: boolean;
  target?: Record<string, MetadataValue> | null;
};

export type PromptContextStrategy = {
  target?: Record<string, MetadataValue> | null;
  scan_surface?: string[];
  output?: Record<string, MetadataValue> | null;
};

export type PromptEntryTypeExtras = {
  system_prompt?: string | null;
  model_class?: string | null;
  provider_policy?: AIPolicy | null;
  inputs?: PromptInputDefinition[];
  context_strategy?: PromptContextStrategy | null;
};

export type EntryBodyEditor = "wysiwyg" | "code";
export type EntryBodyLanguage = "markdown" | "jinja2" | "plain";
export type BodyShape = "prose" | "code" | "chat" | "none";

export type EntryTypeDefinition = {
  name: string;
  kind: string;
  parent?: string | null;
  abstract?: boolean;
  fields: string[];
  own_fields?: string[];
  display_template?: string;
  has_body?: boolean;
  body_editor?: EntryBodyEditor;
  body_language?: EntryBodyLanguage;
  // None → fall back to (none if !has_body, code if body_editor=="code",
  // else prose). See decisions-node-editor-body-spec.
  body_shape?: BodyShape | null;
  // Type-level palette swatch id. Inherits from parent unless set.
  // Resolves to a hex via the machine palette. See colors.ts.
  color?: string | null;
  // Pre-inheritance color — mirrors `own_fields`. Editor uses this to
  // distinguish "set on this type" from "inherited from parent".
  own_color?: string | null;
  default_body?: string;
  default_inputs?: PromptInputDefinition[];
  prompt?: PromptEntryTypeExtras | null;
  // Reusable group applications (L2). Each expands into generated prefixed
  // fields in the effective schema.
  group_applications?: GroupApplication[];
};

// One member of a reusable group definition (L2 groups). `key` is the
// suffix combined with a GroupApplication.key_prefix to form a generated
// field's stable key.
export type GroupMember = {
  key: string;
  name: string;
  type: MetadataFieldType;
  icon?: string | null;
  options?: SelectOption[];
  picker_config?: NodePickerConfig | null;
  // Default value propagated onto each generated field at schema-resolution
  // time, so every application of the group seeds new entries with the
  // same default (#38).
  default?: MetadataValue | null;
};

// A reusable group of fields (e.g. GMO = Goal/Motivation/Obstacle), applied
// to entry types via GroupApplication. Fields resolve dynamically, so
// editing the definition propagates to every application.
export type MetadataGroupDefinition = {
  name: string;
  icon?: string | null;
  members: GroupMember[];
};

// An entry type's use of a reusable group, with a display label + key prefix
// (e.g. GMO applied as External (external_) and Internal (internal_)).
export type GroupApplication = {
  group_id: string;
  label: string;
  key_prefix: string;
};

export type MetadataSchema = {
  version: number;
  entry_types: Record<string, EntryTypeDefinition>;
  fields: Record<string, MetadataFieldDefinition>;
  // Reusable group definitions keyed by group id (L2 groups).
  groups?: Record<string, MetadataGroupDefinition>;
};

export type MetadataSchemaLayer = {
  id: string;
  label: string;
  folder_path: string;
  schema_path: string;
  exists: boolean;
};

export type MetadataSchemaLayers = {
  layers: MetadataSchemaLayer[];
};

export type MetadataDefinitionSource = {
  layer_id: string;
  layer_label: string;
  schema_path?: string | null;
  built_in: boolean;
};

export type MetadataSchemaOverview = {
  effective_schema: MetadataSchema;
  layers: MetadataSchemaLayer[];
  entry_type_sources: Record<string, MetadataDefinitionSource>;
  field_sources: Record<string, MetadataDefinitionSource>;
};

export type TodoItem = {
  id: string;
  text: string;
  status: "open" | "done";
  scope: "project" | "scene";
  scene_id?: string | null;
  anchor_id?: string | null;
};

export type TodoDocument = {
  items: TodoItem[];
};

// An in-prose embedded TODO, enumerated by scanning scene bodies (GH #45).
// Editor-pane independent — a rebuildable index over scenes.
export type EmbeddedTodoRecord = {
  todo_id: string;
  scene_id: string;
  status: "open" | "done";
  note: string;
  text: string;
  line: number;
  scene_path: string;
};

export type EmbeddedTodoList = {
  items: EmbeddedTodoRecord[];
};

// Mid-scene lore mutation records (#33). A marker sets one field of one lore
// entry to a new value at a prose position; the timeline is manuscript-ordered.
export type MutationMarkerRecord = {
  marker_id: string;
  entity_id: string;
  field: string;
  op: string; // "replace" (default) | "add" | "remove" (#58)
  value: string;
  name: string; // optional human label (#65)
  group: string; // co-authored-set tie (#65)
  scene_id: string;
  offset: number;
  line: number;
  scene_path: string;
};

export type MutationMarkerList = {
  items: MutationMarkerRecord[];
};

export type EffectiveStateResponse = {
  entity_id: string;
  scene_id: string;
  position: number | null;
  // Scalar fields resolve to a string; collection fields to a string[] (ADR-0009).
  values: Record<string, string | string[]>;
};

export type ProjectValidation = {
  valid: boolean;
  warnings: string[];
  errors: string[];
  migrations_applied: string[];
};

export type AIPolicy = "off" | "local-only" | "cloud-allowed";

export type ProjectInfo = {
  title: string;
  root_path: string;
  projects_base_folder?: string | null;
  ai_policy: AIPolicy;
  ai_default_provider?: string | null;
  ai_default_model_class?: string | null;
};

export type ProviderCredentialsView = {
  anthropic_api_key: string;
  openai_api_key: string;
  openrouter_api_key: string;
  ollama_host: string;
};

export type ProjectNode = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: Record<string, unknown>;
  computed_metadata: Record<string, unknown>;
};

export type SaveProjectNodeRequest = {
  title: string;
  body: string;
  base_revision?: string | null;
  entry_type?: string;
  metadata?: Record<string, unknown>;
};

export type RecentProject = {
  path: string;
  title: string;
  opened_at: string;
};

export type Swatch = {
  id: string;
  label: string;
  hex: string;
};

export type MachineSettingsView = {
  version: number;
  providers: ProviderCredentialsView;
  default_provider: string;
  default_models: Record<string, string>;
  default_projects_folder: string;
  recent_projects: RecentProject[];
  palette: Swatch[];
  config_path: string;
};

export type MachineSettingsUpdate = {
  providers?: Partial<ProviderCredentialsView>;
  default_provider?: string;
  default_models?: Record<string, string>;
  default_projects_folder?: string;
  recent_projects?: RecentProject[];
  palette?: Swatch[];
};

// Editor-side draft for MachineSettingsDialog. Flat (provider keys hoisted
// to top level) so two-way binding to inputs is straightforward; the parent
// reshapes into MachineSettingsUpdate at save time.
export type MachineSettingsDraft = {
  anthropic_api_key: string;
  openai_api_key: string;
  openrouter_api_key: string;
  ollama_host: string;
  default_provider: string;
  default_models: Record<string, string>;
  default_projects_folder: string;
  palette: Swatch[];
};

export type AIHealthResponse = {
  provider: string;
  model: string;
  ok: boolean;
  latency_ms: number;
  policy: AIPolicy;
  error?: string | null;
};

export type AIProviderInfo = {
  name: string;
  display_name: string;
};

export type AIProviderList = {
  providers: AIProviderInfo[];
};

export type AICapabilityTier = "fast" | "balanced" | "premium" | "reasoning" | "local";

export type AIModelInfo = {
  id: string;
  display_name: string;
  provider: string;
  context_window: number;
  tier: AICapabilityTier;
  capabilities: string[];
  deprecated: boolean;
  sunset_date?: string | null;
  successor?: string | null;
  cost_in_per_mtok?: number | null;
  cost_out_per_mtok?: number | null;
  cache_read_multiplier?: number | null;
};

export type AIProviderModelList = {
  provider: string;
  models: AIModelInfo[];
};

export type AITierResolution = {
  provider: string;
  tier: string;
  model_id: string | null;
};

export type AIPreviewRequest = {
  template_source: string;
  target_scene_id: string;
  session_id?: string | null;
  inputs?: Record<string, unknown>;
  text_before?: string;
  text_after?: string;
  commit?: boolean;
  // V2: when set, preview response includes estimated_cost_usd + caching_style.
  assistant_id?: string | null;
};

export type PreviewContentBlock = {
  text: string;
  cache_break_after: boolean;
};

export type PreviewMessage = {
  role: string;
  blocks: PreviewContentBlock[];
};

export type PreviewCacheBlock = {
  label: string;
  role: string;
  tokens: number;
  cache_break_after: boolean;
};

// Populated on AIPreviewResponse.error when the render failed. The preview
// endpoint returns 200 with this set rather than throwing — the editor
// auto-fires preview before required inputs are filled, so an unrendered
// template is an expected state. `/api/ai/generate` still throws.
export type PreviewErrorInfo = {
  message: string;
  // "undefined" — Jinja UndefinedError; undefined_name set when derivable.
  // "syntax"    — TemplateSyntaxError; line set.
  // "scene_not_found" — preview target_scene_id didn't resolve.
  // "other"     — catch-all.
  kind: "undefined" | "syntax" | "scene_not_found" | "other";
  line?: number | null;
  col?: number | null;
  undefined_name?: string | null;
};

export type AIPreviewResponse = {
  messages: PreviewMessage[];
  warnings: string[];
  char_count: number;
  session_id?: string | null;
  rendered: boolean;
  error?: PreviewErrorInfo | null;
  // V2 telemetry. estimated_tokens always populated; cost null when no
  // assistant or pricing unknown.
  estimated_tokens?: number;
  cache_blocks?: PreviewCacheBlock[];
  estimated_cost_usd?: number | null;
  provider?: string | null;
  model?: string | null;
  caching_style?: "none" | "auto" | "explicit" | null;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  // UI-side accumulator fields populated during the streaming chat turn.
  // Optional on the wire — the backend ignores extras on send.
  thinking?: string;
  truncated?: boolean;
  journal_added?: ChatSessionJournalEntry[];
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIChatRequest = {
  provider?: string | null;
  model?: string | null;
  assistant_id?: string | null;
  system_prompt?: string;
  messages: ChatMessage[];
  max_tokens?: number;
  chat_id?: string | null;
};

export type ChatUsage = {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
};

export type AIChatResponse = {
  role: "assistant";
  content: string;
  provider: string;
  model: string;
  latency_ms: number;
  policy: AIPolicy;
  ok: boolean;
  error?: string | null;
  stop_reason?: string | null;
  truncated: boolean;
  journal_added?: ChatSessionJournalEntry[];
  // V2 telemetry. Null on failure or when provider didn't return usage.
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIGenerateRequest = {
  template_source: string;
  target_scene_id: string;
  session_id?: string | null;
  inputs?: Record<string, unknown>;
  text_before?: string;
  text_after?: string;
  selection?: string;
  commit?: boolean;
  provider?: string | null;
  model?: string | null;
  assistant_id?: string | null;
  max_tokens?: number;
};

export type AIContextPresetResponse = {
  kind: string;
  content: string;
};

export type AIGenerateResponse = {
  content: string;
  rendered_messages: PreviewMessage[];
  rendered_warnings: string[];
  char_count: number;
  provider: string;
  model: string;
  latency_ms: number;
  policy: AIPolicy;
  ok: boolean;
  error?: string | null;
  stop_reason?: string | null;
  truncated: boolean;
  session_id?: string | null;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ProjectCostChatRow = {
  id: string;
  title: string;
  cost_usd: number;
};

export type ProjectCostResponse = {
  total_usd: number;
  chats: ProjectCostChatRow[];
};

export type AIInvocation = {
  id: string;
  ts: string;
  prompt_entry_id?: string;
  prompt_entry_type?: string;
  scene_id?: string;
  character_id?: string;
  provider?: string;
  model?: string;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIInvocationList = {
  invocations: AIInvocation[];
};

export type CreateAIInvocationRequest = {
  prompt_entry_id?: string;
  prompt_entry_type?: string;
  scene_id?: string;
  character_id?: string;
  provider?: string;
  model?: string;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ChatSessionMessage = {
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  truncated?: boolean;
  journal_added?: ChatSessionJournalEntry[];
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ChatSessionContextItem = {
  kind: "scene" | "lore" | "snippet" | "preset";
  id: string;
  entry_type?: string;
  title?: string;
};

export type ChatSessionJournalEntry = {
  entry_id: string;
  title?: string;
  entry_type?: string;
  added_at_turn?: number;
  source?: "user_message" | "rendered_prompt" | "depth1_expansion";
};

export type ChatSession = {
  id: string;
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  system_prompt: string;
  // Scene this chat was opened against; passed as the `scene` binding at
  // first-send render. Empty for freeform / Chats-pane chats.
  target_scene_id?: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  context_items: ChatSessionContextItem[];
  messages: ChatSessionMessage[];
  inputs?: Record<string, unknown>;
  journal?: ChatSessionJournalEntry[];
  // V2: running USD cost (display as EUR via money.ts).
  cost_usd_total?: number;
  // V2: per-cache-slot ISO timestamps of last cache write.
  cache_write_times?: Record<string, string>;
};

export type ChatSessionSummary = {
  id: string;
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
  cost_usd_total?: number;
};

export type ChatSessionList = {
  sessions: ChatSessionSummary[];
};

export type CreateChatSessionRequest = {
  title?: string;
  prompt_entry_id?: string;
  assistant_id?: string;
  system_prompt?: string;
  target_scene_id?: string;
};

export type SaveChatSessionRequest = {
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  system_prompt: string;
  target_scene_id?: string;
  pinned: boolean;
  context_items: ChatSessionContextItem[];
  messages: ChatSessionMessage[];
  inputs?: Record<string, unknown>;
  journal?: ChatSessionJournalEntry[];
  // V2: incremental cost to ADD to persisted cost_usd_total. Backend
  // clamps negatives to 0 (cost is monotonic).
  cost_delta_usd?: number;
  // V2: slot labels whose cache_write_times entry should be stamped
  // with the current server time. Send when the response's usage had
  // cache_write_tokens > 0 for that slot.
  cache_write_slots?: string[];
};

export type DirectoryEntry = {
  name: string;
  path: string;
};

export type DirectoryListing = {
  path: string;
  parent_path?: string | null;
  directories: DirectoryEntry[];
};

export type SearchHit = {
  kind: "scene" | "lore" | "project";
  file_id: string;
  path: string;
  line: number;
  excerpt: string;
  todo_id?: string | null;
};

export type ReferenceCandidate = {
  id: string;
  title: string;
  kind: string;
  entry_type: string;
  summary: string;
  found: boolean;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type ReferenceCandidatesResponse = {
  candidates: ReferenceCandidate[];
};

export type ReferenceResolveResponse = {
  candidates: ReferenceCandidate[];
};

export type Backlink = {
  id: string;
  title: string;
  kind: string;
  entry_type: string;
  field_id: string;
  field_name: string;
};

export type BacklinksResponse = {
  target_id: string;
  backlinks: Backlink[];
};

export type StructureNodeDeletePreview = {
  target_id: string;
  target_title: string;
  target_type: string;
  descendant_scene_count: number;
  descendant_container_count: number;
  backlinks: Backlink[];
};
