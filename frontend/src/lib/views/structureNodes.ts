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
    //
    // Spread precedence is SAFE, not a shadowing hazard (#204 verified): a schema
    // key is stored XOR computed (the backend rejects a stored value on a computed
    // field and a `computed` block on a non-computed one), so `node.metadata`
    // (stored front-matter) and `node.computed_metadata` carry DISJOINT keys — the
    // second spread can never clobber a real stored value.
    const metadata: Record<string, MetadataValue> = {
      ...(node.metadata ?? {}),
      ...(node.computed_metadata ?? {}),
    };
    // `status` is a built-in stored field whose runtime home is the top-level scene
    // property, not the metadata dict — so this projects it in (same value, no
    // divergent stored `metadata.status` to overwrite).
    if (node.status) metadata.status = node.status;
    // The containment ref the Draft/Research Nest joins on (ADR-0037 §4). Roots
    // leave it unset ⇒ `field: parent unset` seeds them as nest roots. `parent` is
    // a SYNTHETIC structural key and intentionally wins here; it is not (yet) a
    // reserved schema key, so a user metadata field literally named `parent` would
    // be shadowed — a known narrow limitation that dissolves when containment
    // becomes a real stored reference (#217), when this backing simply swaps.
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
