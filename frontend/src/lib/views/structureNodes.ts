// Adapt a manuscript/research `StructureDocument` into the flat `EvalNode`
// roster the view evaluator consumes (0.5.0 step 4, #81). A structure node's
// `type` is its entry_type FQN and `computed_metadata` is its effective
// metadata, so the mapping is mechanical. Containers *and* leaves are included:
// a view can match a chapter as readily as a scene (the Draft pane only tints,
// never re-shapes — ADR-0022 — so including containers costs nothing).
//
// Each node also carries its `ancestry` — the chain of container nodes above it,
// outer→inner — so a `presentation: "tree"` view (#101) can rebuild the nesting
// from the flat roster. `nodeId` on each segment marks it as a real node, so the
// renderer draws an ancestor as a collapsible NodeRow, not a synthetic header.

import type { EvalNode, PathSegment } from "@/lib/views/evaluateView";
import type { StructureDocument, StructureNode } from "@/lib/types";

export function structureToEvalNodes(structure: StructureDocument | null): EvalNode[] {
  if (!structure) return [];
  const out: EvalNode[] = [];
  const walk = (node: StructureNode, ancestry: PathSegment[]): void => {
    out.push({
      id: node.id,
      entry_type: node.type,
      title: node.title,
      metadata: node.computed_metadata ?? null,
      ancestry,
    });
    const childAncestry = [...ancestry, { key: node.id, label: node.title, nodeId: node.id }];
    for (const child of node.children ?? []) walk(child, childAncestry);
  };
  for (const child of structure.root.children ?? []) walk(child, []);
  return out;
}
