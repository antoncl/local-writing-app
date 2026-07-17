// The single ViewExpr tree-walker (#275, Part 4b). Every place that needs to
// visit every sub-expression of a view — the Nest registry pre-walk, the param
// referencing-field scan — used to hand-roll its own recursion with its own copy
// of the slot list, and they drifted (a missed slot was the #260 review's
// `collectNests` value-operand gap). This is that slot list, ONCE: change a
// grammar slot here and every collector follows.
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

import type { ViewExpr, ViewFieldOf } from "@/lib/types";

export function walkViewExpr(
  expr: ViewExpr | null | undefined,
  visit: (e: ViewExpr) => void,
): void {
  if (!expr) return;
  visit(expr);
  for (const sub of expr.union ?? []) walkViewExpr(sub, visit);
  for (const sub of expr.intersect ?? []) walkViewExpr(sub, visit);
  if (expr.difference) {
    walkViewExpr(expr.difference.keep, visit);
    walkViewExpr(expr.difference.remove, visit);
  }
  walkViewExpr(expr.complement, visit);
  if (expr.nest) {
    walkViewExpr(expr.nest.parents, visit);
    walkViewExpr(expr.nest.children, visit);
  }
  if (expr.orphans_nest) {
    walkViewExpr(expr.orphans_nest.parents, visit);
    walkViewExpr(expr.orphans_nest.children, visit);
  }
  walkViewExpr(expr.of, visit);
  if (expr.field_of) walkViewExpr(expr.field_of.of, visit);
  // A Filter's value operand may itself project a node-set via `{field_of}` (#196).
  const val = expr.field?.value;
  if (val && typeof val === "object" && "field_of" in val) {
    walkViewExpr((val as { field_of: ViewFieldOf }).field_of.of, visit);
  }
}
