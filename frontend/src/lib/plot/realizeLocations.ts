// The manuscript locations a card can be REALIZED into (#879). Realizing an
// unattached card mints a scene; without a chosen target the backend drops it
// into the first container (Act 1 / Chapter 1), which is rarely where the writer
// wants it. This flattens the manuscript tree to the containers the realize
// picker offers; a chosen id becomes `create_scene`'s `parent_id` (the backend
// already honours it — see test_realize_places_the_scene_under_a_given_parent).
import type { StructureDocument, StructureNode } from "@/lib/types";

// A container the writer can realize into. `depth` drives the picker's indent
// (0 = a top-level act, 1 = a chapter within it, …), so the roster reads as the
// manuscript tree rather than a flat list.
export type PlotRealizeLocation = {
  id: string;
  title: string;
  depth: number;
};

// Every non-leaf node of the manuscript, in reading (pre-order) order. A leaf is
// a scene (`type === "scene:scene"`, mirroring the backend's `_is_leaf_node`), so
// only acts/chapters — whatever container types the project declares — are offered.
// The root is skipped: a scene directly under it is "homeless", not a real
// placement. A null structure (not yet loaded) yields an empty roster, and the
// realize action falls back to the backend default.
export function realizeLocations(structure: StructureDocument | null): PlotRealizeLocation[] {
  if (!structure) return [];
  const out: PlotRealizeLocation[] = [];
  const walk = (node: StructureNode, depth: number): void => {
    for (const child of node.children ?? []) {
      if (child.type === "scene:scene") continue; // a leaf scene — never a container
      out.push({ id: child.id, title: child.title, depth });
      walk(child, depth + 1);
    }
  };
  walk(structure.root, 0);
  return out;
}
