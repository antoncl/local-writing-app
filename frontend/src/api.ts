import type {
  AIChatRequest,
  AIChatResponse,
  AIContextPresetResponse,
  AIGenerateRequest,
  AIGenerateResponse,
  AIHealthResponse,
  AssistantEntry,
  AssistantEntryList,
  AIPolicy,
  AIPreviewRequest,
  AIPreviewResponse,
  BacklinksResponse,
  ChatSession,
  ChatSessionList,
  CreateChatSessionRequest,
  SaveChatSessionRequest,
  DirectoryListing,
  EntryTypeDefinition,
  KnownTags,
  LoreEntry,
  LoreEntryList,
  MachineSettingsUpdate,
  MachineSettingsView,
  MetadataFieldDefinition,
  MetadataSchema,
  MetadataSchemaLayers,
  MetadataSchemaOverview,
  ProjectInfo,
  ProjectValidation,
  PromptEntry,
  PromptEntryList,
  ReferenceCandidatesResponse,
  ReferenceResolveResponse,
  Scene,
  SearchHit,
  StructureDocument,
  StructureNodeDeletePreview,
  TodoDocument,
} from "./types";

const baseUrl = "http://127.0.0.1:8787/api";

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
    throw new Error(formatErrorDetail(payload?.detail) ?? response.statusText);
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
    const obj = detail as { msg?: string };
    return obj.msg ?? JSON.stringify(detail);
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
  createProject(rootPath: string, title: string, projectsBaseFolder: string) {
    return request<ProjectInfo>("/project/create", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath, title, projects_base_folder: projectsBaseFolder }),
    });
  },
  openProject(rootPath: string, projectsBaseFolder: string) {
    return request<ProjectInfo>("/project/open", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath, projects_base_folder: projectsBaseFolder }),
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
  getMachineSettings() {
    return request<MachineSettingsView>("/settings/machine");
  },
  updateMachineSettings(update: MachineSettingsUpdate) {
    return request<MachineSettingsView>("/settings/machine", {
      method: "PUT",
      body: JSON.stringify(update),
    });
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
  aiGenerate(payload: AIGenerateRequest) {
    return request<AIGenerateResponse>("/ai/generate", {
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
  upsertMetadataField(layerId: string, fieldId: string, field: MetadataFieldDefinition, entryType = "scene", allowExisting = true) {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, field_id: fieldId, field, entry_type: entryType, allow_existing: allowExisting }),
    });
  },
  moveMetadataField(fieldId: string, targetLayerId: string, entryType = "scene") {
    return request<MetadataSchema>("/metadata/schema/fields/move", {
      method: "POST",
      body: JSON.stringify({ field_id: fieldId, target_layer_id: targetLayerId, entry_type: entryType }),
    });
  },
  renameMetadataField(oldFieldId: string, newFieldId: string, entryType = "scene") {
    return request<MetadataSchema>("/metadata/schema/fields/rename", {
      method: "POST",
      body: JSON.stringify({ old_field_id: oldFieldId, new_field_id: newFieldId, entry_type: entryType }),
    });
  },
  deleteMetadataField(fieldId: string, entryType = "scene") {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "DELETE",
      body: JSON.stringify({ field_id: fieldId, entry_type: entryType }),
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
  saveScene(scene: Scene, bodyMarkdown: string) {
    return request<Scene>(`/scenes/${scene.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: scene.title,
        body_markdown: bodyMarkdown,
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
  createLoreEntry(title: string, entryType = "lore_note") {
    return request<LoreEntry>("/lore", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType }),
    });
  },
  getLoreEntry(entryId: string) {
    return request<LoreEntry>(`/lore/${entryId}`);
  },
  saveLoreEntry(entry: LoreEntry, bodyMarkdown: string) {
    return request<LoreEntry>(`/lore/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body_markdown: bodyMarkdown,
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
  savePromptEntry(entry: PromptEntry, bodyMarkdown: string) {
    return request<PromptEntry>(`/prompts/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body_markdown: bodyMarkdown,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
      }),
    });
  },
  deletePromptEntry(entryId: string) {
    return request<PromptEntryList>(`/prompts/${entryId}`, {
      method: "DELETE",
    });
  },
  listAssistantEntries() {
    return request<AssistantEntryList>("/assistants");
  },
  createAssistantEntry(title: string, layerId: string = "") {
    return request<AssistantEntry>("/assistants", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: "assistant", layer_id: layerId }),
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
  listChatSessions() {
    return request<ChatSessionList>("/chats");
  },
  createChatSession(payload: CreateChatSessionRequest = {}) {
    return request<ChatSession>("/chats", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getChatSession(chatId: string) {
    return request<ChatSession>(`/chats/${encodeURIComponent(chatId)}`);
  },
  saveChatSession(chatId: string, payload: SaveChatSessionRequest) {
    return request<ChatSession>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "PUT",
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
