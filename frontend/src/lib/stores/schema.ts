// Schema domain store — the three coupled slices of the merged metadata schema:
// the effective schema (entry_types/fields/groups), the overview (per-field /
// per-type layer sources), and the layer list. All three come from one
// getMetadataSchemaOverview() payload and are kept in lockstep here. Lifted out
// of App.svelte for the #14 reactive state layer; `writable` for legacy-safe
// reads (see docs/frontend-architecture.md).
//
// The schema-authoring fallback (which entry_type/layer the editor points at)
// stays in App.svelte — it's UI-local authoring state, not server-mirrored.

import { derived, get, writable } from "svelte/store";
import { api } from "@/lib/api";
import type {
  MetadataSchema,
  MetadataSchemaLayer,
  MetadataSchemaOverview,
} from "@/lib/types";

export const metadataSchemaStore = writable<MetadataSchema | null>(null);
export const metadataSchemaOverviewStore = writable<MetadataSchemaOverview | null>(null);
export const metadataSchemaLayersStore = writable<MetadataSchemaLayer[]>([]);

// The project-local (nearest) schema layer is the last entry in the merged layer
// stack. One definition of that rule, so imperative and reactive readers cannot
// drift (#313).
function nearestLayerId(layers: MetadataSchemaLayer[]): string {
  return layers[layers.length - 1]?.id ?? "";
}

// Defaults for new types/fields land here, and authoring selection falls back to
// it. Reads the store live (`get`) so callers invoked right after a store set
// still see the fresh value (the `$store` alias lags a flush).
export function projectSchemaLayerId(): string {
  return nearestLayerId(get(metadataSchemaLayersStore));
}

// Reactive form for Svelte components deciding per-node provenance (#313): a node
// whose `source_layer_id` differs from this is inherited. Same rule as
// projectSchemaLayerId(), tracked so a component recomputes when the schema loads.
export const projectLayerIdStore = derived(metadataSchemaLayersStore, nearestLayerId);

// Fan one overview payload into all three slices. The single source of truth for
// keeping the trio coherent.
export function setSchemaOverview(overview: MetadataSchemaOverview): void {
  metadataSchemaOverviewStore.set(overview);
  metadataSchemaStore.set(overview.effective_schema);
  metadataSchemaLayersStore.set(overview.layers);
}

// Refresh the overview and return it so the caller can run its authoring
// fallback against the fresh payload (the `$:` aliases lag a flush).
export async function refreshSchema(): Promise<MetadataSchemaOverview> {
  const overview = await api.getMetadataSchemaOverview();
  setSchemaOverview(overview);
  return overview;
}

// Write-through for a mutation that returns the bare effective schema (not the
// overview). Updates only the effective slice; layer-changing mutations must
// still refresh the overview so the layer list / sources stay in sync.
export function setMetadataSchema(schema: MetadataSchema): void {
  metadataSchemaStore.set(schema);
}

export function clearSchema(): void {
  metadataSchemaStore.set(null);
  metadataSchemaOverviewStore.set(null);
  metadataSchemaLayersStore.set([]);
}
