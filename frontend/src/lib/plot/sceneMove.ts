// Moving a written card's scene by dragging the card onto a chapter (ADR-0097 §8) — pure.
// The board knows the scene it wants next to; the manuscript's move API wants a parent and a
// position, so this reads the tree and works the position out — and where the scene sat, so
// undo can put it back.

import type { StructureDocument, StructureNode } from "@/lib/types";
import { findNodeBySceneId, findParentAndIndex, findStructureNodeById } from "@/lib/utils/treeHelpers";

/** The scene a moved scene lands beside: right after, or right before, it. Null = the end. */
export type SceneNear = { after: string } | { before: string } | null;

/** One end of a scene move: the parent node and the slot among its children, counted with
 *  the moved node removed from its old place (what `move_structure_node` takes). */
export type SceneSpot = { parentId: string; position: number };

export type SceneMovePlan = { nodeId: string; from: SceneSpot; to: SceneSpot };

const sceneIdOf = (node: StructureNode): string => node.scene_id ?? node.id;

/** The move that puts `sceneId` under `parentId` beside `near`, or null when the scene or
 *  the parent is not in the tree, or the scene already sits there. A `near` that is not a
 *  child of the parent (or null) appends. */
export function planSceneMove(
  structure: StructureDocument | null,
  sceneId: string,
  parentId: string,
  near: SceneNear,
): SceneMovePlan | null {
  const root = structure?.root;
  const node = root && findNodeBySceneId(root, sceneId);
  const parent = root && findStructureNodeById(root, parentId);
  const old = root && node && findParentAndIndex(root, node.id);
  if (!node || !parent || !old) return null;
  const siblings = (parent.children ?? []).filter((child) => child.id !== node.id).map(sceneIdOf);
  let position = siblings.length;
  if (near) {
    const at = siblings.indexOf("after" in near ? near.after : near.before);
    if (at >= 0) position = "after" in near ? at + 1 : at;
  }
  if (old.parent.id === parentId && old.index === position) return null;
  return { nodeId: node.id, from: { parentId: old.parent.id, position: old.index }, to: { parentId, position } };
}
