import type {
  AIChatRequest,
  AIChatResponse,
  AIContextPresetResponse,
  AIGenerateRequest,
  AIHealthResponse,
  AIProviderList,
  AIProviderModelList,
  AITierResolution,
  AssistantEntry,
  AssistantEntryList,
  AIPolicy,
  AIPreviewRequest,
  AIPreviewResponse,
  AIInvocation,
  AIInvocationList,
  CreateAIInvocationRequest,
  ChatSessionJournalEntry,
  ChatUsage,
  BacklinksResponse,
  ProjectCostResponse,
  ChatSession,
  ChatSessionList,
  CreateChatSessionRequest,
  DirectoryListing,
  EffectiveStateResponse,
  EmbeddedTodoList,
  MutationMarkerList,
  EntryTypeDefinition,
  GroupApplication,
  KnownTags,
  NodePickerConfig,
  TagsOverview,
  LoreEntry,
  LoreEntryList,
  MoveLoreNoteToResearchResponse,
  MachineSettingsUpdate,
  MachineSettingsView,
  MetadataFieldDefinition,
  MetadataGroupDefinition,
  MetadataSchema,
  MetadataSchemaLayers,
  MetadataSchemaOverview,
  ProjectInfo,
  ProjectNode,
  ProjectValidation,
  SaveProjectNodeRequest,
  PromptEntry,
  PromptEntryList,
  MutationSetEntry,
  MutationSetEntryList,
  MutationSetRow,
  ReferenceCandidatesResponse,
  ReferenceResolveResponse,
  ResearchNote,
  Scene,
  SearchHit,
  StructureDocument,
  StructureNodeDeletePreview,
  TodoDocument,
  CreateViewRequest,
  SaveViewRequest,
  ViewNode,
  ViewNodeList,
} from "@/lib/types";

// Backend base URL. Defaults to the shared dev backend on :8787; an isolated
// instance (e.g. Claude's testbench on :8788) overrides it via VITE_API_BASE
// with `vite --mode claude` loading `.env.claude`.
const baseUrl = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8787/api";

/** Error subclass that carries the raw response detail so structured callers
 * can extract fields (e.g. PreviewError's line/col). `.message` still reads as
 * a human-readable string via formatErrorDetail. */
export class HttpError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new HttpError(
      formatErrorDetail(detail) ?? response.statusText,
      response.status,
      detail,
    );
  }
  return response.json() as Promise<T>;
}

function formatErrorDetail(detail: unknown): string | null {
  // FastAPI returns plain strings for ProjectServiceError, but its 422
  // validation errors arrive as an array of {loc, msg, type} objects. Without
  // explicit handling those stringified to "[object Object]" — flatten them
  // into a human-readable form so users see what went wrong.
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const obj = item as { loc?: unknown[]; msg?: string; type?: string };
          const field = Array.isArray(obj.loc) ? obj.loc.filter((p) => p !== "body").join(".") : "";
          return field ? `${field}: ${obj.msg ?? obj.type ?? "invalid"}` : (obj.msg ?? JSON.stringify(item));
        }
        return String(item);
      })
      .join("; ");
  }
  if (typeof detail === "object") {
    // PreviewError shape: { message, line?, col? }. FastAPI validation shape:
    // { msg, loc, type }. Surface whichever is present.
    const obj = detail as { message?: string; msg?: string };
    return obj.message ?? obj.msg ?? JSON.stringify(detail);
  }
  return String(detail);
}

export type AIStreamEvent =
  | { type: "delta"; text: string }
  | { type: "thinking"; text: string }
  | {
      type: "done";
      provider: string;
      model: string;
      latency_ms: number;
      stop_reason: string | null;
      truncated: boolean;
      policy: string;
      session_id?: string;
      char_count?: number;
      usage?: ChatUsage | null;
      cost_usd?: number | null;
      journal_added?: ChatSessionJournalEntry[];
    }
  | {
      type: "error";
      error: string;
      provider: string;
      model: string;
      latency_ms: number;
      policy: string;
    };

async function* streamNdjson(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncIterableIterator<AIStreamEvent> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? response.statusText);
  }
  if (!response.body) {
    throw new Error("Streaming not supported by this response.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        let nl = buffer.indexOf("\n");
        while (nl !== -1) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (line) {
            try {
              yield JSON.parse(line) as AIStreamEvent;
            } catch {
              // Ignore malformed lines — server should never emit them, but
              // don't kill the whole stream over one bad chunk.
            }
          }
          nl = buffer.indexOf("\n");
        }
      }
      if (done) break;
    }
    const tail = buffer.trim();
    if (tail) {
      try {
        yield JSON.parse(tail) as AIStreamEvent;
      } catch {
        // ignore
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export const api = {
  createProject(rootPath: string, title: string, projectsBaseFolder?: string) {
    return request<ProjectInfo>("/project/create", {
      method: "POST",
      body: JSON.stringify({
        root_path: rootPath,
        title,
        ...(projectsBaseFolder ? { projects_base_folder: projectsBaseFolder } : {}),
      }),
    });
  },
  openProject(rootPath: string, projectsBaseFolder?: string) {
    return request<ProjectInfo>("/project/open", {
      method: "POST",
      body: JSON.stringify({
        root_path: rootPath,
        ...(projectsBaseFolder ? { projects_base_folder: projectsBaseFolder } : {}),
      }),
    });
  },
  updateProjectSettings(updates: {
    projects_base_folder?: string;
    ai_policy?: AIPolicy;
    ai_default_provider?: string | null;
    ai_default_model_class?: string | null;
  }) {
    return request<ProjectInfo>("/project/settings", {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },
  getProjectNode() {
    return request<ProjectNode>("/project/node");
  },
  saveProjectNode(node: ProjectNode, body: string) {
    return request<ProjectNode>("/project/node", {
      method: "PUT",
      body: JSON.stringify({
        title: node.title,
        body,
        base_revision: node.revision,
        entry_type: node.entry_type,
        metadata: node.metadata,
      } satisfies SaveProjectNodeRequest),
    });
  },
  getMachineSettings() {
    return request<MachineSettingsView>("/settings/machine");
  },
  updateMachineSettings(update: MachineSettingsUpdate) {
    return request<MachineSettingsView>("/settings/machine", {
      method: "PUT",
      body: JSON.stringify(update),
    });
  },
  listAIProviders() {
    return request<AIProviderList>("/ai/providers");
  },
  listAIProviderModels(provider: string, forceRefresh = false) {
    const qs = forceRefresh ? "?force_refresh=true" : "";
    return request<AIProviderModelList>(`/ai/providers/${encodeURIComponent(provider)}/models${qs}`);
  },
  resolveAIProviderTier(provider: string, tier: string) {
    return request<AITierResolution>(
      `/ai/providers/${encodeURIComponent(provider)}/resolve-tier?tier=${encodeURIComponent(tier)}`,
    );
  },
  aiHealth(provider?: string, model?: string) {
    return request<AIHealthResponse>("/ai/health", {
      method: "POST",
      body: JSON.stringify({ provider: provider ?? null, model: model ?? null }),
    });
  },
  aiPreview(payload: AIPreviewRequest) {
    return request<AIPreviewResponse>("/ai/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  aiChat(payload: AIChatRequest) {
    return request<AIChatResponse>("/ai/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  aiChatStream(payload: AIChatRequest, signal?: AbortSignal) {
    return streamNdjson("/ai/chat/stream", payload, signal);
  },
  aiGenerateStream(payload: AIGenerateRequest, signal?: AbortSignal) {
    return streamNdjson("/ai/generate/stream", payload, signal);
  },
  aiContextPreset(kind: "full_outline" | "full_text") {
    return request<AIContextPresetResponse>(`/ai/context-preset?kind=${encodeURIComponent(kind)}`);
  },
  aiProjectCost() {
    return request<ProjectCostResponse>("/ai/project-cost");
  },
  aiAppendInvocation(payload: CreateAIInvocationRequest) {
    return request<AIInvocation>("/ai/invocations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  aiListInvocations(params: { scene_id?: string; character_id?: string } = {}) {
    const search = new URLSearchParams();
    if (params.scene_id) search.set("scene_id", params.scene_id);
    if (params.character_id) search.set("character_id", params.character_id);
    const query = search.toString();
    return request<AIInvocationList>(
      query ? `/ai/invocations?${query}` : "/ai/invocations",
    );
  },
  getStructure() {
    return request<StructureDocument>("/structure");
  },
  createStructureNode(title: string, entryType: string, parentId?: string | null) {
    return request<StructureDocument>("/structure/nodes", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType, parent_id: parentId ?? null }),
    });
  },
  renameStructureNode(nodeId: string, title: string) {
    return request<StructureDocument>(`/structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  },
  moveStructureNode(nodeId: string, targetParentId: string, position: number) {
    return request<StructureDocument>(`/structure/nodes/${encodeURIComponent(nodeId)}/move`, {
      method: "POST",
      body: JSON.stringify({ target_parent_id: targetParentId, position }),
    });
  },
  cascadeDeletePreview(nodeId: string) {
    return request<StructureNodeDeletePreview>(`/structure/nodes/${encodeURIComponent(nodeId)}/cascade-preview`);
  },
  deleteStructureNode(nodeId: string) {
    return request<StructureDocument>(`/structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
  },
  // ----- Research tree -----
  // Mirrors the manuscript-structure calls; see docs/research-strategy.md.
  getResearchStructure() {
    return request<StructureDocument>("/research-structure");
  },
  createResearchNode(title: string, entryType: string, parentId?: string | null) {
    return request<StructureDocument>("/research-structure/nodes", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType, parent_id: parentId ?? null }),
    });
  },
  renameResearchNode(nodeId: string, title: string) {
    return request<StructureDocument>(`/research-structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  },
  moveResearchNode(nodeId: string, targetParentId: string, position: number) {
    return request<StructureDocument>(`/research-structure/nodes/${encodeURIComponent(nodeId)}/move`, {
      method: "POST",
      body: JSON.stringify({ target_parent_id: targetParentId, position }),
    });
  },
  cascadeResearchDeletePreview(nodeId: string) {
    return request<StructureNodeDeletePreview>(`/research-structure/nodes/${encodeURIComponent(nodeId)}/cascade-preview`);
  },
  deleteResearchNode(nodeId: string) {
    return request<StructureDocument>(`/research-structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
  },
  getResearchNote(noteId: string) {
    return request<ResearchNote>(`/research/notes/${encodeURIComponent(noteId)}`);
  },
  saveResearchNote(note: ResearchNote, body: string) {
    return request<ResearchNote>(`/research/notes/${encodeURIComponent(note.id)}`, {
      method: "PUT",
      body: JSON.stringify({
        title: note.title,
        body,
        base_revision: note.revision,
        entry_type: note.entry_type,
        metadata: note.metadata,
      }),
    });
  },
  getMetadataSchema() {
    return request<MetadataSchema>("/metadata/schema");
  },
  getMetadataSchemaLayers() {
    return request<MetadataSchemaLayers>("/metadata/schema/layers");
  },
  getMetadataSchemaOverview() {
    return request<MetadataSchemaOverview>("/metadata/schema/overview");
  },
  getKnownTags() {
    return request<KnownTags>("/tags");
  },
  getTagsOverview() {
    return request<TagsOverview>("/tags/overview");
  },
  updateTagScope(name: string, scope: NodePickerConfig) {
    return request<KnownTags>("/tags/scope", {
      method: "PUT",
      body: JSON.stringify({ name, scope }),
    });
  },
  mergeTags(sources: string[], target: string) {
    return request<KnownTags>("/tags/merge", {
      method: "POST",
      body: JSON.stringify({ sources, target }),
    });
  },
  upsertMetadataEntryType(layerId: string, entryTypeId: string, entryType: EntryTypeDefinition, allowExisting = true) {
    return request<MetadataSchema>("/metadata/schema/entry-types", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, entry_type_id: entryTypeId, entry_type: entryType, allow_existing: allowExisting }),
    });
  },
  deleteMetadataEntryType(entryTypeId: string) {
    return request<MetadataSchema>("/metadata/schema/entry-types", {
      method: "DELETE",
      body: JSON.stringify({ entry_type_id: entryTypeId }),
    });
  },
  upsertMetadataField(layerId: string, fieldId: string, field: MetadataFieldDefinition, entryType = "scene:scene", allowExisting = true, optionMigration: Record<string, string> | null = null) {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, field_id: fieldId, field, entry_type: entryType, allow_existing: allowExisting, option_migration: optionMigration }),
    });
  },
  moveMetadataField(fieldId: string, targetLayerId: string, entryType = "scene:scene") {
    return request<MetadataSchema>("/metadata/schema/fields/move", {
      method: "POST",
      body: JSON.stringify({ field_id: fieldId, target_layer_id: targetLayerId, entry_type: entryType }),
    });
  },
  renameMetadataField(oldFieldId: string, newFieldId: string, entryType = "scene:scene") {
    return request<MetadataSchema>("/metadata/schema/fields/rename", {
      method: "POST",
      body: JSON.stringify({ old_field_id: oldFieldId, new_field_id: newFieldId, entry_type: entryType }),
    });
  },
  deleteMetadataField(fieldId: string, entryType = "scene:scene") {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "DELETE",
      body: JSON.stringify({ field_id: fieldId, entry_type: entryType }),
    });
  },
  upsertMetadataGroup(layerId: string, groupId: string, group: MetadataGroupDefinition, allowExisting = true) {
    return request<MetadataSchema>("/metadata/schema/groups", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, group_id: groupId, group, allow_existing: allowExisting }),
    });
  },
  deleteMetadataGroup(groupId: string) {
    return request<MetadataSchema>("/metadata/schema/groups", {
      method: "DELETE",
      body: JSON.stringify({ group_id: groupId }),
    });
  },
  setEntryTypeGroupApplications(layerId: string, entryTypeId: string, applications: GroupApplication[]) {
    return request<MetadataSchema>("/metadata/schema/entry-types/group-applications", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, entry_type_id: entryTypeId, applications }),
    });
  },
  setEntryTypeFieldOrder(layerId: string, entryTypeId: string, fieldOrder: string[]) {
    return request<MetadataSchema>("/metadata/schema/entry-types/field-order", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, entry_type_id: entryTypeId, field_order: fieldOrder }),
    });
  },
  listDirectories(path?: string) {
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    return request<DirectoryListing>(`/directories${query}`);
  },
  validateProject() {
    return request<ProjectValidation>("/project/validate", {
      method: "POST",
    });
  },
  repairProject() {
    return request<ProjectValidation>("/project/repair", {
      method: "POST",
    });
  },
  createScene(title: string, parentId?: string) {
    return request<Scene>("/scenes", {
      method: "POST",
      body: JSON.stringify({ title, parent_id: parentId }),
    });
  },
  getScene(sceneId: string) {
    return request<Scene>(`/scenes/${sceneId}`);
  },
  saveScene(scene: Scene, body: string) {
    return request<Scene>(`/scenes/${scene.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: scene.title,
        body,
        base_revision: scene.revision,
        status: scene.status,
        entry_type: scene.entry_type,
        metadata: scene.metadata,
      }),
    });
  },
  deleteScene(sceneId: string) {
    return request<StructureDocument>(`/scenes/${sceneId}`, {
      method: "DELETE",
    });
  },
  listLoreEntries() {
    return request<LoreEntryList>("/lore");
  },
  createLoreEntry(title: string, entryType: string) {
    return request<LoreEntry>("/lore", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType }),
    });
  },
  getLoreEntry(entryId: string) {
    return request<LoreEntry>(`/lore/${entryId}`);
  },
  saveLoreEntry(entry: LoreEntry, body: string) {
    return request<LoreEntry>(`/lore/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
      }),
    });
  },
  deleteLoreEntry(entryId: string) {
    return request<LoreEntryList>(`/lore/${entryId}`, {
      method: "DELETE",
    });
  },
  // Migrate a lore_note to a research/note (slice 5). Drops aliases /
  // related_entries / context_policy (the v1 research note schema is
  // title + body + tags only); the response lists what was dropped.
  moveLoreNoteToResearch(entryId: string) {
    return request<MoveLoreNoteToResearchResponse>(
      `/lore/${encodeURIComponent(entryId)}/move-to-research`,
      { method: "POST" },
    );
  },
  listPromptEntries() {
    return request<PromptEntryList>("/prompts");
  },
  createPromptEntry(title: string, entryType: string) {
    return request<PromptEntry>("/prompts", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType }),
    });
  },
  getPromptEntry(entryId: string) {
    return request<PromptEntry>(`/prompts/${entryId}`);
  },
  savePromptEntry(entry: PromptEntry, body: string) {
    return request<PromptEntry>(`/prompts/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
        inputs: entry.inputs ?? [],
      }),
    });
  },
  deletePromptEntry(entryId: string) {
    return request<PromptEntryList>(`/prompts/${entryId}`, {
      method: "DELETE",
    });
  },
  // Reusable mutation sets (#62).
  listMutationSetEntries() {
    return request<MutationSetEntryList>("/mutation-sets");
  },
  createMutationSetEntry(payload: {
    title: string;
    target_entry_type: string;
    rows: MutationSetRow[];
  }) {
    return request<MutationSetEntry>("/mutation-sets", {
      method: "POST",
      body: JSON.stringify({ ...payload, entry_type: "mutation_set:mutation_set" }),
    });
  },
  getMutationSetEntry(entryId: string) {
    return request<MutationSetEntry>(`/mutation-sets/${entryId}`);
  },
  saveMutationSetEntry(entry: MutationSetEntry) {
    return request<MutationSetEntry>(`/mutation-sets/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        target_entry_type: entry.target_entry_type,
        rows: entry.rows,
      }),
    });
  },
  deleteMutationSetEntry(entryId: string) {
    return request<MutationSetEntryList>(`/mutation-sets/${entryId}`, {
      method: "DELETE",
    });
  },
  listAssistantEntries() {
    return request<AssistantEntryList>("/assistants");
  },
  createAssistantEntry(title: string, layerId: string = "") {
    return request<AssistantEntry>("/assistants", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: "assistant:assistant", layer_id: layerId }),
    });
  },
  getAssistantEntry(entryId: string) {
    return request<AssistantEntry>(`/assistants/${entryId}`);
  },
  saveAssistantEntry(entry: AssistantEntry) {
    return request<AssistantEntry>(`/assistants/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
      }),
    });
  },
  deleteAssistantEntry(entryId: string) {
    return request<AssistantEntryList>(`/assistants/${entryId}`, {
      method: "DELETE",
    });
  },
  reorderAssistants(layerId: string, orderedIds: string[]) {
    return request<AssistantEntryList>("/assistants/order", {
      method: "POST",
      body: JSON.stringify({ layer_id: layerId, ordered_ids: orderedIds }),
    });
  },
  // Saved-view nodes (0.5.0 #78 backend / #80 designer). A view is a
  // frontmatter-only node carrying a ViewSpec; the designer (ViewBodyView)
  // reads getView and persists via saveView.
  listViews() {
    return request<ViewNodeList>("/views");
  },
  createView(payload: CreateViewRequest) {
    return request<ViewNode>("/views", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getView(viewId: string) {
    return request<ViewNode>(`/views/${encodeURIComponent(viewId)}`);
  },
  saveView(viewId: string, payload: SaveViewRequest) {
    return request<ViewNode>(`/views/${encodeURIComponent(viewId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  deleteView(viewId: string) {
    return request<ViewNodeList>(`/views/${encodeURIComponent(viewId)}`, {
      method: "DELETE",
    });
  },
  // Unified node-CRUD shim (Phase 3c). Returns the kind-specific
  // shape; callers pass the expected type. Chat read/write goes through
  // this path now (Phase 4d); the bespoke /chats/{id} GET+PUT endpoints
  // remain server-side until the per-kind endpoints retire.
  readNode<T = unknown>(nodeId: string) {
    return request<T>(`/nodes/${encodeURIComponent(nodeId)}`);
  },
  saveNode<T = unknown>(nodeId: string, payload: unknown) {
    return request<T>(`/nodes/${encodeURIComponent(nodeId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  listChatSessions() {
    return request<ChatSessionList>("/chats");
  },
  createChatSession(payload: CreateChatSessionRequest = {}) {
    return request<ChatSession>("/chats", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  deleteChatSession(chatId: string) {
    return request<ChatSessionList>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
    });
  },
  getTodos() {
    return request<TodoDocument>("/todos");
  },
  createTodo(text: string, sceneId?: string | null, anchorId?: string | null) {
    return request<TodoDocument>("/todos", {
      method: "POST",
      body: JSON.stringify({
        text,
        scope: sceneId ? "scene" : "project",
        scene_id: sceneId,
        anchor_id: anchorId,
      }),
    });
  },
  updateTodo(
    todoId: string,
    updates: { status?: "open" | "done"; text?: string; scope?: "project" | "scene"; scene_id?: string | null },
  ) {
    return request<TodoDocument>(`/todos/${todoId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },
  deleteTodo(todoId: string) {
    return request<TodoDocument>(`/todos/${todoId}`, {
      method: "DELETE",
    });
  },
  // Embedded (in-prose) todos: a rebuildable index over scenes, plus intentful
  // single-marker mutators that rewrite one marker without a full body save
  // (GH #45). The mutators return the updated scene so an open pane reconciles.
  getEmbeddedTodos() {
    return request<EmbeddedTodoList>("/todos/embedded");
  },
  updateEmbeddedTodo(sceneId: string, todoId: string, updates: { status?: "open" | "done"; note?: string }) {
    return request<Scene>(`/scenes/${sceneId}/todos/${todoId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },
  deleteEmbeddedTodo(sceneId: string, todoId: string) {
    return request<Scene>(`/scenes/${sceneId}/todos/${todoId}`, {
      method: "DELETE",
    });
  },
  // Mid-scene lore mutations (#33). The timeline is the manuscript-ordered list
  // for a lore entity; effective state resolves its overrides at a (scene,
  // position) for the time-slider. NOTE: the editor rewrites/removes pills
  // directly in the ProseMirror doc + body save, so updateMutation/deleteMutation
  // below are currently unused by the app — they mirror the backend PATCH/DELETE
  // routes (exercised by backend tests) and are kept for parity / future callers.
  getEntityMutations(entityId: string) {
    return request<MutationMarkerList>(`/lore/${entityId}/mutations`);
  },
  // Each lore entry's effective name-set (title + aliases) as of a scene — the
  // source for the effective-name-aware implicit-context matcher (#61).
  getSceneEffectiveNames(sceneId: string) {
    return request<Record<string, string[]>>(`/scenes/${encodeURIComponent(sceneId)}/effective-names`);
  },
  // The entity's records still open (live, not yet closed) at (scene, pos) — the
  // source for the `/mutate close` picker (#59).
  getLiveEntityMutations(entityId: string, sceneId: string, pos?: number) {
    const query = pos === undefined ? "" : `&pos=${pos}`;
    return request<MutationMarkerList>(
      `/lore/${entityId}/live-mutations?scene=${encodeURIComponent(sceneId)}${query}`,
    );
  },
  getEntityEffectiveState(entityId: string, sceneId: string, pos?: number, exclude?: string[]) {
    // `exclude` skips record ids — the list-edit authoring baseline when
    // re-editing a unit (#71, ADR-0017).
    const posQuery = pos === undefined ? "" : `&pos=${pos}`;
    const excludeQuery =
      exclude && exclude.length > 0 ? `&exclude=${encodeURIComponent(exclude.join(","))}` : "";
    return request<EffectiveStateResponse>(
      `/lore/${entityId}/effective?scene=${encodeURIComponent(sceneId)}${posQuery}${excludeQuery}`,
    );
  },
  updateMutation(sceneId: string, markerId: string, updates: { entity_id?: string; field?: string; value?: string }) {
    return request<Scene>(`/scenes/${sceneId}/mutations/${markerId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },
  deleteMutation(sceneId: string, markerId: string) {
    return request<Scene>(`/scenes/${sceneId}/mutations/${markerId}`, {
      method: "DELETE",
    });
  },
  search(query: string, includeOpenTodos = false) {
    return request<{ query: string; hits: SearchHit[] }>("/search", {
      method: "POST",
      body: JSON.stringify({ query, include_open_todos: includeOpenTodos }),
    });
  },
  resolveReferences(ids: string[]) {
    return request<ReferenceResolveResponse>("/references/resolve", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },
  listReferenceCandidates(filters: { kind?: string; entry_type?: string; exclude_id?: string } = {}) {
    const params = new URLSearchParams();
    if (filters.kind) params.set("kind", filters.kind);
    if (filters.entry_type) params.set("entry_type", filters.entry_type);
    if (filters.exclude_id) params.set("exclude_id", filters.exclude_id);
    const query = params.toString();
    return request<ReferenceCandidatesResponse>(`/references/candidates${query ? `?${query}` : ""}`);
  },
  listBacklinks(id: string) {
    return request<BacklinksResponse>(`/references/backlinks?id=${encodeURIComponent(id)}`);
  },
};
