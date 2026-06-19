export type StructureNode = {
  id: string;
  type: string;
  title: string;
  scene_id?: string | null;
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
  // EditableDocument shape used by DocumentEditorPane, but they are always
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
  | "computed";

export type MetadataFieldDefinition = {
  name: string;
  type: MetadataFieldType;
  options: string[];
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
  | "entity_ref_list";

export type PromptInputDefinition = {
  name: string;
  type: PromptInputType;
  label?: string | null;
  default?: MetadataValue;
  options?: string[];
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

export type MachineSettingsView = {
  version: number;
  providers: ProviderCredentialsView;
  default_provider: string;
  default_models: Record<string, string>;
  config_path: string;
};

export type MachineSettingsUpdate = {
  providers?: Partial<ProviderCredentialsView>;
  default_provider?: string;
  default_models?: Record<string, string>;
};

export type AIHealthResponse = {
  provider: string;
  model: string;
  ok: boolean;
  latency_ms: number;
  policy: AIPolicy;
  error?: string | null;
};

export type AIPreviewRequest = {
  template_source: string;
  target_scene_id: string;
  session_id?: string | null;
  inputs?: Record<string, unknown>;
  text_before?: string;
  text_after?: string;
  commit?: boolean;
};

export type PreviewContentBlock = {
  text: string;
  cache_break_after: boolean;
};

export type PreviewMessage = {
  role: string;
  blocks: PreviewContentBlock[];
};

export type AIPreviewResponse = {
  messages: PreviewMessage[];
  warnings: string[];
  char_count: number;
  session_id?: string | null;
  rendered: boolean;
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
};

export type ChatSessionMessage = {
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  truncated?: boolean;
};

export type ChatSessionContextItem = {
  kind: "scene" | "lore" | "snippet" | "preset";
  id: string;
  entry_type?: string;
  title?: string;
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
