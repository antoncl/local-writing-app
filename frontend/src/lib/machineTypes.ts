// Machine-settings + provider-credentials wire types (#763.5). Extracted from
// types.ts to keep that barrel under the file-size cap; re-exported from
// `@/lib/types` so it stays the single import surface. A leaf module — nothing
// here is referenced back in types.ts.

import type { AIPolicy } from "./aiTypes";

export type ProviderCredentialsView = {
  anthropic_api_key: string;
  openai_api_key: string;
  openrouter_api_key: string;
  ollama_host: string;
};

export type RecentProject = {
  path: string;
  title: string;
  opened_at: string;
  // False when this recent now points outside the machine projects root (#441):
  // shown as unavailable — equivalent to a deleted folder — not offered to open.
  within_root: boolean;
};

export type Swatch = {
  id: string;
  label: string;
  hex: string;
};

// Per-user prose-presentation prefs (#127 / #575), applied as CSS vars on :root.
export type DisplaySettings = { ui_scale: number; paragraph_align: "left" | "justify"; paragraph_indent: boolean };

export type MachineSettingsView = {
  version: number;
  providers: ProviderCredentialsView;
  default_provider: string;
  default_models: Record<string, string>;
  default_projects_folder: string;
  recent_projects: RecentProject[];
  palette: Swatch[];
  display: DisplaySettings;
  // The application-global default AI policy (#746) — the chain's outermost
  // fallback. No "inherit": it IS the floor.
  ai_policy: AIPolicy;
  config_path: string;
};

export type MachineSettingsUpdate = {
  providers?: Partial<ProviderCredentialsView>;
  default_provider?: string;
  default_models?: Record<string, string>;
  default_projects_folder?: string;
  recent_projects?: RecentProject[];
  palette?: Swatch[];
  display?: DisplaySettings;
  ai_policy?: AIPolicy;
};

// Editor-side draft for MachineSettingsDialog. Flat (provider keys hoisted
// to top level) so two-way binding to inputs is straightforward; the parent
// reshapes into MachineSettingsUpdate at save time.
export type MachineSettingsDraft = {
  anthropic_api_key: string;
  openai_api_key: string;
  openrouter_api_key: string;
  ollama_host: string;
  default_provider: string;
  default_models: Record<string, string>;
  default_projects_folder: string;
  palette: Swatch[];
  display: DisplaySettings;
};
