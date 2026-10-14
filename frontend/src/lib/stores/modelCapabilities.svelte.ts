// Per-provider model catalogue, fetched once per session, answering "does this
// model claim tool support?" for the assistant lists (#2485). A purely
// informational lookup: an unreachable provider, a failed fetch, or a model not
// in the catalogue all answer `null` (unknown) — callers show nothing, and
// nothing here surfaces an error. The backend caches the catalogue, so the
// session cache is only about not re-asking per row.

import { api } from "@/lib/api";

// provider -> capability list per model id. `null` = the fetch failed (kept so
// we don't retry-spam a dead provider every render); absent = never asked.
let catalogue = $state<Record<string, Record<string, string[]> | null>>({});
const inflight = new Map<string, Promise<void>>();

async function load(provider: string): Promise<void> {
  try {
    const list = await api.listAIProviderModels(provider);
    const byId: Record<string, string[]> = {};
    for (const m of list.models) byId[m.id] = m.capabilities;
    catalogue[provider] = byId;
  } catch {
    catalogue[provider] = null;
  } finally {
    inflight.delete(provider);
  }
}

export const modelCapabilities = {
  // Fetch every named provider's catalogue that hasn't been asked for yet.
  // Concurrent callers share one request per provider.
  ensure(providers: Iterable<string>): Promise<void> {
    const pending: Promise<void>[] = [];
    for (const provider of providers) {
      if (!provider || provider in catalogue) continue;
      let p = inflight.get(provider);
      if (!p) {
        p = load(provider);
        inflight.set(provider, p);
      }
      pending.push(p);
    }
    return Promise.all(pending).then(() => {});
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
    inflight.clear();
  },
};
