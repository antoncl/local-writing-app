import type {
  AncestorCandidate,
  AppVersion,
  AIPolicy,
  DirectoryEntry,
  DirectoryListing,
  DirectoryRoot,
  MachineSettingsUpdate,
  MachineSettingsView,
  UpdateCheck,
  PathProbe,
  ProjectInfo,
  ProjectNode,
  ProspectiveAiPolicy,
  ProspectiveProjectNode,
  ProjectValidation,
  SaveProjectNodeRequest,
} from "@/lib/types";
import { request, setProjectScopeRoot, baseUrl, scopeHeaders, type ClientErrorReport } from "./core";

export const projectApi = {
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
  // The wizard's AI step (#1672): the policy a prospective project would inherit
  // over the ticked ancestors, plus its provenance — so "inherit" names its value
  // and where it comes from. Same request shape as the review node.
  prospectiveAiPolicy(rootPath: string, inherits: string[]) {
    return request<ProspectiveAiPolicy>("/project/prospective-ai-policy", {
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
  // Open the app-data (logs) folder in the OS file manager (#1749). Loopback-only
  // on the backend; the caller also hides the trigger off-localhost.
  revealLogs() {
    return request<{ config_dir: string }>("/settings/machine/reveal-logs", { method: "POST" });
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
};
