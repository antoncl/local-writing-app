// NodePickerConfig `sources` <-> legacy `{kinds, entryTypes}` membership
// adapter (0.5.0 step 1, #78). The picker/tag-scope filtering has no evaluator
// yet: it still narrows by kind + exact entry_type. A degenerate source
// (kind-only, or a `type` / union-of-`type` leaf) encodes exactly that subset,
// so these two functions let the existing filtering keep working against the
// new stored shape. Mirrors the backend reducer in models.py
// (`_sources_membership` / `_membership_to_sources`).

import type { NodePickerConfig, ViewExpr, ViewRef, ViewSource, ViewSpec } from "@/lib/types";

/** A picker source that references a saved view node, vs. an inline ViewSpec.
 * ViewSpec always carries a `kind`; ViewRef carries only `view`. */
export function isViewRef(source: ViewSource): source is ViewRef {
  return "view" in source && !("kind" in source);
}

function exprEntryTypeLeaves(expr: ViewExpr | null | undefined): string[] | null {
  if (!expr) return null;
  // Only a STRING type leaf is a static entry_type whitelist; a promoted `{var}`
  // type leaf (#222) is a parameterized source with no degenerate reduction.
  if (typeof expr.type === "string") return [expr.type];
  if (expr.union && expr.union.length > 0 && expr.union.every((child) => typeof child.type === "string")) {
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

/** A source the checkbox tree can regenerate from `{kinds, entryTypes}` alone: a
 * ViewSpec that is kind-only or a degenerate `type` / union-of-`type` leaf.
 * Everything else — view-refs and richer inline exprs (`descendants_of`,
 * `intersect`, `difference`, …) — the tree cannot re-author, so it must be
 * carried through a re-encode verbatim rather than clobbered by the degenerate
 * rebuild (#94). */
function treeCanRepresent(source: ViewSource): boolean {
  if (isViewRef(source)) return false;
  return !source.expr || exprEntryTypeLeaves(source.expr) !== null;
}

/** Inverse of {@link pickerMembership}: one degenerate ViewSpec source per kind
 * (kind-only, a single `type` leaf, or a `union` of `type` leaves).
 * Deterministic so equal membership yields an equal source list.
 *
 * The checkbox-tree editor only authors these degenerate type-leaf sources, so
 * it re-encodes them wholesale on every toggle. `existing` carries the config's
 * current `sources` so any source the tree can't represent — saved-view refs
 * (#82 / ADR-0023) AND non-degenerate inline exprs (#94) — is PRESERVED across
 * that re-encode instead of silently dropped. */
export function membershipToSources(
  kinds: string[],
  entryTypes: Record<string, string[]>,
  existing?: ViewSource[] | null,
): ViewSource[] {
  const orderedKinds = Array.from(new Set([...kinds, ...Object.keys(entryTypes)]));
  const degenerate = orderedKinds.map((kind): ViewSpec => {
    const fqns = entryTypes[kind] ?? [];
    if (fqns.length === 0) return { kind };
    if (fqns.length === 1) return { kind, expr: { type: fqns[0] } };
    return { kind, expr: { union: fqns.map((f) => ({ type: f })) } };
  });
  const preserved = (existing ?? []).filter((s) => !treeCanRepresent(s));
  return [...degenerate, ...preserved];
}
