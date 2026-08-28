// Stripe-colour resolution for context-picker rows (ADR-0066/0068) — the one
// curved kind-stripe a NodeRow carries. `resolveColor` walks instance → type →
// kind, so a node's own `metadata.color` wins over the type/kind default (#1520).
// Extracted from NodePicker.svelte (file-size cap) as pure, schema-parameterized
// helpers.

import { resolveColor } from "@/lib/utils/colors";
import type { MetadataSchema, StructureDocument, StructureNode } from "@/lib/types";

/** The resolved kind/sub-type hex for a ref, or null. No instance override. */
export function hexForRef(
  ref: { kind: string; entry_type?: string },
  schema: MetadataSchema | null | undefined,
): string | null {
  return resolveColor(null, ref.entry_type, ref.kind, schema)?.hex ?? null;
}

/** The stripe for a tree row keyed on entry_type alone (kind = the `kind:key`
 * prefix). A type with no colour (e.g. structural manuscript) yields null. */
export function stripeForType(
  entryType: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): string | null {
  if (!entryType) return null;
  return hexForRef({ kind: entryType.split(":")[0], entry_type: entryType }, schema);
}

/** Like stripeForType, but honours a node's own `metadata.color` (an instance
 * override) ahead of the type/kind default (#1520 — a custom-coloured node
 * otherwise showed the kind default). */
export function stripeForNode(
  instanceColor: string | null | undefined,
  entryType: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): string | null {
  const kind = entryType ? entryType.split(":")[0] : null;
  return resolveColor(instanceColor ?? null, entryType ?? null, kind, schema)?.hex ?? null;
}

type Coloured = { id: string; metadata?: Record<string, unknown> | null };

/** A ref → instance-colour index (`${kind}:${id}` → `metadata.color` swatch id),
 * built once from the sources a picker surface already holds. Chips and selector
 * members carry only a ref (id + kind), not the source entity, so they resolve
 * their own colour through this (the panels read the entity directly). Scenes are
 * keyed by scene_id — the canonical ref id. */
export function buildInstanceColorMap(sources: {
  loreEntries?: Coloured[];
  cardEntries?: Coloured[];
  structure?: StructureDocument | null;
}): Map<string, string> {
  const map = new Map<string, string>();
  const put = (kind: string, id: string | null | undefined, meta: Record<string, unknown> | null | undefined) => {
    const c = meta?.color;
    if (id && typeof c === "string") map.set(`${kind}:${id}`, c);
  };
  for (const e of sources.loreEntries ?? []) put("lore", e.id, e.metadata);
  for (const c of sources.cardEntries ?? []) put("plot", c.id, c.metadata);
  const walk = (n: StructureNode | undefined) => {
    if (!n) return;
    put("manuscript", n.scene_id, n.metadata);
    n.children?.forEach(walk);
  };
  walk(sources.structure?.root);
  return map;
}
