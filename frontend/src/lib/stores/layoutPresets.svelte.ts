// Named user layout presets for the tiled workspace shell (#155). A saved
// arrangement is an ergonomic preference, not project data, so the roster is
// GLOBAL (one localStorage key, shared across projects) — unlike the *current*
// layout, which persists per-project in workspaceLayout. Built-in presets
// (writing / schema / research) live in workspaceLayout.serialize; this owns
// only the user-created ones.
//
// A rune controller mirroring the paneViews persistence style: imperative
// save/apply/remove that read + write localStorage synchronously.

import { workspaceLayout } from "./workspaceLayout.svelte";
import { deserialize, type LayoutSnapshot } from "./workspaceLayout.serialize";

const STORAGE_KEY = "workspaceLayout.presets";

export type UserPreset = { name: string; snapshot: LayoutSnapshot };

class LayoutPresets {
  presets = $state<UserPreset[]>([]);

  // Load the saved roster from localStorage, dropping any entry whose snapshot
  // no longer validates (same tolerance as per-project restore).
  load(): void {
    let raw: string | null = null;
    try {
      raw = localStorage.getItem(STORAGE_KEY);
    } catch {
      raw = null;
    }
    if (!raw) {
      this.presets = [];
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      this.presets = [];
      return;
    }
    if (!Array.isArray(parsed)) {
      this.presets = [];
      return;
    }
    const out: UserPreset[] = [];
    for (const entry of parsed) {
      if (!entry || typeof entry !== "object") continue;
      const name = (entry as Record<string, unknown>).name;
      const snap = deserialize(JSON.stringify((entry as Record<string, unknown>).snapshot));
      if (typeof name === "string" && name.trim() && snap) out.push({ name, snapshot: snap });
    }
    this.presets = out;
  }

  #save(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.presets));
    } catch {
      // Storage disabled / quota — presets are best-effort.
    }
  }

  has(name: string): boolean {
    const key = name.trim().toLowerCase();
    return this.presets.some((p) => p.name.toLowerCase() === key);
  }

  // Capture the current workspace arrangement under `name`, replacing an
  // existing preset of the same name (case-insensitive).
  save(name: string): void {
    const trimmed = name.trim();
    if (!trimmed) return;
    const snapshot = workspaceLayout.snapshot();
    const key = trimmed.toLowerCase();
    const next = this.presets.filter((p) => p.name.toLowerCase() !== key);
    next.push({ name: trimmed, snapshot });
    next.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    this.presets = next;
    this.#save();
  }

  apply(name: string): void {
    const key = name.trim().toLowerCase();
    const preset = this.presets.find((p) => p.name.toLowerCase() === key);
    if (preset) workspaceLayout.applySnapshot(preset.snapshot);
  }

  remove(name: string): void {
    const key = name.trim().toLowerCase();
    this.presets = this.presets.filter((p) => p.name.toLowerCase() !== key);
    this.#save();
  }
}

export const layoutPresets = new LayoutPresets();
