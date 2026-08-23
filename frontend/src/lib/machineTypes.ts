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

// Which GitHub Releases channel this install follows for updates (ADR-0072 S6).
// `stable` = tagged releases; `nightly` = the rolling bleeding-edge prerelease.
export type UpdateChannel = "stable" | "nightly";

// The result of an update check (`GET /api/updates/check`, ADR-0072 S6). Mirrors
// the backend UpdateCheck: `reachable=false` is "couldn't check" (offline / rate-
// limited), never an error; `update_available` is only ever true on a positive
// comparison, so an unreachable check leaves it false. `latest`/`latest_url` are
// null when there's nothing newer to point at.
export type UpdateCheck = {
  channel: UpdateChannel;
  current_version: string;
  current_build: string | null;
  update_available: boolean;
  latest: string | null;
  latest_url: string | null;
  reachable: boolean;
  detail: string | null;
};

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
  // The update channel this install follows (ADR-0072 S6).
  update_channel: UpdateChannel;
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
  update_channel?: UpdateChannel;
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
  // The update channel (ADR-0072 S6). A plain preference — unlike ai_policy it
  // rides the batched Save, so it lives on the draft.
  update_channel: UpdateChannel;
};
