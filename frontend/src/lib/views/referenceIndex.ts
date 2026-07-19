// The reverse-reference index (#184 Phase 2, ADR-0031 §14.4): invert the
// backend's forward adjacency (referrer id → target ids) into the
// `Map<targetId, Set<referrerId>>` the view evaluator's `references` computed
// field projects over (`field_of(set, "references")` → the set's referrers).
//
// Pure and framework-free so it is unit-testable and reusable by whatever loads
// it (the references store today). The evaluator only reads the map — it never
// mutates it — so the returned map's sets are the canonical membership.

import type { MetadataSchema } from "@/lib/types";

// The ids one node references through its `entity_ref` / `entity_ref_list`
// fields — the frontend mirror of the backend `_reference_edges_for_entry`
// (references.py), minus the field qualifier: the backend keeps edges
// field-qualified (#305), this only needs the target set (see below).
// Walks the node's entry_type field list, collecting the scalar
// ref and each list ref, deduped into a SET: only the ref *set* determines the
// reverse index, so reordering a list, editing a non-ref field, or a prose-only
// save all leave it identical. Used to change-gate the reverse-index refresh
// (#200) — a save whose forward-ref set is unchanged cannot move the reverse
// index, so the refetch (and the reactive storm a fresh Map identity triggers)
// is skipped. Empty when the node has no schema type, no schema, or no metadata.
export function forwardRefsOf(
  metadata: Record<string, unknown> | null | undefined,
  entryType: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): Set<string> {
  const refs = new Set<string>();
  if (!metadata || !entryType || !schema) return refs;
  const definition = schema.entry_types[entryType];
  if (!definition) return refs;
  for (const fieldId of definition.fields) {
    const field = schema.fields[fieldId];
    if (!field) continue;
    const value = metadata[fieldId];
    if (field.type === "entity_ref") {
      if (typeof value === "string" && value) refs.add(value);
    } else if (field.type === "entity_ref_list" && Array.isArray(value)) {
      for (const item of value) if (typeof item === "string" && item) refs.add(item);
    }
  }
  return refs;
}

// Two forward-ref sets are equivalent when they hold the same ids (order- and
// duplicate-insensitive, since both are Sets). The change-gate skips the refresh
// exactly when this holds across a save's before/after.
export function sameRefSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size !== b.size) return false;
  for (const id of a) if (!b.has(id)) return false;
  return true;
}

// Build the reverse index from forward adjacency. `forward[id]` lists the ids
// node `id` references; the result maps each referenced id → the set of nodes
// that reference it. Self-references are kept (a node can reference itself); an
// empty/missing target list contributes nothing.
export function buildReferenceIndex(
  forward: Record<string, string[]> | null | undefined,
): Map<string, Set<string>> {
  const reverse = new Map<string, Set<string>>();
  if (!forward) return reverse;
  for (const [referrer, targets] of Object.entries(forward)) {
    for (const target of targets ?? []) {
      if (!target) continue;
      let referrers = reverse.get(target);
      if (!referrers) {
        referrers = new Set<string>();
        reverse.set(target, referrers);
      }
      referrers.add(referrer);
    }
  }
  return reverse;
}

// Project the `references` computed field (ADR-0031 §14.4): the union of every
// node that references any id in `of`. This is the single implementation behind
// both `field_of(set, "references")` in the view evaluator and the backlinks
// panel (Phase 2c) — the panel projects the open node's referrers through this same
// helper. Reads the reverse index only (never mutates); an unloaded/missing index
// yields an empty set.
export function projectReferences(
  of: Iterable<string>,
  reverse: ReadonlyMap<string, ReadonlySet<string>> | null | undefined,
): Set<string> {
  const out = new Set<string>();
  if (!reverse) return out;
  for (const id of of) {
    const referrers = reverse.get(id);
    if (referrers) for (const r of referrers) out.add(r);
  }
  return out;
}
