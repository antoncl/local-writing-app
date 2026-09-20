// The reverse-reference index (#184 Phase 2, ADR-0031 §14.4): invert the
// backend's forward adjacency (referrer id → target ids) into the
// `Map<targetId, Set<referrerId>>` the view evaluator's `references` computed
// field projects over (`field_of(set, "references")` → the set's referrers).
//
// Pure and framework-free so it is unit-testable and reusable by whatever loads
// it (the references store today). The evaluator only reads the map — it never
// mutates it — so the returned map's sets are the canonical membership.

import { keyedListKeyMember, refMembersOf } from "@/lib/editor-core/keyedList";
import type { MetadataSchema, ReferenceGraphEdge } from "@/lib/types";

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
    } else if (field.type === "list" && Array.isArray(value)) {
      // A reference-keyed / ref-bearing list (#2067): a save that only edits an
      // item's ref/tag member changes the item, not the list identity, so the
      // change-gate must walk one level into each item to see it.
      const members = refMembersOf(field);
      if (members.length === 0) continue;
      for (const item of value) {
        if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
        const record = item as Record<string, unknown>;
        for (const member of members) {
          const memberValue = record[member.key];
          if (member.type === "entity_ref") {
            if (typeof memberValue === "string" && memberValue) refs.add(memberValue);
          } else if (member.type === "entity_ref_list" && Array.isArray(memberValue)) {
            for (const v of memberValue) if (typeof v === "string" && v) refs.add(v);
          }
        }
      }
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

// One row in a field-qualified reverse index: the entry holding the
// reference, and the field it references through. `KeyedReferrer` is kept as
// an alias — it named the same row shape before the field index widened
// beyond reference-keyed lists (#2075, ADR-0089 §6).
export type FieldReferrer = { referrerId: string; fieldId: string };
export type KeyedReferrer = FieldReferrer;

// Shared loop behind `buildReferrerFieldIndex` and `buildKeyedReferrerIndex`:
// invert the field-qualified `edges` into target id → referrer rows, keeping
// only edges whose field passes `keep` (all of them when omitted), and
// deduped per (referrer, field) so a list field naming the same target twice
// through the same field (e.g. a duplicate id in an `entity_ref_list` member)
// contributes one row.
function buildFieldReferrerIndex(
  edges: ReferenceGraphEdge[] | null | undefined,
  keep?: (fieldId: string) => boolean,
): Map<string, FieldReferrer[]> {
  const index = new Map<string, FieldReferrer[]>();
  if (!edges) return index;
  const seenByTarget = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (keep && !keep(edge.field_id)) continue;
    let seen = seenByTarget.get(edge.dst);
    if (!seen) {
      seen = new Set<string>();
      seenByTarget.set(edge.dst, seen);
    }
    const dedupeKey = `${edge.src}::${edge.field_id}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    const row: FieldReferrer = { referrerId: edge.src, fieldId: edge.field_id };
    const existing = index.get(edge.dst);
    if (existing) existing.push(row);
    else index.set(edge.dst, [row]);
  }
  return index;
}

// The field-qualified reverse index (#2067, ADR-0089 §6): target id → every
// entry that references it, tagged with the field the reference lives in.
// Unfiltered — every `entity_ref` / `entity_ref_list` field and every
// reference-keyed list counts, unlike `buildKeyedReferrerIndex` below. Feeds
// the References panel's per-field rows.
export function buildReferrerFieldIndex(
  edges: ReferenceGraphEdge[] | null | undefined,
): Map<string, FieldReferrer[]> {
  return buildFieldReferrerIndex(edges);
}

// The reverse index behind the delete-orphan warning (ADR-0089 §9): target id
// → every entry that holds a relationship item keyed by it. Built from the
// field-qualified `edges` (not `refs`, which drops the field), keeping only
// edges whose field is a reference-keyed list — an ordinary `entity_ref` /
// `entity_ref_list` field's edges are not item keys and would over-warn on an
// unrelated delete.
export function buildKeyedReferrerIndex(
  edges: ReferenceGraphEdge[] | null | undefined,
  schema: MetadataSchema | null | undefined,
): Map<string, KeyedReferrer[]> {
  if (!schema) return new Map();
  return buildFieldReferrerIndex(edges, (fieldId) => keyedListKeyMember(schema.fields[fieldId]) !== null);
}
