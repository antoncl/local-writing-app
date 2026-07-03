// NodePickerConfig `sources` <-> legacy `{kinds, entryTypes}` membership
// adapter (0.5.0 step 1, #78). The picker/tag-scope filtering has no evaluator
// yet: it still narrows by kind + exact entry_type. A degenerate source
// (kind-only, or a `type` / union-of-`type` leaf) encodes exactly that subset,
// so these two functions let the existing filtering keep working against the
// new stored shape. Mirrors the backend reducer in models.py
// (`_sources_membership` / `_membership_to_sources`).

import type { NodePickerConfig, ViewExpr, ViewSource, ViewSpec } from "@/lib/types";

function exprEntryTypeLeaves(expr: ViewExpr | null | undefined): string[] | null {
  if (!expr) return null;
  if (expr.type) return [expr.type];
  if (expr.union && expr.union.length > 0 && expr.union.every((child) => !!child.type)) {
    return expr.union.map((child) => child.type as string);
  }
  // Any richer expr can't be reduced to the degenerate subset without an
  // evaluator — treat as "kind only, no entry_type constraint".
  return null;
}

/** Read a config's `sources` back as the legacy `{kinds, entryTypes}` subset.
 * View-refs and non-degenerate exprs contribute their kind (when known) with no
 * entry_type constraint. */
export function pickerMembership(config: NodePickerConfig | null | undefined): {
  kinds: string[];
  entryTypes: Record<string, string[]>;
} {
  const kinds: string[] = [];
  const entryTypes: Record<string, string[]> = {};
  for (const source of config?.sources ?? []) {
    if (!("kind" in source) || !source.kind) continue; // view-ref: unresolved here
    if (!kinds.includes(source.kind)) kinds.push(source.kind);
    const leaves = exprEntryTypeLeaves(source.expr);
    if (leaves && leaves.length > 0) {
      const bucket = (entryTypes[source.kind] ??= []);
      for (const fqn of leaves) if (!bucket.includes(fqn)) bucket.push(fqn);
    }
  }
  return { kinds, entryTypes };
}

/** Inverse of {@link pickerMembership}: one degenerate ViewSpec source per kind
 * (kind-only, a single `type` leaf, or a `union` of `type` leaves).
 * Deterministic so equal membership yields an equal source list. */
export function membershipToSources(
  kinds: string[],
  entryTypes: Record<string, string[]>,
): ViewSource[] {
  const orderedKinds = Array.from(new Set([...kinds, ...Object.keys(entryTypes)]));
  return orderedKinds.map((kind): ViewSpec => {
    const fqns = entryTypes[kind] ?? [];
    if (fqns.length === 0) return { kind };
    if (fqns.length === 1) return { kind, expr: { type: fqns[0] } };
    return { kind, expr: { union: fqns.map((f) => ({ type: f })) } };
  });
}
