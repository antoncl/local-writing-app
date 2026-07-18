// The three-valued lowering algebra for graph → spec serialization (extracted
// from viewGraph.ts as a pure, self-contained unit; a down-payment on the #278
// split). A `Built` is a lowered branch; the *Built combinators fold the
// universe/empty identities so the emitted ViewExpr stays minimal. Pure — depends
// only on the ViewExpr grammar type; the graph-aware lowering (buildNode, nestBuilt,
// filterBuilt, …) lives in viewGraph.ts and calls these.

import type { ViewExpr } from "@/lib/types";

// A lowered branch: a concrete membership `expr`, the whole `universe` (an
// `All` injector or a bare handle), or `empty` (nothing / unconfigured).
export type Built = { tag: "expr"; expr: ViewExpr } | { tag: "universe" } | { tag: "empty" };
export const UNIVERSE: Built = { tag: "universe" };
export const EMPTY: Built = { tag: "empty" };
export const built = (expr: ViewExpr): Built => ({ tag: "expr", expr });

// Inner lowering: a concrete expr → itself; universe/empty → null. Used for
// positions the grammar can't hand a universal-set operand (a `nest` seed, a
// `field_of` input) — there an unwired/`All` branch still degrades to null (→
// dropped/empty), exactly as before ADR-0036. The OUTER serialization points
// (`materializeOuter`, called from graphToSpec/graphToExpr) instead render a
// top-level/group `universe` as the explicit `descendants_of:<kind-root>` — post
// ADR-0036 null means the empty set, so "everything" can no longer ride on null.
export function materialize(b: Built): ViewExpr | null {
  return b.tag === "expr" ? b.expr : null;
}

// Outer lowering (ADR-0036 §3): a top-level or group `universe` becomes the
// explicit whole-roster expr for the anchor kind; `empty` → null (= empty set);
// a concrete expr → itself. `universeExpr` is resolved once per lowering from the
// graph's kind + schema (null in the kind-less `graphToExpr` test helper, where a
// bare universe stays null).
export function materializeOuter(b: Built, universeExpr: ViewExpr | null): ViewExpr | null {
  if (b.tag === "universe") return universeExpr;
  return materialize(b);
}

export function unionBuilt(parts: Built[]): Built {
  const exprs: ViewExpr[] = [];
  for (const p of parts) {
    if (p.tag === "universe") return UNIVERSE; // universe absorbs a union
    if (p.tag === "empty") continue;
    exprs.push(p.expr);
  }
  if (exprs.length === 0) return EMPTY;
  if (exprs.length === 1) return built(exprs[0]);
  return built({ union: exprs });
}

export function intersectBuilt(parts: Built[]): Built {
  const exprs: ViewExpr[] = [];
  for (const p of parts) {
    if (p.tag === "empty") return EMPTY; // empty absorbs an intersect
    if (p.tag === "universe") continue; // universe is the identity
    exprs.push(p.expr);
  }
  if (exprs.length === 0) return UNIVERSE; // every operand was universe
  if (exprs.length === 1) return built(exprs[0]);
  return built({ intersect: exprs });
}

export function complementBuilt(inner: Built): Built {
  if (inner.tag === "universe") return EMPTY;
  if (inner.tag === "empty") return UNIVERSE;
  return built({ complement: inner.expr });
}

export function differenceBuilt(keep: Built, remove: Built): Built {
  if (keep.tag === "empty") return EMPTY;
  if (remove.tag === "empty") return keep; // nothing removed
  if (remove.tag === "universe") return EMPTY; // removes everything
  // remove is a concrete expr
  if (keep.tag === "universe") return built({ complement: remove.expr });
  return built({ difference: { keep: keep.expr, remove: remove.expr } });
}
