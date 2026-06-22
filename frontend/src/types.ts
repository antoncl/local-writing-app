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
  body_markdown: string;
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
  body_markdown: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type LoreEntry = {
  id: string;
  title: string;
  body_markdown: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type EditableDocument = Scene | LoreEntry | PromptEntry | AssistantEntry;

export type LoreEntryList = {
  entries: LoreEntrySummary[];
};

export type PromptEntrySummary = {
  id: string;
  title: string;
  body_markdown: string;
  entry_type: string;
  metadata: EntryMetadata;
  inputs: PromptInputDefinition[];
  source_layer_id?: string;
  source_layer_label?: string;
};

export type PromptEntry = {
  id: string;
  title: string;
  body_markdown: string;
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
  body_markdown?: string;
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type AssistantEntryList = {
  entries: AssistantEntrySummary[];
};


export type KnownTags = {
  tags: string[];
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
  target?: Record<string, string> | null;
  computed?: Record<string, string> | null;
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
  | "color";

// Shape carried in PromptInputDefinition.target when type === "context_pick".
// Matches the backend convention documented in
// docs/context-picker.md and the inline comment on models.py.
export type ContextPickConfig = {
  kinds?: ("scene" | "lore" | "snippet" | "assistant")[];
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
export type ContextPickRef = {
  id: string;
  kind: "scene" | "lore" | "snippet" | "assistant" | "preset";
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
  // Type-level palette swatch id. Inherits from parent unless set.
  // Resolves to a hex via the machine palette. See colors.ts.
  color?: string | null;
  // Pre-inheritance color — mirrors `own_fields`. Editor uses this to
  // distinguish "set on this type" from "inherited from parent".
  own_color?: string | null;
  default_body?: string;
  default_inputs?: PromptInputDefinition[];
  prompt?: PromptEntryTypeExtras | null;
};

export type MetadataSchema = {
  version: number;
  entry_types: Record<string, EntryTypeDefinition>;
  fields: Record<string, MetadataFieldDefinition>;
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
  body_markdown: string;
  revision: string;
  entry_type: string;
  metadata: Record<string, unknown>;
  computed_metadata: Record<string, unknown>;
};

export type SaveProjectNodeRequest = {
  title: string;
  body_markdown: string;
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

export type AIPreviewResponse = {
  messages: PreviewMessage[];
  warnings: string[];
  char_count: number;
  session_id?: string | null;
  rendered: boolean;
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
};

export type ChatSessionList = {
  sessions: ChatSessionSummary[];
};

export type CreateChatSessionRequest = {
  title?: string;
  prompt_entry_id?: string;
  assistant_id?: string;
  system_prompt?: string;
};

export type SaveChatSessionRequest = {
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  system_prompt: string;
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
