// Pure, side-effect-free helpers for the manuscript/research structure trees.
// These operate purely on StructureDocument/StructureNode data plus a passed-in
// MetadataSchema — no reactive state, no API calls — so they live outside the
// App/Tree components and can be shared (and unit-tested) freely. Anything that
// mutates app state, touches the DOM, or calls the backend stays in the
// component that owns that state.

import type { MetadataSchema, StructureDocument, StructureNode } from "./types";

// Direct children of a node, normalising the optional `children` field to [].
export function nodeChildren(node: StructureNode): StructureNode[] {
  return node.children ?? [];
}

// Leaf nodes are the ones that own an underlying scene file. (Research notes
// are not reorderable, so this manuscript-flavoured check is only ever reached
// for the scene tree.)
export function isLeafNode(node: StructureNode): boolean {
  return node.type === "scene";
}

// Depth-first lookup of a node by id, starting from any subtree root.
export function findStructureNodeById(
  node: StructureNode | null | undefined,
  id: string,
): StructureNode | null {
  if (!node) return null;
  if (node.id === id) return node;
  for (const child of node.children ?? []) {
    const found = findStructureNodeById(child, id);
    if (found) return found;
  }
  return null;
}

// Find the tree node that owns a given scene/note id. Both manuscript scenes
// and research notes live in tree nodes whose `scene_id` carries the
// underlying-document id.
export function findNodeBySceneId(node: StructureNode, sceneId: string): StructureNode | null {
  if (node.scene_id === sceneId) return node;
  for (const child of node.children ?? []) {
    const found = findNodeBySceneId(child, sceneId);
    if (found) return found;
  }
  return null;
}

// Diff a parent's children before/after a create call to recover the new
// child's id (the create APIs return the whole document, not the new id).
export function findNewlyAddedChildId(
  before: StructureDocument | null,
  after: StructureDocument | null,
  parentId: string | null,
): string | null {
  if (!after) return null;
  const beforeParent = before ? findStructureNodeById(before.root, parentId ?? before.root.id) : null;
  const afterParent = findStructureNodeById(after.root, parentId ?? after.root.id);
  if (!afterParent) return null;
  const beforeIds = new Set(beforeParent?.children?.map((child) => child.id) ?? []);
  return afterParent.children.find((child) => !beforeIds.has(child.id))?.id ?? null;
}

// Locate a node's parent and its index within that parent's children.
export function findParentAndIndex(
  parent: StructureNode,
  nodeId: string,
): { parent: StructureNode; index: number } | null {
  for (let i = 0; i < (parent.children?.length ?? 0); i++) {
    if (parent.children[i].id === nodeId) return { parent, index: i };
    const found = findParentAndIndex(parent.children[i], nodeId);
    if (found) return found;
  }
  return null;
}

// All node ids in a subtree (the node itself plus every descendant).
export function collectNodeIdSet(root: StructureNode): Set<string> {
  const ids = new Set<string>();
  const walk = (current: StructureNode) => {
    ids.add(current.id);
    for (const child of current.children ?? []) walk(child);
  };
  walk(root);
  return ids;
}

// All scene/note ids carried by a subtree's leaf nodes.
export function collectSceneIdSet(node: StructureNode | null): Set<string> {
  const ids = new Set<string>();
  if (!node) return ids;
  const walk = (current: StructureNode) => {
    if (current.scene_id) ids.add(current.scene_id);
    for (const child of current.children ?? []) walk(child);
  };
  walk(node);
  return ids;
}

// Immutably rewrite a single node's title within a tree.
export function updateNodeTitleInTree(node: StructureNode, nodeId: string, title: string): StructureNode {
  if (node.id === nodeId) {
    return { ...node, title };
  }
  return {
    ...node,
    children: (node.children ?? []).map((child) => updateNodeTitleInTree(child, nodeId, title)),
  };
}

// Display name for an entry type id, falling back to the raw id.
export function entryTypeName(typeId: string, schema: MetadataSchema | null): string {
  return schema?.entry_types[typeId]?.name ?? typeId;
}

// Entry-type choices for a kind's "+ Add child" menu. Drops abstract parents
// (they can't be instantiated) and sorts by name.
export function entryTypeChoicesByKind(
  schema: MetadataSchema | null,
  kind: string,
): Array<{ id: string; name: string }> {
  return Object.entries(schema?.entry_types ?? {})
    .filter(([, definition]) => definition.kind === kind && !definition.abstract)
    .map(([id, definition]) => ({ id, name: definition.name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}
