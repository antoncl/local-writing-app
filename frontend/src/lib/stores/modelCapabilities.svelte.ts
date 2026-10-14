// Per-provider model catalogue, answering "does this model claim tool support?"
// for the assistant lists (#2485). A purely informational lookup: an
// unreachable provider, a failed fetch, or a model not in the catalogue all
// answer `null` (unknown) — callers show nothing, and nothing here surfaces an
// error. The backend caches the catalogue; this cache is about not re-asking
// per row.
//
// One source: ProviderTierPicker primes it with every catalogue it loads (incl.
// a forced refresh), so the picker and the lists never disagree about a model.

import { api } from "@/lib/api";
import type { AIModelInfo } from "@/lib/aiTypes";

// All this cache reads off a catalogue row.
type ModelCaps = Pick<AIModelInfo, "id" | "capabilities">;

// A failed fetch is retried in the background rather than cached as unknown for
// the session — the provider (typically a local Ollama) may simply not be up
// yet. Backs off and then gives up, so a provider that is just absent isn't
// polled forever; a later `ensure()` (the list re-rendering) or a picker load
// still recovers it.
const RETRY_DELAYS_MS = [30_000, 60_000, 120_000];

// provider -> capability list per model id. Absent = not loaded.
let catalogue = $state<Record<string, Record<string, string[]>>>({});
// provider -> failed attempts in the current retry run.
const failures = new Map<string, number>();
const retryTimers = new Map<string, ReturnType<typeof setTimeout>>();
const inflight = new Map<string, Promise<void>>();

function scheduleRetry(provider: string): void {
  const attempt = failures.get(provider) ?? 0;
  const delay = RETRY_DELAYS_MS[attempt - 1];
  if (delay === undefined || retryTimers.has(provider)) return;
  retryTimers.set(
    provider,
    setTimeout(() => {
      retryTimers.delete(provider);
      if (!(provider in catalogue) && !inflight.has(provider)) startLoad(provider);
    }, delay),
  );
}

function startLoad(provider: string): Promise<void> {
  const p = load(provider);
  inflight.set(provider, p);
  return p;
}

function byId(models: ModelCaps[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const m of models) out[m.id] = m.capabilities;
  return out;
}

async function load(provider: string): Promise<void> {
  try {
    const list = await api.listAIProviderModels(provider);
    catalogue[provider] = byId(list.models);
    failures.delete(provider);
  } catch {
    failures.set(provider, (failures.get(provider) ?? 0) + 1);
    inflight.delete(provider);
    scheduleRetry(provider);
    return;
  }
  inflight.delete(provider);
}

export const modelCapabilities = {
  // Fetch every named provider's catalogue not loaded yet. Concurrent callers
  // share one request per provider; a provider in a background retry run is
  // left to it.
  ensure(providers: Iterable<string>): Promise<void> {
    const pending: Promise<void>[] = [];
    for (const provider of providers) {
      if (!provider || provider in catalogue || retryTimers.has(provider)) continue;
      pending.push(inflight.get(provider) ?? startLoad(provider));
    }
    return Promise.all(pending).then(() => {});
  },

  // Record a catalogue someone else already fetched (the picker).
  prime(provider: string, models: ModelCaps[]): void {
    if (!provider) return;
    catalogue[provider] = byId(models);
    failures.delete(provider);
    const timer = retryTimers.get(provider);
    if (timer !== undefined) clearTimeout(timer);
    retryTimers.delete(provider);
  },

  // true/false when the model is in a loaded catalogue; null when unknown.
  // The model id is matched exactly, as ProviderTierPicker does (`m.id === model`).
  supportsTools(provider: string, model: string): boolean | null {
    const caps = catalogue[provider]?.[model];
    return caps ? caps.includes("tools") : null;
  },

  // Test seam: forget everything.
  reset(): void {
    catalogue = {};
    failures.clear();
    for (const timer of retryTimers.values()) clearTimeout(timer);
    retryTimers.clear();
    inflight.clear();
  },
};
