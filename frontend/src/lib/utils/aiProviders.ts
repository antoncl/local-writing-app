// AI provider identity + "which providers are configured" logic for the
// create-wizard's AI step (#547) and anywhere else a provider chooser is shown.
// Pure and dependency-free so the configured/addable derivation is unit-tested;
// the frontend has no component-test infra, so this logic lives here rather than
// in the Svelte view.
//
// There is no backend "configured providers" endpoint — the wizard derives the
// set client-side from the machine-settings credentials it already holds. A
// cloud provider is a *subscription you have* exactly when its API key is
// non-empty; on read the backend masks a set key to "********", so any non-empty
// string counts as configured.

import type { AIPolicy, ProviderCredentialsView } from "@/lib/types";

export type ProviderOption = { id: string; label: string };

// Mirrors the backend PROVIDER_DISPLAY_NAMES (machine_settings.py) — kept small
// on purpose; the supported set is fixed and rarely changes.
export const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

// The cloud subscriptions shown as the segmented "Your subscriptions" control.
// Ollama is local (a host, not a key), handled separately under Local policy.
export const CLOUD_PROVIDERS = ["anthropic", "openai", "openrouter"] as const;

// The credential field each cloud provider's key lives in.
const CLOUD_KEY_FIELD: Record<string, keyof ProviderCredentialsView> = {
  anthropic: "anthropic_api_key",
  openai: "openai_api_key",
  openrouter: "openrouter_api_key",
};

// Placeholder hint per provider's key, echoing MachineSettingsDialog.
const CLOUD_KEY_PLACEHOLDER: Record<string, string> = {
  anthropic: "sk-ant-…",
  openai: "sk-…",
  openrouter: "sk-or-…",
};

export function cloudKeyField(providerId: string): keyof ProviderCredentialsView | null {
  return CLOUD_KEY_FIELD[providerId] ?? null;
}

export function cloudKeyPlaceholder(providerId: string): string {
  return CLOUD_KEY_PLACEHOLDER[providerId] ?? "";
}

// The configured cloud subscriptions — non-empty key ⇒ configured (masked
// "********" counts). These populate the segmented control.
export function configuredCloudProviders(
  providers: ProviderCredentialsView | null | undefined,
): ProviderOption[] {
  if (!providers) return [];
  return CLOUD_PROVIDERS.filter((id) => (providers[CLOUD_KEY_FIELD[id]] ?? "").trim() !== "").map(
    (id) => ({ id, label: PROVIDER_DISPLAY_NAMES[id] }),
  );
}

// The cloud providers offered under "+ Add provider": the supported set minus
// those already configured. The long list only appears here, behind the menu.
export function addableCloudProviders(
  providers: ProviderCredentialsView | null | undefined,
): ProviderOption[] {
  const configured = new Set(configuredCloudProviders(providers).map((option) => option.id));
  return CLOUD_PROVIDERS.filter((id) => !configured.has(id)).map((id) => ({
    id,
    label: PROVIDER_DISPLAY_NAMES[id],
  }));
}

// ADR-0073 S2: the providers a picker may offer under a project's resolved AI
// policy + this machine's credentials — the same rule the backend enforces
// (`_policy_allows` in `services/ai/providers.py`), re-derived here so the
// picker never shows a provider the send path would reject. "off" offers
// nothing; "local-only" offers Ollama alone (a host, not a key — always
// listed); "cloud-allowed" offers the configured cloud subscriptions first,
// then Ollama.
export function eligibleProviders(
  policy: AIPolicy,
  credentials: ProviderCredentialsView | null | undefined,
): string[] {
  if (policy === "off") return [];
  if (policy === "local-only") return ["ollama"];
  return [...configuredCloudProviders(credentials).map((option) => option.id), "ollama"];
}
