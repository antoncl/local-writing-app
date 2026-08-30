// The one and only HTTP client to the backend. Every request goes through
// `request` / `streamNdjson` below, which is what injects the open project's
// scope on the wire (`scopeHeaders`, #413) — a raw `fetch` from a component or
// store skips that and talks to the wrong project, invisibly. That boundary is
// enforced: `scripts/check_http_client.py` fails CI on any network primitive
// (`fetch` to a URL, `EventSource`, `WebSocket`, `XMLHttpRequest`, axios)
// outside this file (ADR-0056, #977). Add a method here; do not reach for the
// network anywhere else.
import type {
  AIChatRequest,
  AIChatResponse,
  AIContextPresetResponse,
  EntryPatchExtraction,
  AIGenerateRequest,
  AIHealthResponse,
  OllamaHostHealth,
  AIProviderList,
  AIProviderModelList,
  AITierResolution,
  AncestorCandidate,
  AppVersion,
  AssistantEntry,
  AssistantEntryList,
  AIPolicy,
  AIPreviewRequest,
  AIPreviewResponse,
  AIInvocation,
  AIInvocationList,
  CreateAIInvocationRequest,
  ChatSessionJournalEntry,
  ChangedPick,
  ChatUsage,
  AssistantTagList,
  AssistantTagsOverview,
  ChatSession,
  ChatSessionList,
  CreateChatSessionRequest,
  DirectoryEntry,
  DirectoryListing,
  DirectoryRoot,
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
  LooseScene,
  MoveLoreNoteToResearchResponse,
  MachineSettingsUpdate,
  MachineSettingsView,
  UpdateCheck,
  MetadataFieldDefinition,
  MetadataGroupDefinition,
  MetadataSchema,
  MetadataSchemaLayers,
  MetadataSchemaOverview,
  PathProbe,
  ProjectInfo,
  ProjectNode,
  ProspectiveProjectNode,
  ProjectValidation,
  PromotionTarget,
  PromotionPlan,
  SaveProjectNodeRequest,
  PromptEntry,
  PromptEntryList,
  SnippetDependents,
  PlotTemplate,
  PlotTemplateList,
  PlotBoardProjection,
  PlotBoard,
  PlotBoardLayout,
  CardEntry,
  CardList,
  PlotlineEntry,
  PlotlineList,
  MutationSetEntry,
  MutationSetEntryList,
  MutationSetRow,
  ReferenceCandidatesResponse,
  ReferenceGraphResponse,
  ReferenceResolveResponse,
  ResearchNote,
  Scene,
  SearchHit,
  Snapshot,
  SnapshotDetail,
  SnapshotDrift,
  SnapshotList,
  StructureDocument,
  StructureNodeDeletePreview,
  TodoDocument,
  CreateViewRequest,
  SaveViewRequest,
  ViewNode,
  ViewNodeList,
  ViewUiState,
} from "@/lib/types";

// Backend base URL. Defaults to a same-origin relative path (ADR-0072 §1): in
// the packaged product the backend serves this bundle, so `/api` reaches it
// with no baked-in address. Only the production build takes this default; both
// dev stacks bake an absolute VITE_API_BASE at build time (vite.config.js) —
// Anton's serve talks to :8787 cross-origin, `--mode claude` to its own derived
// backend port — so dev never proxies and streaming responses stay unbuffered.
const baseUrl = import.meta.env.VITE_API_BASE ?? "/api";

// A WebSocket URL for a backend path, derived from the same base the HTTP client
// uses so both dev (an absolute cross-origin base) and the packaged app (the
// relative same-origin `/api`) reach the backend. A relative base resolves
// against the page origin; either way http(s) swaps to ws(s).
function apiWsUrl(path: string): string {
  const url = new URL(`${baseUrl}${path}`, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

// Open the session-presence WebSocket (#1378). The raw socket primitive lives
// here with the rest of the backend transport — ADR-0056's http-client-guard
// keeps network I/O in this one module; the presence controller in
// lib/sessionPresence.ts only drives the returned socket's lifecycle.
export function openSessionPresenceSocket(): WebSocket {
  return new WebSocket(apiWsUrl("/session/live"));
}

// The open project's root, carried on every request so the backend resolves the
// request's scope from the request itself (#413 / ADR-0045) rather than from a
// process-wide record of what was last opened. Set on a successful open/create
// and overwritten on a switch (which is just another open); null before any
// project is open, so the machine-level surfaces run unbound. URL-encoded into
// the header so a non-ASCII folder name survives a latin-1 HTTP header.
//
// It is mirrored in `sessionStorage` (per browser tab) so the scope survives a
// re-instantiation of THIS module while the app stays mounted — a Vite hot update,
// or any other dev module re-eval — which would otherwise reset a bare module
// variable back to null while a project is still open and 409 "No project is open."
// the next project-scoped fetch (#965). sessionStorage is not module state, so a
// fresh instance recovers it. This is NOT the ambient current-project #413 removed:
// that was a backend process global answering "what did SOME request open"; this is
// per-tab frontend state answering "what did THIS tab open" — exactly the request's
// own scope (ADR-0045). Per-tab means a new tab correctly starts unscoped until it
// opens a project, and since the app never returns to a no-project state after the
// first open (a switch just overwrites), the stored value always names the tab's
// currently-open project.
const SCOPE_STORAGE_KEY = "lwa.projectScopeRoot";

function readStoredScopeRoot(): string | null {
  try {
    return sessionStorage.getItem(SCOPE_STORAGE_KEY);
  } catch {
    return null; // sessionStorage unavailable (some test / SSR environments)
  }
}

let projectScopeRoot: string | null = readStoredScopeRoot();

function setProjectScopeRoot(root: string | null): void {
  projectScopeRoot = root;
  try {
    if (root === null) sessionStorage.removeItem(SCOPE_STORAGE_KEY);
    else sessionStorage.setItem(SCOPE_STORAGE_KEY, root);
  } catch {
    // sessionStorage unavailable — the module variable still carries scope for
    // this instance's lifetime; only cross-re-instantiation recovery is lost.
  }
}

function scopeHeaders(): Record<string, string> {
  // Fall back to the stored value when the module variable was reset out from
  // under us (module re-eval) but the tab still has a project open (#965).
  const root = projectScopeRoot ?? readStoredScopeRoot();
  return root === null ? {} : { "X-Project-Root": encodeURIComponent(root) };
}

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

/** A caught client-side failure shipped to the backend error log (#386).
 * `context` names where it happened; `detail` carries a stack or extra text. */
export interface ClientErrorReport {
  message: string;
  context?: string;
  detail?: string;
}

// While a page-hide flush is in progress every save PUT is marked `keepalive` so
// the browser lets an in-flight request finish even as the tab closes (#369).
// It is a transient hint, not a mode: App toggles it around the (brief) flush,
// and a keepalive request the flag catches by accident is harmless — it only
// asks the browser not to abort the request on unload. Note the ~64KB keepalive
// body cap: a very large scene save can still be dropped on a hard kill (the
// irreducible residual tracked in #455). The `visibilitychange: hidden` trigger
// covers the common case regardless, because the page is still alive then to
// complete a normal-weight request.
let keepaliveSaves = false;
export function setKeepaliveSaves(active: boolean): void {
  keepaliveSaves = active;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    keepalive: options.keepalive ?? keepaliveSaves,
    headers: {
      "Content-Type": "application/json",
      ...scopeHeaders(),
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
    headers: { "Content-Type": "application/json", ...scopeHeaders() },
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
  // No `projects_base_folder` on create/open/settings (#429): the layer walk's
  // bound is the machine root, set once in machine settings for every project.
  // Sending it per project is what made every chain one hop long — the chooser
  // passed the folder it had just built the project inside, so every project
  // recorded its own parent as the bound.
  // `inherits` is the wizard's declaration (#318): the ancestor paths ticked in
  // the location step. Omitted (undefined) means "take the default" — every
  // ancestor project — while `[]` is a deliberate flat project (#425/#426).
  async createProject(rootPath: string, title: string, inherits?: string[]) {
    const info = await request<ProjectInfo>("/project/create", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath, title, inherits }),
    });
    // The wire scope for every subsequent request is this project's root (#413).
    setProjectScopeRoot(info.root_path);
    return info;
  },
  // The inheritable ancestors of a *prospective* project path — the wizard's
  // location step, which enumerates before the project (or its folder) exists.
  // Every row comes back `inherited=false`; the author ticks to build the list.
  prospectiveAncestorCandidates(rootPath: string) {
    return request<AncestorCandidate[]>(
      `/project/ancestor-candidates?path=${encodeURIComponent(rootPath)}`,
    );
  },
  // The wizard's review step (#318 slice 4): the project node's authored fields
  // resolved over the ticked ancestors before the project exists — merged
  // schema, inherited values, and the per-field source. `inherits` is the same
  // absolute candidate paths the location step produced.
  prospectiveProjectNode(rootPath: string, inherits: string[]) {
    return request<ProspectiveProjectNode>("/project/prospective-node", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath, inherits }),
    });
  },
  async openProject(rootPath: string) {
    const info = await request<ProjectInfo>("/project/open", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath }),
    });
    // Switching projects is just another open; overwrite the wire scope (#413).
    setProjectScopeRoot(info.root_path);
    return info;
  },
  // Ship a caught client-side error to the backend so it lands in the open
  // project's `errors.log` (#386). Deliberately bypasses `request()`: it must
  // not throw on a non-2xx (the route returns an empty 204) and it must never
  // fail the operation it is recording, so a down backend, an absent project, or
  // a network error is swallowed. `keepalive` lets a report survive page unload.
  async logClientError(report: ClientErrorReport): Promise<void> {
    try {
      await fetch(`${baseUrl}/log`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...scopeHeaders() },
        body: JSON.stringify(report),
        keepalive: true,
      });
    } catch {
      // Logging must never break the app — drop a failed report silently (#386).
    }
  },
  // Partial update, per field: an omitted key leaves that setting alone.
  // `inherits: []` is therefore a deliberate flat project, not "no opinion" —
  // which is what makes unticking the last layer expressible (#426).
  updateProjectSettings(updates: {
    // "inherit" clears the policy back to no-opinion so the layer chain
    // resolves it (#471); omitting the key leaves it unchanged.
    ai_policy?: AIPolicy | "inherit";
    inherits?: string[];
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
  getVersion() {
    return request<AppVersion>("/version");
  },
  // Poll GitHub Releases for a newer build on the configured channel (ADR-0072
  // S6). Never throws for "offline" — that comes back as `reachable: false`.
  checkForUpdate() {
    return request<UpdateCheck>("/updates/check");
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
  // `assistantId` targets a specific assistant so the check tests the one a
  // send will actually use — omit it and the backend resolves the topmost
  // assistant (the default smoke test in Machine Settings). #336.
  aiHealth(assistantId?: string, provider?: string, model?: string) {
    return request<AIHealthResponse>("/ai/health", {
      method: "POST",
      body: JSON.stringify({
        assistant_id: assistantId ?? null,
        provider: provider ?? null,
        model: model ?? null,
      }),
    });
  },
  // Model-less reachability probe of the Ollama host — "can this machine reach
  // the daemon / is the firewall open?" — tests the typed host so a user can
  // check before saving (#1380). Never throws for "offline"; that's `reachable:
  // false` with a hint.
  checkOllamaHost(host: string) {
    return request<OllamaHostHealth>("/ai/ollama/health", {
      method: "POST",
      body: JSON.stringify({ host }),
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
  getLooseScenes() {
    // Scene files on disk no manuscript node references — the import offer,
    // read on its own now (#635) rather than off the validation report.
    return request<LooseScene[]>("/structure/loose-scenes");
  },
  importLooseScenes(sceneIds: string[]) {
    return request<StructureDocument>("/structure/import-loose", {
      method: "POST",
      body: JSON.stringify({ scene_ids: sceneIds }),
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
  getAssistantTags() {
    return request<AssistantTagList>("/assistant-tags");
  },
  setAssistantTagColor(name: string, color: string | null) {
    return request<AssistantTagList>(`/assistant-tags/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ color }),
    });
  },
  getAssistantTagsOverview() {
    return request<AssistantTagsOverview>("/assistant-tags/overview");
  },
  mergeAssistantTags(sources: string[], target: string) {
    // Rename is a single-source merge, exactly like mergeTags (#247).
    return request<AssistantTagList>("/assistant-tags/merge", {
      method: "POST",
      body: JSON.stringify({ sources, target }),
    });
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
  setTagColor(name: string, color: string | null) {
    return request<KnownTags>("/tags/color", {
      method: "PUT",
      body: JSON.stringify({ name, color }),
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
  upsertMetadataField(layerId: string, fieldId: string, field: MetadataFieldDefinition, entryType = "manuscript:scene", allowExisting = true, optionMigration: Record<string, string> | null = null) {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, field_id: fieldId, field, entry_type: entryType, allow_existing: allowExisting, option_migration: optionMigration }),
    });
  },
  moveMetadataField(fieldId: string, targetLayerId: string, entryType = "manuscript:scene") {
    return request<MetadataSchema>("/metadata/schema/fields/move", {
      method: "POST",
      body: JSON.stringify({ field_id: fieldId, target_layer_id: targetLayerId, entry_type: entryType }),
    });
  },
  renameMetadataField(oldFieldId: string, newFieldId: string, entryType = "manuscript:scene") {
    return request<MetadataSchema>("/metadata/schema/fields/rename", {
      method: "POST",
      body: JSON.stringify({ old_field_id: oldFieldId, new_field_id: newFieldId, entry_type: entryType }),
    });
  },
  deleteMetadataField(fieldId: string, entryType = "manuscript:scene") {
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
  // Per-type field presentation override (#116): relabel / hide a field for
  // one entry type. `label`/`hidden` are the complete desired overlay — pass
  // null to clear an aspect; both empty drops the override.
  setEntryTypeFieldOverride(
    layerId: string,
    entryTypeId: string,
    fieldKey: string,
    override: { label?: string | null; hidden?: boolean | null },
  ) {
    return request<MetadataSchema>("/metadata/schema/entry-types/field-override", {
      method: "PUT",
      body: JSON.stringify({
        layer_id: layerId,
        entry_type_id: entryTypeId,
        field_key: fieldKey,
        label: override.label ?? null,
        hidden: override.hidden ?? null,
      }),
    });
  },
  listDirectories(path?: string) {
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    return request<DirectoryListing>(`/directories${query}`);
  },
  listDirectoryRoots() {
    return request<DirectoryRoot[]>("/directories/roots");
  },
  probeDirectory(path: string) {
    return request<PathProbe>(`/directories/probe?path=${encodeURIComponent(path)}`);
  },
  createDirectory(parent: string, name: string) {
    return request<DirectoryEntry>("/directories", {
      method: "POST",
      body: JSON.stringify({ parent, name }),
    });
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
  /** `dynamicContext` is the set of lore entries the prose editor detected in
   *  this body (#439). Read only by the automatic snapshot capture inside the
   *  save; omitted when no prose editor reported, which the backend treats as
   *  *not observed* rather than as empty. */
  saveScene(scene: Scene, body: string, dynamicContext?: string[]) {
    return request<Scene>(`/scenes/${scene.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: scene.title,
        body,
        base_revision: scene.revision,
        status: scene.status,
        entry_type: scene.entry_type,
        metadata: scene.metadata,
        ...(dynamicContext ? { dynamic_context: dynamicContext } : {}),
      }),
    });
  },
  deleteScene(sceneId: string) {
    return request<StructureDocument>(`/scenes/${sceneId}`, {
      method: "DELETE",
    });
  },
  // ---- scene snapshots (ADR-0043 / ADR-0044, #401) -------------------------
  listSnapshots(sceneId: string) {
    return request<SnapshotList>(`/scenes/${encodeURIComponent(sceneId)}/snapshots`);
  },
  /** The camera: an explicit, never-thinned capture. Carries the dynamic
   *  context so an author-invoked snapshot witnesses the same world an
   *  automatic one does. */
  captureSnapshot(sceneId: string, dynamicContext?: string[]) {
    return request<Snapshot>(`/scenes/${encodeURIComponent(sceneId)}/snapshots`, {
      method: "POST",
      ...(dynamicContext ? { body: JSON.stringify({ dynamic_context: dynamicContext }) } : {}),
    });
  },
  readSnapshot(sceneId: string, snapshotId: string) {
    return request<SnapshotDetail>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}`,
    );
  },
  /** The drift report alone (#583). Once the content diff (runs + fields + title)
   *  is computed client-side, this is the one half that stays on the server —
   *  the "now" witness needs resolved entity state — so it gets a slim call
   *  carrying the dynamic context the editor observed plus the scene's unsaved
   *  buffer (`metadata` + `body`, #581), so the now-witness resolves the same
   *  "now" the client-side field flip does instead of the ~6 s-stale disk copy.
   *  `null` dynamic context is "not observed", `[]` is "observed and empty" —
   *  the distinction the service turns on (#439). */
  snapshotDrift(
    sceneId: string,
    snapshotId: string,
    dynamicContext: string[] | null,
    metadata: Record<string, unknown>,
    body: string,
  ) {
    return request<SnapshotDrift>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/drift`,
      {
        method: "POST",
        body: JSON.stringify({ dynamic_context: dynamicContext, metadata, body }),
      },
    );
  },
  /** Captures the current state and restores, in ONE call. Never do this as a
   *  client-side capture-then-restore: the pair can half-fail into a snapshot
   *  nobody asked for and an author who cannot tell whether it worked (#395). */
  restoreSnapshot(sceneId: string, snapshotId: string) {
    return request<Scene>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/restore`,
      { method: "POST" },
    );
  },
  /** Finalize a roleplay scene (ADR-0070 S3): capture a `kept` safety-net
   *  snapshot, then replace the body with the AI-produced clean prose — in ONE
   *  call, the same #395 reason `restoreSnapshot` is (a client-side
   *  capture-then-write can half-fail). The AI generation ran beforehand through
   *  the ordinary generate path, so the finalize prompt stays author-
   *  customizable; this only commits the reviewed result. */
  finalizeScene(sceneId: string, body: string, dynamicContext?: string[]) {
    return request<Scene>(`/scenes/${encodeURIComponent(sceneId)}/finalize`, {
      method: "POST",
      body: JSON.stringify({ body, ...(dynamicContext ? { dynamic_context: dynamicContext } : {}) }),
    });
  },
  /** Pin an automatic snapshot: flip `retention` from thinned to kept so it
   *  survives thinning without re-capturing it (ADR-0043 Amendment 1).
   *  Idempotent — pinning an already-kept snapshot returns it unchanged. */
  pinSnapshot(sceneId: string, snapshotId: string) {
    return request<Snapshot>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/pin`,
      { method: "POST" },
    );
  },
  /** Set (or clear, with `""`) the snapshot's one-line description (#468).
   *  Writes the sidecar's authorial half only — the body and witness are
   *  frozen. */
  setSnapshotDescription(sceneId: string, snapshotId: string, description: string) {
    return request<Snapshot>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/description`,
      { method: "PUT", body: JSON.stringify({ description }) },
    );
  },
  /** Delete one snapshot — the feature's only irreversible gesture, which is
   *  why the surface confirms it (ADR-0043). Returns what remains, so the strip
   *  re-lists in one call. */
  deleteSnapshot(sceneId: string, snapshotId: string) {
    return request<SnapshotList>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}`,
      { method: "DELETE" },
    );
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
  // The entry's body with its whole-body code fence stripped (#1628), read-only —
  // fed into the standard revision review so the user commits or declines the
  // unwrap. 409s if the body is no longer a single wrapping fence.
  unwrapLoreCodeFencePreview(entryId: string) {
    return request<{ body: string }>(`/lore/${entryId}/unwrap-preview`);
  },
  // Fork-to-here (#313): copy an inherited lore entry down into the current
  // project, keeping its id, and stop inheriting it. Returns the now-local entry.
  forkLoreEntry(entryId: string) {
    return request<LoreEntry>(`/lore/${entryId}/fork`, { method: "POST" });
  },
  // `authoringLayerId` is ADR-0042's layer L (#314): the write target the rail
  // picker chose. `null` = no explicit target — the open project for a local
  // entry; for an *inherited* entry the backend then 409s rather than silently
  // rewriting ancestor canon. When set, `L == owning layer` edits the owning
  // file, `L < owning` writes a sparse override delta at L.
  // `clearOverrideFields` (#517 / create-project-wizard.md §8) names the fields
  // whose override row(s) to DROP at L, reverting them to the inherited value —
  // the explicit "unset ⇒ inherit" signal. The submitted `metadata` still carries
  // their overridden value; the backend drops the row regardless, which is what
  // distinguishes a reset from omitting the field (read as clear-to-empty).
  saveLoreEntry(
    entry: LoreEntry,
    body: string,
    authoringLayerId: string | null = null,
    clearOverrideFields: string[] = [],
  ) {
    return request<LoreEntry>(`/lore/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
        authoring_layer_id: authoringLayerId,
        clear_override_fields: clearOverrideFields,
      }),
    });
  },
  deleteLoreEntry(entryId: string) {
    return request<LoreEntryList>(`/lore/${entryId}`, {
      method: "DELETE",
    });
  },
  // ADR-0078 §2: the declared ancestor projects a node HERE may be promoted
  // into — empty for a flat project (no `inherits:` chain). Generic across
  // kinds; lore is the first caller (slice 2).
  promotionTargets() {
    return request<PromotionTarget[]>("/promotion/targets");
  },
  // Pure dry-run (ADR-0078 §9): the partition the commit would run, without
  // writing anything. Renders as the promote dialogue's three buckets.
  previewLorePromotion(entryId: string, targetLayerId: string) {
    return request<PromotionPlan>(`/lore/${entryId}/promote/preview`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  // Lift an owned lore entry into a declared ancestor project, keeping its id
  // (ADR-0078 §1/§2). Runs the same partition `previewLorePromotion` returned.
  // Refuses 409 if the entry is already inherited, 400 if the target isn't a
  // declared ancestor.
  promoteLoreEntry(entryId: string, targetLayerId: string) {
    return request<LoreEntry>(`/lore/${entryId}/promote`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  // ADR-0051 S4 / ADR-0067 S2: the commit runs as a cached CONTINUATION of the
  // chat itself — `chat_id` is the chat's real id, so the server reads back the
  // field set its lock render registered (ChatSession.field_contract_stored)
  // instead of rebuilding a separate contract, and reuses the cached system
  // prefix + lore rather than re-shipping the transcript fresh. Returns the
  // patch + cost.
  extractEntryPatch(
    nodeId: string,
    body: { messages: { role: string; content: string }[]; assistant_id: string | null; chat_id: string },
  ) {
    return request<EntryPatchExtraction>(`/ai/entry-patch/${encodeURIComponent(nodeId)}/extract`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  // Create-mode sibling — no node yet, so the target entry_type rides in the body.
  extractEntryDraft(
    entryType: string,
    body: { messages: { role: string; content: string }[]; assistant_id: string | null; chat_id: string },
  ) {
    return request<EntryPatchExtraction>("/ai/entry-draft/extract", {
      method: "POST",
      body: JSON.stringify({ entry_type: entryType, ...body }),
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
        // Round-trip the "show this prompt on…" allow-list so a body/inputs edit
        // never strips it (ADR-0054 §4/S4; no authoring UI yet).
        offer_on: entry.offer_on ?? [],
        // Round-trip the behavior contract (ADR-0065 S3 / ADR-0062 D3) — the
        // writer rebuilds front matter from these arguments (not a merge), so
        // omitting this silently wipes a forked prompt's output/commit config
        // on the next autosave.
        context_strategy: entry.context_strategy ?? null,
      }),
    });
  },
  deletePromptEntry(entryId: string) {
    return request<PromptEntryList>(`/prompts/${entryId}`, {
      method: "DELETE",
    });
  },
  // Clone a built-in Library prompt into the project as an editable copy
  // (ADR-0049 §5). Unlike lore's fork, this mints a NEW id and leaves the
  // shipped original in place; the returned entry is the local copy.
  forkPromptEntry(entryId: string) {
    return request<PromptEntry>(`/prompts/${entryId}/fork`, { method: "POST" });
  },
  // ADR-0078 §2/§9 slice 3: the prompt counterparts to previewLorePromotion /
  // promoteLoreEntry — same dry-run/commit shape, plus the §6 include-closure
  // cascade and §5 dynamic-reference list the plan carries for a prompt.
  previewPromptPromotion(entryId: string, targetLayerId: string) {
    return request<PromotionPlan>(`/prompts/${entryId}/promote/preview`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  promotePromptEntry(entryId: string, targetLayerId: string) {
    return request<PromptEntry>(`/prompts/${entryId}/promote`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  // The "used by N prompts / M chats" dependency counts for a snippet (ADR-0061
  // §5). Harmless for a non-snippet prompt (nothing includes it → 0/0), so the
  // caller shows the advisory only when a count is non-zero.
  getPromptDependents(entryId: string) {
    return request<SnippetDependents>(`/prompts/${entryId}/dependents`);
  },
  // Plot templates (ADR-0048 S4c) — the ADR-0049 Library's second tenant. Same
  // browse/read/clone shape as prompts: list the resolved shelf, read one (with
  // its fail-closed `editable` verdict), clone an inherited one into an owned
  // editable copy, save/delete owned clones (inherited → 409 backend-side).
  listPlotTemplates() {
    return request<PlotTemplateList>("/plot/templates");
  },
  // Blank-create an owned template (#918) — the non-fork path. The backend defaults
  // a blank title, so callers may omit it and let the writer rename in the editor.
  createPlotTemplate(title = "") {
    return request<PlotTemplate>("/plot/templates", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  },
  getPlotTemplate(entryId: string) {
    return request<PlotTemplate>(`/plot/templates/${entryId}`);
  },
  forkPlotTemplate(entryId: string) {
    return request<PlotTemplate>(`/plot/templates/${entryId}/fork`, { method: "POST" });
  },
  savePlotTemplate(entry: PlotTemplate, body: string) {
    return request<PlotTemplate>(`/plot/templates/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        template: entry.template,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  deletePlotTemplate(entryId: string) {
    return request<PlotTemplateList>(`/plot/templates/${entryId}`, { method: "DELETE" });
  },
  // The board's read model (ADR-0048 S7a): plotlines + cards (with their refs) +
  // the opaque layout, in one GET. Get-or-creates the `plot:board` singleton.
  getPlotBoardProjection() {
    return request<PlotBoardProjection>("/plot/board/projection");
  },
  // Persist the board layout (ADR-0048 S7c). PUT round-trips the opaque layout
  // dict with an optimistic base_revision; returns the board with its advanced
  // revision (the next save's base).
  savePlotBoard(payload: { base_revision: string; layout: PlotBoardLayout }) {
    return request<PlotBoard>("/plot/board", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  // Plot cards + plotlines (ADR-0048 S5a/S5b) — the board's content ops, wired in
  // S7d. Cards and plotlines share the `plot/` folder + a book-local layered CRUD;
  // the endpoint path is the only family discriminator (the backend enforces an
  // is_a family guard on each). Attach/detach have no endpoint of their own — they
  // are a saveCard that sets / clears the `scene` ref in `metadata` (ADR §1).
  // The flat card list — the context picker's plot-card roster (ADR-0074 slice 6),
  // over which a plotline's selector expands to its current cards. The board still
  // reads its card set via the projection; this is the light list a picker needs.
  listCards() {
    return request<CardList>("/plot/cards");
  },
  // Create a single unattached card — the board's direct-authoring entry point
  // (#793), the per-card inverse of seed. Returns the created card so the caller can
  // open it to name it. No scene → it projects homeless until attached / realized.
  // `id` is supplied only by undo-of-delete / redo-of-create (ADR-0053 §7), to
  // restore a card under its original identity so other cards' causal_links
  // reconnect; a collision 409s. Omitted for a normal create (backend mints).
  createCard(title: string, id?: string) {
    return request<CardEntry>("/plot/cards", {
      method: "POST",
      body: JSON.stringify(id ? { title, id } : { title }),
    });
  },
  getCard(entryId: string) {
    return request<CardEntry>(`/plot/cards/${entryId}`);
  },
  saveCard(entry: CardEntry, body: string) {
    return request<CardEntry>(`/plot/cards/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  deleteCard(entryId: string) {
    return request<CardList>(`/plot/cards/${entryId}`, { method: "DELETE" });
  },
  // Mint a scene from the card and attach it (ADR §1 *realize*). `parentId` places
  // the scene (null → the backend's first-container fallback). 409 if the card is
  // already attached (0..1 scene per card).
  realizeCard(entryId: string, parentId: string | null = null) {
    return request<CardEntry>(`/plot/cards/${entryId}/realize`, {
      method: "POST",
      body: JSON.stringify({ parent_id: parentId }),
    });
  },
  // Bulk inverse of realize (ADR §S5): one attached card per un-carded leaf scene,
  // in manuscript order. Idempotent — skips already-carded scenes.
  seedFromManuscript() {
    return request<CardList>("/plot/seed-from-manuscript", { method: "POST" });
  },
  // The plotline roster — the ReferencePicker's `plot` source (#742) and the
  // board's lanes both draw from this.
  listPlotlines() {
    return request<PlotlineList>("/plot/plotlines");
  },
  // Create an ad-hoc plotline (no template behind it) — the "New plotline" entry
  // point. Title only (colour + beats are authored afterward via savePlotline / the
  // board node); mirrors createCard. Returns the new node so the caller can place +
  // name it.
  // `id` is supplied only by undo/redo (ADR-0053 §7) to restore a plotline under
  // its original id so cards' beat_links + primary reconnect; a collision 409s.
  createPlotline(title: string, id?: string) {
    return request<PlotlineEntry>("/plot/plotlines", {
      method: "POST",
      body: JSON.stringify(id ? { title, id } : { title }),
    });
  },
  // Single plotline read/save/delete — the plotline document opener (#735): a
  // plotline backlink (a card's `plotline` ref) opens the thread in the editor to
  // rename / recolour / describe it. Book-local, so always editable (no Library
  // lock). Mirrors the card twins; delete returns the refreshed roster.
  getPlotline(entryId: string) {
    return request<PlotlineEntry>(`/plot/plotlines/${entryId}`);
  },
  savePlotline(entry: PlotlineEntry, body: string) {
    return request<PlotlineEntry>(`/plot/plotlines/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  deletePlotline(entryId: string) {
    return request<PlotlineList>(`/plot/plotlines/${entryId}`, { method: "DELETE" });
  },
  // Snapshot a Library template's beats into a new owned plotline (ADR-0048 §3;
  // ADR-0053 §1/§2 — a plotline IS a template instance). Lives among the template
  // routes backend-side; returns the created plotline so the caller can place + edit
  // it on the board (the S3 palette's instantiate gesture). An ad-hoc plotline is a
  // plain createPlotline (no template behind it).
  instantiatePlotTemplate(templateId: string) {
    return request<PlotlineEntry>(`/plot/templates/${templateId}/instantiate`, { method: "POST" });
  },
  // Reusable mutation sets (#62).
  listMutationSetEntries() {
    return request<MutationSetEntryList>("/mutation-sets");
  },
  createMutationSetEntry(payload: {
    title: string;
    target_entry_type: string;
    // ADR-0055 §3: optional entity pin (omit/"" ⇒ reusable template).
    target_entity?: string;
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
  // ADR-0055 §5: mark a pinned set placed — the single write-back apply gains
  // when the writer stamps a one-off into a scene. Rejected (400) for a reusable
  // set, which apply leaves untouched.
  placeMutationSet(entryId: string) {
    return request<MutationSetEntry>(`/mutation-sets/${entryId}/place`, { method: "POST" });
  },
  saveMutationSetEntry(entry: MutationSetEntry) {
    return request<MutationSetEntry>(`/mutation-sets/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        target_entry_type: entry.target_entry_type,
        target_entity: entry.target_entity,
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
  createAssistantEntry(title: string, layerId: string | null = null) {
    // `null` (the default the "+" button sends) = the local layer, i.e. the
    // open project — machine when no project is open. Assistants are a layered
    // kind (ADR-0039), so a new one belongs in the project you're working in,
    // not forced onto the machine roster (#1452). An explicit "" still targets
    // the machine layer (the wizard's cross-project hire).
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
  // `layerId` omitted ⇒ the LOCAL layer, which is what a curation gesture always
  // means (#332/#333): the open project states its own opinion about what it
  // inherits, and no ancestor file is touched. Pass "" for the machine layer.
  reorderAssistants(orderedIds: string[], layerId?: string) {
    return request<AssistantEntryList>("/assistants/order", {
      method: "POST",
      body: JSON.stringify({ layer_id: layerId ?? null, ordered_ids: orderedIds }),
    });
  },
  unlistAssistant(entryId: string, layerId?: string) {
    return request<AssistantEntryList>("/assistants/unlist", {
      method: "POST",
      body: JSON.stringify({ layer_id: layerId ?? null, entry_id: entryId }),
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
  // Lock-free ui write (ADR-0036). MERGES the given fields into the view's `ui`
  // blob (a `view_default_<kind>` id with no file yet materializes the system
  // default). Pass only the field you own — `collapsed` (fold state) or
  // `appearance` (ADR-0069) — and the backend leaves the other untouched, so the
  // two independent writers never clobber each other.
  updateViewUi(viewId: string, ui: Partial<ViewUiState>) {
    return request<ViewNode>(`/views/${encodeURIComponent(viewId)}/ui`, {
      method: "PUT",
      body: JSON.stringify({ ui }),
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
  // #1635: picked lore entries edited since the AI last saw them — feeds the
  // Context door's "· edited" marker on the auto-added panel.
  chatChangedPicks(chatId: string) {
    return request<{ picks: ChangedPick[] }>(`/chats/${encodeURIComponent(chatId)}/changed-picks`);
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
  referenceGraph() {
    return request<ReferenceGraphResponse>("/references/graph");
  },
};
