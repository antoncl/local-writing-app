// The single ViewExpr tree-walker (#275 Part 4b; #277 Phase 3). Every place that
// needs to visit every sub-expression of a view routes through ONE traversal.
// Since #277 / ADR-0041 the child-edge list is machine-generated from the grammar
// IDL: `walkViewExpr` delegates to the generated `children(expr)`, so adding a
// grammar slot updates every walker automatically — there is no hand-copied slot
// list left to drift (the #260/#276 failure class, structurally eliminated).
//
// `visit` is called on `expr` and, pre-order, on every descendant ViewExpr. It
// receives the live object, so a visitor may read OR mutate it in place. Callers
// with per-branch logic that returns values (the evaluator's `evalExpr`, the
// spec→graph builder) keep their own bodies — this serves pure collection/mutation
// passes, not value-returning dispatch.
//
// Terminates only on an acyclic expr. `{orphans_of}` references are acyclic by
// invariant (isValidConnection at authoring + the load-time repair, #275), and the
// tree slots can't form a cycle, so no visited-guard is needed.

import type { ViewExpr } from "@/lib/types";
import { children } from "@/lib/viewGrammar.generated";

export function walkViewExpr(
  expr: ViewExpr | null | undefined,
  visit: (e: ViewExpr) => void,
): void {
  if (!expr) return;
  visit(expr);
  for (const child of children(expr)) walkViewExpr(child, visit);
}
