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
  // ADR-0082 §3: a tag chip resolves through the same instance-colour path
  // every other ref kind does, instead of the retired name-keyed tag map.
  tagEntries?: Coloured[];
}): Map<string, string> {
  const map = new Map<string, string>();
  const put = (kind: string, id: string | null | undefined, meta: Record<string, unknown> | null | undefined) => {
    const c = meta?.color;
    if (id && typeof c === "string") map.set(`${kind}:${id}`, c);
  };
  for (const e of sources.loreEntries ?? []) put("lore", e.id, e.metadata);
  for (const c of sources.cardEntries ?? []) put("plot", c.id, c.metadata);
  for (const t of sources.tagEntries ?? []) put("tag", t.id, t.metadata);
  const walk = (n: StructureNode | undefined) => {
    if (!n) return;
    put("manuscript", n.scene_id, n.metadata);
    n.children?.forEach(walk);
  };
  walk(sources.structure?.root);
  return map;
}

/** Title → hex for tag CHIPS (`NodeRow`'s `tagColor` prop) — a different
 * colour system from the picker's id-keyed instance map above (a Chip, not a
 * kind Stripe; #88). Title-keyed because `NodeRow.tags` already carries
 * titles, not ids (`tagTitleById`-resolved by the caller). Build from the
 * LIVE roster (ADR-0082 §5): a merged tag's own title never reaches a chip —
 * `tagTitleById` resolves it to the survivor's — so only survivors need an
 * entry here.
 *
 * Scoped to ONE vocabulary (`entryType`, an entry_type FQN): titles are only
 * unique within a vocabulary, not across the whole roster — a "Paris"
 * `tag:motifs` entry and an unrelated "Paris" `tag:tag` entry would otherwise
 * collide in one shared title-keyed map, and the second write silently wins.
 * Each caller passes its own field's vocabulary (the assistant-tag strip's
 * `tag:assistant_tag`, the general `tags` field's `tag:tag`, TagsPane's own
 * group's entry_type). */
export function tagChipHexByTitle(
  tags: { title: string; entry_type: string; metadata?: Record<string, unknown> | null }[],
  schema: MetadataSchema | null | undefined,
  entryType: string,
): Map<string, string> {
  const map = new Map<string, string>();
  for (const tag of tags) {
    if (tag.entry_type !== entryType) continue;
    const color = tag.metadata?.color;
    const hex = resolveColor(typeof color === "string" ? color : null, tag.entry_type, "tag", schema)?.hex;
    if (hex) map.set(tag.title, hex);
  }
  return map;
}
