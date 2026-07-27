// Project session — owns the "which project + machine settings" layer that App
// used to carry directly: the machine-settings dialog state, the recent-projects
// list, the last-opened-project persistence, and the open/create/rehydrate flow.
// Extracted from App.svelte (#14 P0).
//
// Singleton rune controller (mirrors confirmService / projectChooser):
// one app shell, one of each, so a module-level instance with rune fields is the
// idiomatic shape. Not a writable store — traceable methods.
//
// PROJECT IDENTITY (appState / projectPath / projectTitle) deliberately STAYS in
// App: it's read pervasively across the markup and written from three sites
// (workspace open, AI-settings save, project-node save). The cross-subsystem
// workspace wiring (reset editor panes, AI settings, cost, color, chat hydration,
// pane fit/focus) also stays in App and is injected here as `onOpenWorkspace` —
// the same boundary the editorPanes controller draws for orchestration that's
// irreducibly coupled to App's many subsystems.

import { api } from "@/lib/api";
import { setPalette } from "@/lib/utils/colors";
import { get } from "svelte/store";
import { structureStore } from "@/lib/stores/structure";
import { isLeafNode } from "@/lib/utils/treeHelpers";
import { refreshAssistantEntries } from "@/lib/stores/assistants";
import { createWizard } from "@/lib/stores/createWizard.svelte";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { loadProjectData } from "@/lib/stores/index";
import type {
  AIPolicy,
  MachineSettingsDraft,
  MachineSettingsUpdate,
  MachineSettingsView,
  MetadataValue,
  ProjectInfo,
  ProviderCredentialsView,
  RecentProject,
  StructureNode,
} from "@/lib/types";

// Persisted "what was open" — survives reload (HMR or browser refresh) so the
// user doesn't lose their seat. Cleared on a failed re-open so a moved/deleted
// folder doesn't keep erroring every load.
const LAST_PROJECT_KEY = "lastOpenedProjectPath";

function findFirstSceneId(node: StructureNode | null | undefined): string | null {
  if (!node) return null;
  if (node.scene_id && isLeafNode(node)) return node.scene_id;
  for (const child of node.children ?? []) {
    const sceneId = findFirstSceneId(child);
    if (sceneId) return sceneId;
  }
  return null;
}

class ProjectSession {
  // ---- Machine settings ----
  machineSettings = $state<MachineSettingsView | null>(null);
  machineSettingsOpen = $state(false);
  machineSettingsDraft = $state<MachineSettingsDraft | null>(null);

  // Recent projects come from machine settings. Reloaded after open/create
  // (which push onto the recents list server-side) and after machine-settings
  // saves (which can change the default folder).
  recentProjects = $state<RecentProject[]>([]);

  // True for the whole of `setDeclaration` — the request AND the project-data
  // reload that follows it. The Project pane reads it to disable the
  // inheritance checkboxes, because a second tick mid-flight would be computed
  // from the enumeration the first one is about to replace (#426).
  declarationSaving = $state(false);

  // ---- Injected host hooks (set in App.onMount) ----
  // Wraps an action in App's run() so errors surface in App's `error`; returns
  // false when the action threw (used by rehydrate to detect a failed re-open).
  run: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  setStatus: (message: string) => void = () => {};
  // App's cross-subsystem workspace wiring (reset editor panes, AI settings,
  // cost, color, collapse, chat hydration, pane fit/focus). Runs BEFORE
  // loadProjectData, exactly as the inlined openProjectWorkspace did.
  onOpenWorkspace: (project: ProjectInfo) => void = () => {};
  // Runs AFTER loadProjectData — App syncs the schema-authoring selection.
  onProjectDataLoaded: () => void = () => {};
  // Writes an updated ProjectInfo back onto App's appState. Project identity
  // stays in App (the aiSettings controller injects the same hook), and a
  // declaration change returns a fresh enumeration the breadcrumb reads.
  onProjectUpdated: (project: ProjectInfo) => void = () => {};

  // ---- Last-opened-project persistence ----
  rememberLastProject(path: string): void {
    try {
      localStorage.setItem(LAST_PROJECT_KEY, path);
    } catch {
      // Storage disabled / quota — rehydrate just won't work; not fatal.
    }
  }

  forgetLastProject(): void {
    try {
      localStorage.removeItem(LAST_PROJECT_KEY);
    } catch {
      // ignore
    }
  }

  readLastProject(): string | null {
    try {
      return localStorage.getItem(LAST_PROJECT_KEY);
    } catch {
      return null;
    }
  }

  // ---- Machine settings: load / refresh / open / save ----
  async loadMachineSettings(): Promise<void> {
    try {
      this.machineSettings = await api.getMachineSettings();
      this.recentProjects = this.machineSettings.recent_projects ?? [];
      createWizard.defaultProjectsFolder = this.machineSettings.default_projects_folder ?? "";
      setPalette(this.machineSettings.palette ?? []);
    } catch {
      // Backend may be offline — leave machineSettings as null; pickers will
      // hide and the request falls back to the backend's default assistant.
    }
    // The file-backed assistant index is canonical for the chat-panel and
    // inputs-dialog pickers; load it eagerly alongside machine settings.
    await refreshAssistantEntries();
  }

  // Re-pull machine settings just to refresh the recents list. Called after
  // open/create routes — they touch_recent_project server-side; the UI needs
  // the new list to render the switcher dropdown.
  async refreshRecents(): Promise<void> {
    try {
      const view = await api.getMachineSettings();
      this.machineSettings = view;
      this.recentProjects = view.recent_projects ?? [];
      createWizard.defaultProjectsFolder = view.default_projects_folder ?? "";
      setPalette(view.palette ?? []);
    } catch {
      // Non-fatal — recents stays stale until next reload.
    }
  }

  async openMachineSettings(): Promise<void> {
    await this.run(async () => {
      const settings = await api.getMachineSettings();
      this.machineSettings = settings;
      this.machineSettingsDraft = {
        anthropic_api_key: settings.providers.anthropic_api_key,
        openai_api_key: settings.providers.openai_api_key,
        openrouter_api_key: settings.providers.openrouter_api_key,
        ollama_host: settings.providers.ollama_host,
        default_provider: settings.default_provider,
        default_models: { ...settings.default_models },
        default_projects_folder: settings.default_projects_folder ?? "",
        palette: (settings.palette ?? []).map((s) => ({ ...s })),
      };
      this.machineSettingsOpen = true;
    });
  }

  async saveMachineSettings(): Promise<void> {
    const draft = this.machineSettingsDraft;
    if (!this.machineSettings || !draft) return;
    await this.run(async () => {
      const update: MachineSettingsUpdate = {
        providers: {
          anthropic_api_key: draft.anthropic_api_key,
          openai_api_key: draft.openai_api_key,
          openrouter_api_key: draft.openrouter_api_key,
          ollama_host: draft.ollama_host,
        },
        default_provider: draft.default_provider,
        default_models: draft.default_models,
        default_projects_folder: draft.default_projects_folder,
        palette: draft.palette,
      };
      this.machineSettings = await api.updateMachineSettings(update);
      this.recentProjects = this.machineSettings.recent_projects ?? [];
      createWizard.defaultProjectsFolder = this.machineSettings.default_projects_folder ?? "";
      setPalette(this.machineSettings.palette ?? []);
      this.machineSettingsOpen = false;
      this.setStatus("Saved machine settings");
    });
  }

  // Serializes recents writes (#423 review). The switcher stays open to invite
  // clearing several dead rows in a burst, and each remove is a read-modify-write
  // of `recentProjects`; overlapping them would let two clicks both compute from
  // the pre-removal list, so the later server response resurrects a row the user
  // removed — and concurrent PUTs would also race the backend's load-modify-save
  // of config.yaml. Chaining makes each remove read the list only after the
  // previous write has landed.
  private recentsWrite: Promise<void> = Promise.resolve();

  // Forget one recents entry (#423). Recents is a machine-global MRU that can
  // outlive the projects it points at (moved, renamed, deleted, unmounted), and
  // a dead row is otherwise permanent — it fails every time it is clicked with
  // no way to clear it. This is an explicit user gesture, so we never guess at
  // liveness (that would mis-drop a project on a disconnected drive): send the
  // list minus this path and take the server's rewritten list as canonical.
  async removeRecentProject(path: string): Promise<void> {
    const chained = this.recentsWrite.then(() =>
      this.run(async () => {
        const next = this.recentProjects.filter((r) => r.path !== path);
        const view = await api.updateMachineSettings({ recent_projects: next });
        this.machineSettings = view;
        this.recentProjects = view.recent_projects ?? [];
      }),
    );
    // Absorb the boolean and any rejection so one failed write never poisons the
    // queue for later removes.
    this.recentsWrite = chained.then(
      () => undefined,
      () => undefined,
    );
    await this.recentsWrite;
  }

  // Open the create-project wizard, reading fresh machine settings first (#556).
  //
  // The wizard's `needsRootFolder` is derived from `createWizard
  // .defaultProjectsFolder`, which is otherwise only refreshed at app load /
  // save. If that value was cached empty (e.g. settings loaded before the
  // backend was ready) while the machine actually has a root configured, the
  // wizard would open showing the first-run root step and let the author
  // OVERWRITE their real root. Re-reading on open makes `needsRootFolder`
  // reflect the current backend state, so the root step appears only when the
  // root is genuinely unset. `loadMachineSettings` swallows a failed fetch
  // (backend offline) and leaves the last-known value, so the wizard still
  // opens — no worse than before.
  async startCreateWizard(): Promise<void> {
    await this.loadMachineSettings();
    createWizard.start();
  }

  // Set only the machine root, from the wizard's first-run step (#318). A
  // partial update: the server reads it with `exclude_unset`, so the other
  // machine settings are left untouched. Re-syncs `machineSettings` so the
  // wizard's `needsRootFolder` flips and step 1 gives way to step 2.
  async saveDefaultProjectsFolder(folder: string): Promise<void> {
    await this.run(async () => {
      this.machineSettings = await api.updateMachineSettings({ default_projects_folder: folder });
      createWizard.defaultProjectsFolder = this.machineSettings.default_projects_folder ?? "";
    });
  }

  // Write a single provider credential from the wizard's AI step (#547). Sparse
  // partial PUT: `merge_update` skips unsent fields and preserves masked ones,
  // so adding one key never clobbers the others. Re-syncs `machineSettings` so
  // the provider chooser's "configured" set updates reactively.
  async saveProviderCredential(
    field: keyof ProviderCredentialsView,
    value: string,
  ): Promise<void> {
    await this.run(async () => {
      this.machineSettings = await api.updateMachineSettings({ providers: { [field]: value } });
    });
  }

  // ---- Project lifecycle entry points ----
  // Create a project at the given path with the given title. The layer walk's
  // bound is the machine root (#429), so creation neither takes nor sends one.
  // `inherits` is the wizard's declaration (#318); omitted defaults to a flat
  // project (its call sites all pass an explicit list).
  //
  // `aiPolicy` (#547) is the wizard's chosen AI policy, applied right after
  // create: `POST /project/create` records the new scope, so the following
  // settings PATCH targets the new project. Undefined leaves no stated policy,
  // so the chain resolves it (§7's inheritance law) — the wizard passes it only
  // when the author overrode the inherited default with a concrete stop.
  async createProjectAt(
    path: string,
    title: string,
    inherits: string[] = [],
    aiPolicy?: AIPolicy,
    nodeMetadata: Record<string, MetadataValue> = {},
    description = "",
  ): Promise<void> {
    await this.run(async () => {
      let openedProject = await api.createProject(path, title, inherits);
      if (aiPolicy) {
        openedProject = await api.updateProjectSettings({ ai_policy: aiPolicy });
      }
      // The review pane's overrides + blurb (#318 slice 4), written into the new
      // book's `project.md` before the workspace loads so the first render sees
      // them. Both target the just-created project (create recorded the scope,
      // like the aiPolicy PATCH above). Only fields the author set are sent —
      // everything else stays absent and inherits.
      await this.#applyProjectNodeDraft(nodeMetadata, description);
      this.rememberLastProject(openedProject.root_path);
      this.onOpenWorkspace(openedProject);
      await loadProjectData();
      this.onProjectDataLoaded();
      const initialSceneId = findFirstSceneId(get(structureStore)?.root);
      if (initialSceneId) {
        await editorPanes.openScene(initialSceneId);
      }
      await this.refreshRecents();
      this.setStatus(`Created ${openedProject.title}`);
    });
  }

  // Write the wizard's review overrides + description into the just-created
  // project node (#318 slice 4). A no-op when the author accepted every default
  // and skipped the blurb — a fresh node already carries `metadata: {}` and an
  // empty body. `saveProjectNode` needs the node's revision, so read it first;
  // the overrides layer onto its (empty) metadata, absence meaning inherit.
  async #applyProjectNodeDraft(
    metadata: Record<string, MetadataValue>,
    description: string,
  ): Promise<void> {
    const hasMetadata = Object.keys(metadata).length > 0;
    const hasDescription = description.trim().length > 0;
    if (!hasMetadata && !hasDescription) return;
    const node = await api.getProjectNode();
    await api.saveProjectNode(
      { ...node, metadata: { ...node.metadata, ...metadata } },
      hasDescription ? description : node.body,
    );
  }

  // Returns false when the open failed (App's run() swallows the error), so
  // rehydrate can forget a moved/deleted last-opened path.
  async openProjectAt(path: string): Promise<boolean> {
    // Opening another project tears the editor surface down (`editorPanes
    // .reset()` via App's `resetEditorWorkspace`), so anything still inside the
    // 6s autosave debounce would go with it. Persist first, and refuse the
    // switch if that fails — #310 made this reachable in one click from the
    // child roster, but the switcher and the recents menu always had it.
    if (!(await editorPanes.flushDirtyPanes())) {
      this.setStatus("Unsaved changes could not be saved — staying in this project.");
      return false;
    }
    return await this.run(async () => {
      const openedProject = await api.openProject(path);
      this.rememberLastProject(openedProject.root_path);
      this.onOpenWorkspace(openedProject);
      await loadProjectData();
      this.onProjectDataLoaded();
      await this.refreshRecents();
      this.setStatus(`Opened ${openedProject.title}`);
    });
  }

  // Rewrite this project's `inherits:` declaration (#426).
  //
  // It lives here rather than on aiSettings because of the second half: the
  // declaration decides which projects the merged schema, the node index, the
  // tag registry and the lore roster are assembled from, so the response's
  // fresh ProjectInfo is not enough — every project-scoped store has to be
  // re-pulled. That is `loadProjectData`, which this controller already owns.
  //
  // What it deliberately does NOT do is `onOpenWorkspace`. This is the same
  // project, still open: tearing down the editor panes and the layout on a
  // checkbox click would discard the reason the author is looking at the pane.
  // Nothing here changes the resolution scope, so it is not a unit boundary
  // (ADR-0045) — only the layers behind it.
  //
  // Rejects an overlapping call rather than queueing it: each request is
  // derived from the enumeration on screen, so a second one issued mid-flight
  // would compute from a stale one and undo the first. `declarationSaving`
  // disables the boxes, and the pane puts the rejected box back.
  async setDeclaration(paths: string[]): Promise<boolean> {
    if (this.declarationSaving) return false;
    this.declarationSaving = true;
    try {
      return await this.run(async () => {
        const updatedProject = await api.updateProjectSettings({ inherits: paths });
        this.onProjectUpdated(updatedProject);
        await loadProjectData();
        this.onProjectDataLoaded();
        this.setStatus(
          paths.length === 0
            ? "Inherits from nothing"
            : `Inherits from ${paths.length} ${paths.length === 1 ? "level" : "levels"}`,
        );
      });
    } finally {
      this.declarationSaving = false;
    }
  }

  // Eagerly fetch machine settings (so the chat panel + inputs dialog can show
  // the assistant roster without a round-trip), then auto-rehydrate the
  // last-opened project so an HMR reload / plain F5 doesn't drop the user back
  // to "No project open." Run after machine settings so recents are populated.
  async rehydrate(): Promise<void> {
    await this.loadMachineSettings();
    const lastPath = this.readLastProject();
    if (lastPath) {
      const opened = await this.openProjectAt(lastPath);
      if (!opened) {
        this.forgetLastProject();
      }
    }
  }
}

export const projectSession = new ProjectSession();
