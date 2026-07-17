// The Nest registry pre-walk (ADR-0028 Amendment 1, #260). Before evaluating a
// ViewSpec, the evaluator scans the whole expr tree so an `{orphans_of: id}`
// reference can resolve to (and evaluate, memoized) the Nest carrying that `id` —
// wherever the Nest lives, in the same group's expr or another's. Kept separate
// from `evaluateView` so that (large) file stays under the size cap; pure and
// framework-free.

import type { ViewExpr, ViewFieldOf, ViewNestOp } from "@/lib/types";

// Register every id'd `nest` (`nests`) and every `{orphans_of}` reference (`refs`)
// reachable in an expr tree. Recurses through every ViewExpr slot that can hold a
// sub-expr — including a Filter value operand's `{field_of}` projection, which the
// evaluator (`resolveOperand`) also traverses, so a nest / reference buried there
// must not drop out of the pre-walk.
export function collectNests(
  expr: ViewExpr | null | undefined,
  nests: Map<string, ViewNestOp>,
  refs: Set<string>,
): void {
  if (!expr) return;
  if (expr.orphans_of != null) refs.add(expr.orphans_of);
  if (expr.nest) {
    if (expr.nest.id != null) nests.set(expr.nest.id, expr.nest);
    collectNests(expr.nest.parents, nests, refs);
    collectNests(expr.nest.children, nests, refs);
  }
  for (const sub of expr.union ?? []) collectNests(sub, nests, refs);
  for (const sub of expr.intersect ?? []) collectNests(sub, nests, refs);
  if (expr.difference) {
    collectNests(expr.difference.keep, nests, refs);
    collectNests(expr.difference.remove, nests, refs);
  }
  collectNests(expr.complement, nests, refs);
  collectNests(expr.of, nests, refs);
  if (expr.field_of) collectNests(expr.field_of.of, nests, refs);
  const val = expr.field?.value;
  if (val && typeof val === "object" && "field_of" in val) {
    collectNests((val as { field_of: ViewFieldOf }).field_of.of, nests, refs);
  }
}
