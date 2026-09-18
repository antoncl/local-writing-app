// Layer-override authoring helpers (#314 / ADR-0042 / ADR-0039 slice E).
//
// The rail authoring-layer picker chooses L — the layer an inherited lore
// entry's edits write to. These are the two pure decisions behind it, factored
// out so they can be unit-tested (the frontend has no component-test infra, so
// UI logic worth pinning lives in a plain function — the same reason
// provenance.ts and projectChain.ts exist). The component keeps only the
// wiring: confirm-on-entry, the warn strip, and reporting L up to the pane.

import type { MetadataSchemaLayer } from "@/lib/types";

/**
 * The rest-position authoring layer L for a freshly-loaded entry.
 *
 * An *inherited* entry (its owning layer is above the open project) defaults to
 * overriding at the open project — the safe, local landing spot for a lazy edit
 * (ADR-0042: rest is local and safe, so laziness lands on the override and only
 * an explicit act reaches past it). A locally-owned entry has no override target
 * (`null` → the save goes to its own file).
 *
 * `openLayerId` is the open project's own layer id (the nearest merged schema
 * layer). Returns `null` — never a guess — while it is empty (schema not loaded).
 */
export function authoringDefaultLayerId(
  sourceLayerId: string | undefined | null,
  openLayerId: string,
): string | null {
  if (!openLayerId) return null;
  const inherited = Boolean(sourceLayerId) && sourceLayerId !== openLayerId;
  return inherited ? openLayerId : null;
}

/**
 * The layers L can target for an inherited entry: the owning layer down to the
 * open project, inclusive — ADR-0042's `owning ≤ L ≤ open project` — presented
 * **open-project-first** (the rest position at the top of the menu).
 *
 * `layers` is the merged schema-layer stack, outermost first / open project
 * last. `owningLayerId` is the entry's `source_layer_id`. Returns `[]` when the
 * owning layer is not in the stack (schema still loading) — the caller then
 * hides the picker rather than showing a truncated or empty menu.
 *
 * The bound is on the write *target* only: the candidate values a write may use
 * still resolve the full ancestor union base→L. That is the backend's concern;
 * this only orders the target menu.
 */
export function pickableAuthoringLayers(
  layers: MetadataSchemaLayer[],
  owningLayerId: string | undefined | null,
): MetadataSchemaLayer[] {
  if (!owningLayerId) return [];
  const owningIdx = layers.findIndex((layer) => layer.id === owningLayerId);
  if (owningIdx < 0) return [];
  return [...layers.slice(owningIdx)].reverse();
}

/**
 * The `?layer=` argument for a lore entry's node-snapshot routes: the authoring
 * layer when the entry is edited as an override *below* its owning layer, else
 * `null` — the base file's own history (ADR-0088 §6 / ADR-0087 §3b).
 *
 * The snapshot store co-locates with the file the write lands in (ADR-0087 §3),
 * so this must mirror the base-vs-override choice `saveLoreEntry` makes from the
 * same `authoringLayerId`: a base edit writes the owning-layer file (`null`), a
 * sparse override writes a delta at L (`L`). The one case the two diverge is
 * `L === owning layer` — a *direct canon edit* still writes the base file, and
 * `node_override_snapshot_kind` refuses an authoring layer that is not strictly
 * below the owning one, so it maps to `null`, never that layer id. A
 * locally-owned entry passes `authoringLayerId === null` and lands here as
 * `null` regardless.
 */
export function snapshotLayerId(
  authoringLayerId: string | null,
  owningLayerId: string | undefined | null,
): string | null {
  return authoringLayerId !== null && authoringLayerId !== owningLayerId ? authoringLayerId : null;
}
