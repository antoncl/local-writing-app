// NodePickerConfig `sources` <-> legacy `{kinds, entryTypes, families}` membership
// adapter (0.5.0 step 1, #78; tri-state #1947). The picker/tag-scope filtering
// narrows by kind + entry_type, where each scoped type is EXACT (`{type: fqn}`)
// or FAMILY (`{descendants_of: fqn}`, self + subtypes) — the ADR-0074 Amendment 4
// tri-state. A degenerate source (kind-only, or a `type`/`descendants_of` leaf, or
// a union of those) encodes exactly that subset, so these functions let the
// existing filtering + the checkbox tree work against the stored shape. Mirrors
// the backend reducer in models.py (`_sources_membership`/`_membership_to_sources`).

import type { NodePickerConfig, ViewExpr, ViewRef, ViewSource, ViewSpec } from "@/lib/types";

/** A picker source that references a saved view node, vs. an inline ViewSpec.
 * ViewSpec always carries a `kind`; ViewRef carries only `view`. */
export function isViewRef(source: ViewSource): source is ViewRef {
  return "view" in source && !("kind" in source);
}

/** One entry-type leaf reduced from a degenerate source: the FQN and whether it
 * is a FAMILY scope (`{descendants_of}`, self + subtypes) or EXACT (`{type}`). */
export type TypeLeaf = { fqn: string; family: boolean };

/** The type/descendants_of leaf of a single expr node, or null when it is neither
 * (a combinator, a promoted `{var}` leaf — #222 — a field predicate, …). Only a
 * STRING operand is a static entry_type; a `{var}` is a parameterized source. */
function leafOf(expr: ViewExpr): TypeLeaf | null {
  if (typeof expr.type === "string") return { fqn: expr.type, family: false };
  if (typeof expr.descendants_of === "string") return { fqn: expr.descendants_of, family: true };
  return null;
}

/** Reduce a source's expr to its degenerate entry-type whitelist, per fqn tagged
 * exact vs family: a bare `{type}`/`{descendants_of}` leaf, or a `union` whose
 * children are each such a leaf (a MIXED union of both is legal — one kind can
 * hold exact and family leaves side by side). Any richer expr (a `{var}` leaf, or
 * an `intersect`/`filter`/`difference` — a `descendants_of` BURIED in one of those
 * is not degenerate) can't be reduced without an evaluator ⇒ null ("kind only, no
 * entry_type constraint", and preserved verbatim by the tree). */
function exprEntryTypeLeaves(expr: ViewExpr | null | undefined): TypeLeaf[] | null {
  if (!expr) return null;
  const direct = leafOf(expr);
  if (direct) return [direct];
  if (expr.union && expr.union.length > 0) {
    const leaves = expr.union.map(leafOf);
    if (leaves.every((l): l is TypeLeaf => l !== null)) return leaves;
  }
  return null;
}

/** Read a config's `sources` back as the legacy membership subset. `entryTypes`
 * lists EVERY scoped fqn of a kind (exact + family) — so the many read-only "is
 * this fqn in scope" consumers need no change — and `families` is the parallel
 * set of fqns whose leaf is `descendants_of` (self + subtypes). View-refs and
 * non-degenerate exprs contribute their kind (when known) with no entry_type
 * constraint. */
export function pickerMembership(config: NodePickerConfig | null | undefined): {
  kinds: string[];
  entryTypes: Record<string, string[]>;
  families: Record<string, string[]>;
} {
  const kinds: string[] = [];
  const entryTypes: Record<string, string[]> = {};
  const families: Record<string, string[]> = {};
  for (const source of config?.sources ?? []) {
    if (!("kind" in source) || !source.kind) continue; // view-ref: unresolved here
    if (!kinds.includes(source.kind)) kinds.push(source.kind);
    const leaves = exprEntryTypeLeaves(source.expr);
    if (leaves && leaves.length > 0) {
      const bucket = (entryTypes[source.kind] ??= []);
      for (const leaf of leaves) {
        if (!bucket.includes(leaf.fqn)) bucket.push(leaf.fqn);
        if (leaf.family) {
          const fam = (families[source.kind] ??= []);
          if (!fam.includes(leaf.fqn)) fam.push(leaf.fqn);
        }
      }
    }
  }
  return { kinds, entryTypes, families };
}

/** A source the checkbox tree can regenerate from `{kinds, entryTypes, families}`
 * alone: a ViewSpec that is kind-only, or a `type`/`descendants_of` leaf, or a
 * union of those. Everything else — view-refs and richer inline exprs
 * (`intersect`, `difference`, a `{var}` leaf, …) — the tree cannot re-author, so
 * it must be carried through a re-encode verbatim rather than clobbered by the
 * degenerate rebuild (#94). */
function treeCanRepresent(source: ViewSource): boolean {
  if (isViewRef(source)) return false;
  return !source.expr || exprEntryTypeLeaves(source.expr) !== null;
}

/** Inverse of {@link pickerMembership}: one degenerate ViewSpec source per kind,
 * each fqn emitted as `{type: fqn}` (exact) or `{descendants_of: fqn}` (family,
 * per `families`) — a single leaf when a kind has one fqn, a `union` (which may
 * MIX both leaf kinds) when several. Deterministic — fqns are sorted so equal
 * membership yields a byte-equal source list (tag-scope change-detection relies
 * on it; see the backend `_membership_to_sources` docstring).
 *
 * The checkbox-tree editor only authors these degenerate sources, so it
 * re-encodes them wholesale on every toggle. `existing` carries the config's
 * current `sources` so any source the tree can't represent — saved-view refs
 * (#82 / ADR-0023) AND non-degenerate inline exprs (#94) — is PRESERVED across
 * that re-encode instead of silently dropped. */
export function membershipToSources(
  kinds: string[],
  entryTypes: Record<string, string[]>,
  families: Record<string, string[]>,
  existing?: ViewSource[] | null,
): ViewSource[] {
  const orderedKinds = Array.from(new Set([...kinds, ...Object.keys(entryTypes)]));
  const degenerate = orderedKinds.map((kind): ViewSpec => {
    const fqns = [...(entryTypes[kind] ?? [])].sort();
    const fam = new Set(families[kind] ?? []);
    const leaf = (fqn: string): ViewExpr => (fam.has(fqn) ? { descendants_of: fqn } : { type: fqn });
    if (fqns.length === 0) return { kind };
    if (fqns.length === 1) return { kind, expr: leaf(fqns[0]) };
    return { kind, expr: { union: fqns.map(leaf) } };
  });
  const preserved = (existing ?? []).filter((s) => !treeCanRepresent(s));
  return [...degenerate, ...preserved];
}
