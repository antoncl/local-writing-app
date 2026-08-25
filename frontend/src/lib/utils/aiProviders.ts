// AI provider identity + "which providers are configured / addable / in scope"
// logic for the create-wizard's AI step (#547) and the Settings AI tab. Pure and
// dependency-free so the derivation is unit-tested; the frontend has no
// component-test infra, so this logic lives here rather than in the Svelte view.
//
// One model, no special cases: **every provider is a `ProviderDescriptor`**, and
// providers differ only in their *config options* — a cloud provider's credential
// is a secret API key; Ollama's is a URL (its host), and Ollama additionally
// offers a model-less reachability test. "Ollama is a host, not a key" is captured
// as `kind: "url"` on its descriptor, not as separate handling in the markup
// (#1417). Adding a provider is one entry in `PROVIDERS`, nothing else.
//
// There is no backend "configured providers" endpoint — the surfaces derive the
// set client-side from the machine-settings credentials they already hold. A
// secret provider is a *subscription you have* exactly when its key is non-empty;
// on read the backend masks a set key to "********", so any non-empty string
// counts. A URL provider ships a default and is always considered configured.

import type { AIPolicy, ProviderCredentialsView } from "@/lib/types";

export type ProviderOption = { id: string; label: string };

// A secret credential is a masked API key (password input); a url credential is a
// plain, non-sensitive host URL (text input). The kind drives the input widget,
// whether the value is shown at rest, and whether the slot is ever "unconfigured".
export type ProviderCredentialKind = "secret" | "url";

export type ProviderDescriptor = {
  id: string;
  label: string;
  field: keyof ProviderCredentialsView;
  kind: ProviderCredentialKind;
  placeholder: string;
  // A secret can be rotated and dropped (clearing the key drops the subscription);
  // a URL provider is always present (it has a baked default host) and is never
  // "removed" — you edit its host instead.
  removable: boolean;
  // Whether the provider offers a model-less reachability probe (Ollama's
  // `/ai/ollama/health`, #1380). It is *data on the descriptor*, not a branch in
  // the UI: a cloud provider that later gains a key-validation probe just flips
  // this on — "only Ollama has a Test button" stops being a special case.
  hasReachabilityTest: boolean;
};

// The supported providers, in display order. Add a provider here, not in markup.
export const PROVIDERS: ProviderDescriptor[] = [
  {
    id: "anthropic",
    label: "Anthropic",
    field: "anthropic_api_key",
    kind: "secret",
    placeholder: "sk-ant-…",
    removable: true,
    hasReachabilityTest: false,
  },
  {
    id: "openai",
    label: "OpenAI",
    field: "openai_api_key",
    kind: "secret",
    placeholder: "sk-…",
    removable: true,
    hasReachabilityTest: false,
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    field: "openrouter_api_key",
    kind: "secret",
    placeholder: "sk-or-…",
    removable: true,
    hasReachabilityTest: false,
  },
  {
    id: "ollama",
    label: "Ollama",
    field: "ollama_host",
    kind: "url",
    placeholder: "http://127.0.0.1:11434",
    removable: false,
    hasReachabilityTest: true,
  },
];

const BY_ID: Record<string, ProviderDescriptor> = Object.fromEntries(
  PROVIDERS.map((p) => [p.id, p]),
);

// Kept for the tier picker (`ProviderTierPicker`), which labels providers by id.
export const PROVIDER_DISPLAY_NAMES: Record<string, string> = Object.fromEntries(
  PROVIDERS.map((p) => [p.id, p.label]),
);

export function providerDescriptor(id: string): ProviderDescriptor | null {
  return BY_ID[id] ?? null;
}

export function providerField(id: string): keyof ProviderCredentialsView | null {
  return BY_ID[id]?.field ?? null;
}

export function providerPlaceholder(id: string): string {
  return BY_ID[id]?.placeholder ?? "";
}

// A provider counts as configured when its credential is present. A secret is
// present when its key is non-empty (the masked "********" read-back counts); a
// URL provider is ALWAYS configured — it ships a default host and the backend
// falls back to that default on a blank, so it is never an unconfigured slot.
export function isProviderConfigured(
  desc: ProviderDescriptor,
  providers: ProviderCredentialsView | null | undefined,
): boolean {
  if (desc.kind === "url") return true;
  return (providers?.[desc.field] ?? "").trim() !== "";
}

// Restrict the provider set to a scope. `allowed` is the set of provider ids a
// surface may show — the wizard passes the policy-derived scope; Settings passes
// nothing (all supported). Order follows `PROVIDERS`.
function scoped(allowed: string[] | undefined): ProviderDescriptor[] {
  if (!allowed) return PROVIDERS;
  const set = new Set(allowed);
  return PROVIDERS.filter((p) => set.has(p.id));
}

// The configured providers within scope — rendered as chips.
export function configuredProviders(
  providers: ProviderCredentialsView | null | undefined,
  allowed?: string[],
): ProviderOption[] {
  return scoped(allowed)
    .filter((p) => isProviderConfigured(p, providers))
    .map((p) => ({ id: p.id, label: p.label }));
}

// The addable providers within scope — offered under "+ Add provider". A URL
// provider is always configured, so it is never addable (you edit its chip).
export function addableProviders(
  providers: ProviderCredentialsView | null | undefined,
  allowed?: string[],
): ProviderOption[] {
  return scoped(allowed)
    .filter((p) => !isProviderConfigured(p, providers))
    .map((p) => ({ id: p.id, label: p.label }));
}

// The provider ids a project's AI policy permits *configuring* in the chooser.
// Broader than `eligibleProviders` (the send-path scope of already-*configured*
// providers): "off" allows none; "local-only" only Ollama; "cloud-allowed" every
// provider (cloud keys plus Ollama). Moving the policy slider up simply widens
// this set — that is all the slider does to the provider surface. "inherit" is
// folded to a concrete policy by the caller before this is read.
export function providersForPolicy(policy: AIPolicy): string[] {
  if (policy === "off") return [];
  if (policy === "local-only") return ["ollama"];
  return PROVIDERS.map((p) => p.id);
}

// ADR-0073 S2: the providers a *picker* may offer under a project's resolved AI
// policy + this machine's credentials — the same rule the backend send path
// enforces (`_policy_allows` in `services/ai/providers.py`). "off" offers
// nothing; "local-only" Ollama alone; "cloud-allowed" the configured cloud
// subscriptions first, then Ollama (always available — a host, not a key).
export function eligibleProviders(
  policy: AIPolicy,
  credentials: ProviderCredentialsView | null | undefined,
): string[] {
  if (policy === "off") return [];
  if (policy === "local-only") return ["ollama"];
  const cloud = PROVIDERS.filter(
    (p) => p.id !== "ollama" && isProviderConfigured(p, credentials),
  ).map((p) => p.id);
  return [...cloud, "ollama"];
}
