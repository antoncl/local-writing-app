// The reverse-reference index (#184 Phase 2, ADR-0031 §14.4): invert the
// backend's forward adjacency (referrer id → target ids) into the
// `Map<targetId, Set<referrerId>>` the view evaluator's `references` computed
// field projects over (`field_of(set, "references")` → the set's referrers).
//
// Pure and framework-free so it is unit-testable and reusable by whatever loads
// it (the references store today). The evaluator only reads the map — it never
// mutates it — so the returned map's sets are the canonical membership.

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
