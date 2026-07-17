// The Nest registry pre-walk (ADR-0028 Amendment 1, #260). Before evaluating a
// ViewSpec, the evaluator scans the whole expr tree so an `{orphans_of: id}`
// reference can resolve to (and evaluate, memoized) the Nest carrying that `id` —
// wherever the Nest lives, in the same group's expr or another's. Kept separate
// from `evaluateView` so that (large) file stays under the size cap; pure and
// framework-free.

import type { ViewExpr, ViewNestOp } from "@/lib/types";
import { walkViewExpr } from "@/lib/views/walkViewExpr";

// Register every id'd Nest (`nests`) and every `{orphans_of}` reference (`refs`)
// reachable in an expr tree. A Nest's `id` is registered from EITHER a `{nest}`
// slot (its results branch) OR an `{orphans_of, orphans_nest}` reference carrying
// the definition inline (the orphans-only case, #275) — both populate the same
// registry so `{orphans_of: id}` resolves regardless of which output was wired.
// Traversal (incl. the Filter value-operand's `{field_of}` projection) is the
// shared `walkViewExpr` — this pass only collects.
export function collectNests(
  expr: ViewExpr | null | undefined,
  nests: Map<string, ViewNestOp>,
  refs: Set<string>,
): void {
  walkViewExpr(expr, (e) => {
    if (e.orphans_of != null) refs.add(e.orphans_of);
    if (e.nest?.id != null) nests.set(e.nest.id, e.nest);
    if (e.orphans_nest?.id != null) nests.set(e.orphans_nest.id, e.orphans_nest);
  });
}
