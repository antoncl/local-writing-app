// Color palette + resolver. Phase 1 of the color system: the palette is
// machine-wide state loaded from /api/settings/machine on app start. The
// resolver walks instance → type → kind-default → null; for Phase 1 only
// the kind-default leg is populated (Phase 2 adds type-level color on
// EntryTypeDefinition, Phase 2/4 adds instance overrides). The four
// kind-default ids preserve the historical `--ctx-k-*` values that the
// context picker used to hardcode, so day-one visuals don't shift.

import { writable, get } from "svelte/store";
import type { EntryTypeDefinition, MetadataSchema, Swatch } from "@/lib/types";

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
  // Chat is a Node kind like the rest and had no default here, so a chat row
  // resolved to null and showed no kind-stripe (ADR-0066 Amendment 1, decision
  // 5). Graphite matches the `--k-graphite /* chat */` token already reserved
  // for it in styles.css; it groups visually with the other tool/meta kinds.
  chat: "graphite",
  project: "violet",
  research: "teal",
  prompt: "indigo",
  mutation_set: "violet",
  plot: "plum",
  // A tag's own metadata.color (ADR-0082 slice 1) usually wins per-entry; this
  // is the fallback stripe for a tag row/chip with none set — neutral, like
  // the other tool/meta kinds (assistant/chat/preset) above.
  tag: "graphite",
};

export function resolveColorForKind(kind: string | null | undefined): Swatch | null {
  if (!kind) return null;
  const id = KIND_DEFAULT_SWATCH[kind];
  return id ? getSwatch(id) : null;
}

// Walk an entry-type's parent chain, returning the first non-null value `pick`
// yields (child wins). The one place the type-inheritance descent is expressed;
// `resolveColorForType` and `resolveTypeIcon` (fieldIcons.ts) both route through
// it so the walk — cycle guard included — lives once. The backend resolver
// already propagates inheritable attributes parent→child, so a single read
// usually suffices; we walk defensively for a schema consumed pre-resolve (raw
// layer file, etc.).
export function firstInEntryTypeChain<T>(
  entryTypeId: string | null | undefined,
  schema: MetadataSchema | null | undefined,
  pick: (def: EntryTypeDefinition) => T | null | undefined,
): T | null {
  if (!entryTypeId || !schema) return null;
  const seen = new Set<string>();
  let current: EntryTypeDefinition | undefined = schema.entry_types?.[entryTypeId];
  while (current && !seen.has(current.name + ":" + (current.parent ?? ""))) {
    seen.add(current.name + ":" + (current.parent ?? ""));
    const value = pick(current);
    if (value != null) return value;
    if (!current.parent) break;
    current = schema.entry_types?.[current.parent];
  }
  return null;
}

// The first explicit `color` swatch up an entry-type's parent chain, or null.
// A `color` id that doesn't resolve to a known swatch is skipped (the walk
// continues to the parent), so a stale swatch id never masks an ancestor's.
export function resolveColorForType(
  entryTypeId: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): Swatch | null {
  return firstInEntryTypeChain(entryTypeId, schema, (def) =>
    def.color ? getSwatch(def.color) : null,
  );
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
