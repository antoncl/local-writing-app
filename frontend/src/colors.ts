// Color palette + resolver. Phase 1 of the color system: the palette is
// machine-wide state loaded from /api/settings/machine on app start. The
// resolver walks instance → type → kind-default → null; for Phase 1 only
// the kind-default leg is populated (Phase 2 adds type-level color on
// EntryTypeDefinition, Phase 2/4 adds instance overrides). The four
// kind-default ids preserve the historical `--ctx-k-*` values that the
// context picker used to hardcode, so day-one visuals don't shift.

import { writable, get } from "svelte/store";
import type { EntryTypeDefinition, MetadataSchema, Swatch } from "./types";

export const paletteStore = writable<Swatch[]>([]);

let byId: Record<string, Swatch> = {};
paletteStore.subscribe((swatches) => {
  byId = Object.fromEntries(swatches.map((s) => [s.id, s]));
});

export function setPalette(swatches: Swatch[]): void {
  paletteStore.set(swatches.slice());
}

export function getPalette(): Swatch[] {
  return get(paletteStore);
}

export function getSwatch(id: string | null | undefined): Swatch | null {
  if (!id) return null;
  return byId[id] ?? null;
}

// Phase 1 kind-default mapping. Replaced in Phase 2 by a per-type
// `color` field on EntryTypeDefinition that the resolver walks via the
// parent chain. Until then, this table keeps the context picker's
// chip/monogram colors identical to the legacy hardcoded values in
// NodePicker.svelte's `--ctx-k-*` block (now removed).
const KIND_DEFAULT_SWATCH: Record<string, string> = {
  scene: "forest",
  lore: "slate-blue",
  snippet: "warm-brown",
  preset: "graphite",
  assistant: "graphite",
  project: "violet",
  research: "teal",
  prompt: "indigo",
};

export function resolveColorForKind(kind: string | null | undefined): Swatch | null {
  if (!kind) return null;
  const id = KIND_DEFAULT_SWATCH[kind];
  return id ? getSwatch(id) : null;
}

// Walk an entry-type's parent chain looking for an explicit `color` swatch
// id. The backend resolver already propagates `color` from parent to child
// through `_resolve_metadata_schema_inheritance`, so a single read on the
// passed-in entry type should be enough — but we walk defensively in case
// the schema is consumed before the resolver ran (raw layer file, etc.).
export function resolveColorForType(
  entryTypeId: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): Swatch | null {
  if (!entryTypeId || !schema) return null;
  const seen = new Set<string>();
  let current: EntryTypeDefinition | undefined = schema.entry_types?.[entryTypeId];
  while (current && !seen.has(current.name + ":" + (current.parent ?? ""))) {
    seen.add(current.name + ":" + (current.parent ?? ""));
    if (current.color) {
      const swatch = getSwatch(current.color);
      if (swatch) return swatch;
    }
    if (!current.parent) break;
    current = schema.entry_types?.[current.parent];
  }
  return null;
}

// Full instance → type → parent → kind-default resolver. Pass the entry's
// metadata.color (if present) as `instanceSwatchId`. Returns null only when
// nothing in the chain yields a swatch and the kind has no default either.
export function resolveColor(
  instanceSwatchId: string | null | undefined,
  entryTypeId: string | null | undefined,
  kind: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): Swatch | null {
  const instance = getSwatch(instanceSwatchId);
  if (instance) return instance;
  const typeResolved = resolveColorForType(entryTypeId, schema);
  if (typeResolved) return typeResolved;
  return resolveColorForKind(kind);
}

// Render a hex into a soft tinted background via color-mix. Returns a
// CSS string suitable for `background:` / `--var:` values. Falls back
// gracefully on older browsers (color-mix has wide support, but old
// Safari needs the raw hex).
export function softTint(hex: string, mix = 88): string {
  return `color-mix(in srgb, ${hex} ${100 - mix}%, white ${mix}%)`;
}

// Same as softTint but suitable for dark backgrounds.
export function darkSoftTint(hex: string, mix = 80): string {
  return `color-mix(in srgb, ${hex} ${100 - mix}%, black ${mix}%)`;
}
