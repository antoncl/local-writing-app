// AI settings — owns the per-project AI policy draft, the provider
// health-check, and the top-bar project-color dot that App used to carry
// directly. Extracted from App.svelte (#14 P0).
//
// Singleton rune controller (mirrors confirmService /
// projectChooser / projectSession): one app shell, one of each, so a
// module-level instance with rune fields is the idiomatic shape.
//
// `policy` is two-way bound by the Project pane
// (bind:aiPolicy={aiSettings.policy}) — a member-expression bind on a $state
// class field, the projectSession.machineSettingsDraft pattern. It is the only
// per-project AI setting left; the provider / model-class pair that used to sit
// beside it was write-only and was retired in #330.
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
      });
      this.onProjectUpdated(updatedProject);
      this.policy = updatedProject.ai_policy;
      this.setStatus("Updated AI settings");
    });
  }

  // No provider argument: the ping resolves the same way a send with no
  // assistant does — the topmost assistant in the roster (ADR-0024) supplies
  // both provider and model. Passing a provider override (what the retired
  // project preference did) overrode *only* the provider, leaving the model
  // from that assistant, so the ping could exercise a provider/model pair no
  // send would ever make. This checks the default assistant, not whichever
  // assistant a given chat is pinned to — see #336.
  async runHealthCheck(): Promise<void> {
    await this.run(async () => {
      this.healthChecking = true;
      try {
        this.healthResult = await api.aiHealth();
      } finally {
        this.healthChecking = false;
      }
    });
  }
}

export const aiSettings = new AISettings();
