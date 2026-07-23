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
import { projectChooser } from "@/lib/stores/projectChooser.svelte";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { loadProjectData } from "@/lib/stores/index";
import type {
  MachineSettingsDraft,
  MachineSettingsUpdate,
  MachineSettingsView,
  ProjectInfo,
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
      projectChooser.defaultProjectsFolder = this.machineSettings.default_projects_folder ?? "";
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
      projectChooser.defaultProjectsFolder = view.default_projects_folder ?? "";
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
      projectChooser.defaultProjectsFolder = this.machineSettings.default_projects_folder ?? "";
      setPalette(this.machineSettings.palette ?? []);
      this.machineSettingsOpen = false;
      this.setStatus("Saved machine settings");
    });
  }

  // ---- Project lifecycle entry points ----
  // Create a project at the given path with the given title. The layer walk's
  // bound is the machine root (#429), so creation neither takes nor sends one.
  async createProjectAt(path: string, title: string): Promise<void> {
    await this.run(async () => {
      const openedProject = await api.createProject(path, title);
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
