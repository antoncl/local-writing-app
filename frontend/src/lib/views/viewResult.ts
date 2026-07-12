// `ViewResult` constructors (ADR-0035 §2). A view's output is ALWAYS exactly one
// `ViewResult<T>`, and that is `ViewNodeList`'s sole input. These constructors
// lift a non-view node array (or a bare node) into that same shape, so every call
// site — the view-driven panes (Lore/Assistants/preview) and the hand-assembled
// ones (Chats/Backlinks/ReferencePicker) — hands the wrapper one input type, with
// no `ViewResult | T[]` union and no `Array.isArray` discriminant inside it.
//
// They live beside `evaluateView` as constructors — NOT view grammar (that stays
// ADR-0018/0027). Shared invariant (ADR-0035 §4 / ADR-0027 §E / ADR-0019 /
// ADR-0028): `nodes` = membership → deduped (a node is "in the view" once);
// `groups` = presentation → may repeat (the same node may appear under two
// segments/paths).
//
// `concat` (inter-result stacking, ADR-0035 §2) is deliberately NOT shipped here:
// the ADR gates it on "only if a hand-assembled site needs it", no phase-1 site
// does, and a correct implementation must union+dedupe same-key top-level groups
// (ADR-0027 §D) — logic best pinned down against its first real caller.

import type { EvalNode, ViewGroup, ViewResult } from "@/lib/views/evaluateView";

// A member node as a childless real-node (leaf) group — the tree-uniform form
// every real node takes (ADR-0035 §4). The single source for this shape: the
// flat lift in `ViewNodeList` builds its leaves through it, so the render
// contract lives in one place. `color` carries the node's annotation token when
// a caller has one (default none).
export function leafGroup<T extends EvalNode>(node: T, color: string | null = null): ViewGroup<T> {
  return { key: `node:${node.id}`, label: node.title, color, nodeId: node.id, node, children: [] };
}

// The degenerate, one-stream `ViewResult` (ADR-0035 §2): a bare node array with
// no annotations and no grouping — the least-expressive result, and the base case
// every non-view site lifts through. `<ViewNodeList result={nodeSet(chats)} />`.
export function nodeSet<T extends EvalNode>(nodes: T[]): ViewResult<T> {
  return { nodes, annotations: new Map(), groups: null };
}
