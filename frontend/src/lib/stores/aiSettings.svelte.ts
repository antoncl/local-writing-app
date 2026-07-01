// AI settings — owns the per-project AI policy/provider/model-class draft, the
// provider health-check, and the top-bar project-color dot that App used to
// carry directly. Extracted from App.svelte (#14 P0).
//
// Singleton rune controller (mirrors paneLayout / confirmService /
// projectChooser / projectSession): one app shell, one of each, so a
// module-level instance with rune fields is the idiomatic shape.
//
// The policy/provider/model-class fields are two-way bound by the Project pane
// (bind:aiPolicy={aiSettings.policy} …) — member-expression binds on $state
// class fields, the projectSession.machineSettingsDraft pattern.
//
// PROJECT IDENTITY (appState) stays in App: saving AI settings returns an
// updated ProjectInfo that must be written back onto App's appState, so the
// save injects `onProjectUpdated`. metadataSchema is read imperatively from its
// store (get) at color-refresh time, so this stays a plain .svelte.ts.

import { api } from "@/lib/api";
import { get } from "svelte/store";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { resolveColor } from "@/lib/utils/colors";
import type { AIHealthResponse, AIPolicy, ProjectInfo } from "@/lib/types";

class AISettings {
  // ---- Per-project AI settings draft (bound by the Project pane) ----
  policy: AIPolicy = $state("off");
  defaultProvider = $state("");
  defaultModelClass = $state("");

  // ---- Provider health check ----
  healthResult = $state<AIHealthResponse | null>(null);
  healthChecking = $state(false);

  // ---- Project-node color (top-bar switcher dot) ----
  // Refreshed on open; null until resolved.
  projectColor = $state<string | null>(null);

  // ---- Injected host hooks (set in App.onMount) ----
  // Wraps an action in App's run() so errors surface in App's `error`.
  run: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  setStatus: (message: string) => void = () => {};
  // True when a project is open — guards the save (no-op with no project).
  isProjectOpen: () => boolean = () => false;
  // Writes the saved ProjectInfo back onto App's appState (project identity
  // stays in App; saving AI settings returns a fresh project to fold in).
  onProjectUpdated: (project: ProjectInfo) => void = () => {};

  // Seed from a freshly opened project (replaces App's inline reset). Clears the
  // health result and color so nothing leaks across a project switch.
  seedFromProject(project: ProjectInfo): void {
    this.policy = project.ai_policy;
    this.defaultProvider = project.ai_default_provider ?? "";
    this.defaultModelClass = project.ai_default_model_class ?? "";
    this.healthResult = null;
    this.projectColor = null;
  }

  // Project-node color, surfaced on the top-bar switcher as a dot so the user
  // can tell at a glance which project they're in.
  async refreshProjectColor(): Promise<void> {
    try {
      const node = await api.getProjectNode();
      const instance = typeof node?.metadata?.color === "string" ? node.metadata.color : null;
      const swatch = resolveColor(instance, node?.entry_type, "project", get(metadataSchemaStore));
      this.projectColor = swatch?.hex ?? null;
    } catch {
      this.projectColor = null;
    }
  }

  async save(): Promise<void> {
    if (!this.isProjectOpen()) return;
    await this.run(async () => {
      const updatedProject = await api.updateProjectSettings({
        ai_policy: this.policy,
        ai_default_provider: this.defaultProvider || null,
        ai_default_model_class: this.defaultModelClass || null,
      });
      this.onProjectUpdated(updatedProject);
      this.policy = updatedProject.ai_policy;
      this.defaultProvider = updatedProject.ai_default_provider ?? "";
      this.defaultModelClass = updatedProject.ai_default_model_class ?? "";
      this.setStatus("Updated AI settings");
    });
  }

  async runHealthCheck(): Promise<void> {
    await this.run(async () => {
      this.healthChecking = true;
      try {
        this.healthResult = await api.aiHealth(this.defaultProvider || undefined);
      } finally {
        this.healthChecking = false;
      }
    });
  }
}

export const aiSettings = new AISettings();
