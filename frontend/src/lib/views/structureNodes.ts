// Adapt a manuscript/research `StructureDocument` into the flat `EvalNode`
// roster the view evaluator consumes (0.5.0 step 4, #81). A structure node's
// `type` is its entry_type FQN; its evaluator `metadata` is the scene's full
// front-matter metadata + computed counters + `status` merged into one dict
// (#184 Phase 3), so the roster is filterable by any scene field. Containers
// *and* leaves are included: a view can match a chapter as readily as a scene
// (the Draft pane only tints, never re-shapes — ADR-0022 — so including
// containers costs nothing).
//
// Each node carries a `parent` metadata ref = its immediate container's node id
// (unset for roots). This is the materialized backing of the containment
// relation (ADR-0037 §4): the Draft/Research default view is a recursive Nest on
// `parent` (`defaultView("scene")`), so the tree is rebuilt by the ordinary Nest
// evaluator — not a `presentation: "tree"` special case (eradicated by §3). When
// containment later moves to real stored references (#217), only this backing
// swaps; the view spec is unchanged.

import type { EvalNode } from "@/lib/views/evaluateView";
import type { MetadataValue, StructureDocument, StructureNode } from "@/lib/types";

export function structureToEvalNodes(structure: StructureDocument | null): EvalNode[] {
  if (!structure) return [];
  const out: EvalNode[] = [];
  const walk = (node: StructureNode, parentId: string | null): void => {
    // The evaluator reads a scene field via `metadata[key]` (status/pov/… are
    // not intrinsic), so flatten the full scene metadata + computed counters +
    // the top-level `status` projection into one dict — this is what makes the
    // Draft roster filterable by scene field in one pass (#184 Phase 3).
    const metadata: Record<string, MetadataValue> = {
      ...(node.metadata ?? {}),
      ...(node.computed_metadata ?? {}),
    };
    if (node.status) metadata.status = node.status;
    // The containment ref the Draft/Research Nest joins on (ADR-0037 §4). Roots
    // leave it unset ⇒ `field: parent unset` seeds them as nest roots.
    if (parentId) metadata.parent = parentId;
    out.push({
      id: node.id,
      entry_type: node.type,
      title: node.title,
      metadata,
      // #201: a scene's canonical identity is its front-matter `scene_id`, which
      // is what the reverse reference index keys on — while its roster `id` is
      // the structure `node.id`. Carry it so `field_of(…, references)` bridges
      // the two id spaces. `||`: a container (no scene_id) or a blank id ⇒ omitted
      // so `id` is treated as canonical, never a lookup on the empty string.
      ref_id: node.scene_id || undefined,
    });
    for (const child of node.children ?? []) walk(child, node.id);
  };
  for (const child of structure.root.children ?? []) walk(child, null);
  return out;
}
