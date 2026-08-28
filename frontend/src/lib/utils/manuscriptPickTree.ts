// The invocation picker's manuscript tree — ADR-0074 slice 4b (#1476).
//
// The author-time `pickerTree.ts` cannot be reused: it walks the metadata TYPE
// hierarchy and stores concrete leaves ("checked container = every leaf in the
// set"). This walks the manuscript INSTANCE tree (acts/chapters/scenes) and its
// selection model is the inverse — checking a container stores ONE live ref
// that the backend expands at render time (slice 4a), and unchecking an implied
// child SPLITS that ref into explicit siblings.
//
// Two id spaces meet here and never collide: a scene ref carries the scene's
// `scene_id`; a container ref carries the structure-node `id` (containers have
// no scene_id). Refs are classified against the live structure, not by trusting
// `entry_type`, so a scene sub-type can't be mistaken for a container.

import type { NodePickerRef, StructureDocument, StructureNode } from "@/lib/types";

export type PickState = "on" | "implied" | "indeterminate" | "off";

/** A manuscript node flattened for rendering (depth-indented rows). */
export interface ManuscriptRow {
  id: string;
  title: string;
  type: string;
  depth: number;
  isScene: boolean;
  hasChildren: boolean;
  state: PickState;
  collapsed: boolean;
  /** Descendant scene count — 1 for a scene, N for a container. */
  sceneCount: number;
}

const MANUSCRIPT = "manuscript";

// Manuscript container node types (vs leaf scenes). Acts and chapters carry
// their own `scene_id` (a backing file), so container-vs-scene is NOT
// `scene_id is None` — it is the node type, or having children (covering any
// user-defined container level). Mirrors TreeStructureService.is_container.
const CONTAINER_TYPES = new Set(["root", "manuscript:act", "manuscript:chapter"]);

function isContainer(node: StructureNode): boolean {
  return CONTAINER_TYPES.has(node.type) || (node.children?.length ?? 0) > 0;
}
function isScene(node: StructureNode): boolean {
  return !isContainer(node);
}

/** The id a ref uses for this node: the scene_id for a leaf scene, the node id
 * for a container. */
function refIdFor(node: StructureNode): string {
  return isScene(node) ? (node.scene_id ?? node.id) : node.id;
}

/** The scene node's instance entry_type (a sub-type like `manuscript:battle`)
 * when present, else its structure `type`. Mirrors the flattenScenes read. */
function sceneEntryType(node: StructureNode): string {
  const instance = (node as unknown as { entry_type?: string }).entry_type;
  return instance ?? node.type ?? "manuscript:scene";
}

/** The picker ref for a node — a scene ref or a container ref. */
export function refForNode(node: StructureNode): NodePickerRef {
  if (isScene(node)) {
    return {
      id: node.scene_id as string,
      kind: MANUSCRIPT,
      entry_type: sceneEntryType(node),
      title: node.title,
    };
  }
  return { id: node.id, kind: MANUSCRIPT, entry_type: node.type, title: node.title };
}

interface PickSets {
  scenes: Set<string>; // picked scene_ids
  containers: Set<string>; // picked container node-ids
}

/** Classify the manuscript refs in `value` against the structure. A ref whose
 * id matches no node is stale and contributes to neither set. */
function pickSets(document: StructureDocument, value: NodePickerRef[]): PickSets {
  const sceneIds = new Set<string>();
  const containerIds = new Set<string>();
  const walk = (n: StructureNode) => {
    if (isContainer(n)) containerIds.add(n.id);
    else if (n.scene_id) sceneIds.add(n.scene_id);
    n.children?.forEach(walk);
  };
  walk(document.root);
  const scenes = new Set<string>();
  const containers = new Set<string>();
  for (const ref of value) {
    if (ref.kind !== MANUSCRIPT) continue;
    if (sceneIds.has(ref.id)) scenes.add(ref.id);
    else if (containerIds.has(ref.id)) containers.add(ref.id);
  }
  return { scenes, containers };
}

function hasAnyScene(node: StructureNode): boolean {
  if (isScene(node)) return !!node.scene_id;
  return (node.children ?? []).some(hasAnyScene);
}

/** Whether any scene under `node` is covered — its scene_id picked, or a
 * container at or below `node` picked. Assumes `node` itself is not covered by
 * an ancestor (the caller handles "implied"). */
function subtreeHasCoveredScene(node: StructureNode, sets: PickSets): boolean {
  if (isContainer(node)) {
    if (sets.containers.has(node.id)) return hasAnyScene(node);
    return (node.children ?? []).some((c) => subtreeHasCoveredScene(c, sets));
  }
  return !!node.scene_id && sets.scenes.has(node.scene_id);
}

function stateFor(node: StructureNode, sets: PickSets, coveredByAncestor: boolean): PickState {
  const selfPicked = isContainer(node)
    ? sets.containers.has(node.id)
    : !!node.scene_id && sets.scenes.has(node.scene_id);
  if (selfPicked) return "on";
  if (coveredByAncestor) return "implied";
  if (isScene(node)) return "off";
  return subtreeHasCoveredScene(node, sets) ? "indeterminate" : "off";
}

export interface FlattenOptions {
  /** A scene is emitted only if this returns true; a container only if it has
   * an emitted descendant scene. Applied whether or not a search is active — it
   * is the home for the config's scene-subtype allowlist, combined with the
   * search match by the caller. Omit to show every scene. */
  sceneVisible?: (node: StructureNode) => boolean;
  /** Ignore `collapsedIds` — every surviving row expanded (a search is active,
   * per the ADR's "search expands every surviving row"). */
  expandAll?: boolean;
}

/** Flatten the manuscript tree into depth-indented rows with tri-state. The root
 * is included as the "The Manuscript" whole-novel row. Collapsed containers hide
 * their subtree unless `expandAll`; a `sceneVisible` predicate gates which scenes
 * (and thus which containers) appear at all. */
export function flattenManuscript(
  document: StructureDocument,
  value: NodePickerRef[],
  collapsedIds: Set<string>,
  options: FlattenOptions = {},
): ManuscriptRow[] {
  const { sceneVisible, expandAll = false } = options;
  const sets = pickSets(document, value);
  const visible = (node: StructureNode): boolean => {
    if (node.scene_id) return sceneVisible ? sceneVisible(node) : true;
    return (node.children ?? []).some(visible);
  };
  const rows: ManuscriptRow[] = [];
  const walk = (node: StructureNode, depth: number, coveredByAncestor: boolean) => {
    if (sceneVisible && !visible(node)) return;
    const state = stateFor(node, sets, coveredByAncestor);
    const scene = isScene(node);
    const children = node.children ?? [];
    const collapsed = !expandAll && collapsedIds.has(node.id);
    rows.push({
      id: node.id,
      title: node.title,
      type: node.type,
      depth,
      isScene: scene,
      hasChildren: children.length > 0,
      state,
      collapsed,
      sceneCount: countScenes(node),
    });
    if (collapsed) return;
    const childCovered = coveredByAncestor || (!scene && sets.containers.has(node.id));
    for (const child of children) walk(child, depth + 1, childCovered);
  };
  walk(document.root, 0, false);
  return rows;
}

function countScenes(node: StructureNode): number {
  if (isScene(node)) return node.scene_id ? 1 : 0;
  return (node.children ?? []).reduce((n, c) => n + countScenes(c), 0);
}

/** The ids of every COLLAPSIBLE manuscript container — acts, chapters, and any
 * user-defined container level — but NOT the root, which stays open so its acts
 * always show (the mockup gives the root no caret). Feeds the picker's
 * collapse-by-default model: a container is collapsed unless the user has
 * expanded it, so `containers \ expanded` is the collapsed set. */
export function collapsibleContainerIds(document: StructureDocument): Set<string> {
  const ids = new Set<string>();
  const walk = (node: StructureNode, depth: number) => {
    if (depth > 0 && isContainer(node)) ids.add(node.id);
    node.children?.forEach((c) => walk(c, depth + 1));
  };
  walk(document.root, 0);
  return ids;
}

/** The descendant scene count for a picked ref, or null when the ref is not a
 * container (a scene ref shows no count). Used by the picked-list chips. */
export function sceneCountForRef(document: StructureDocument, ref: NodePickerRef): number | null {
  if (ref.kind !== MANUSCRIPT) return null;
  const node = findById(document.root, ref.id);
  if (node === null || isScene(node)) return null;
  return countScenes(node);
}

function findById(node: StructureNode, id: string): StructureNode | null {
  if (node.id === id) return node;
  for (const child of node.children ?? []) {
    const found = findById(child, id);
    if (found) return found;
  }
  return null;
}

function pathTo(root: StructureNode, id: string): StructureNode[] | null {
  if (root.id === id) return [root];
  for (const child of root.children ?? []) {
    const sub = pathTo(child, id);
    if (sub) return [root, ...sub];
  }
  return null;
}

/** The nearest ancestor container of `node` whose ref is picked, or null. */
function coveringAncestor(
  document: StructureDocument,
  node: StructureNode,
  sets: PickSets,
): StructureNode | null {
  const path = pathTo(document.root, node.id);
  if (path === null) return null;
  // Walk ancestors nearest-first (exclude node itself, the last element).
  for (let i = path.length - 2; i >= 0; i--) {
    if (sets.containers.has(path[i].id)) return path[i];
  }
  return null;
}

function withoutRef(value: NodePickerRef[], refId: string): NodePickerRef[] {
  return value.filter((r) => !(r.kind === MANUSCRIPT && r.id === refId));
}

/** Absorb: drop every manuscript ref under `container` (scenes and
 * sub-containers), then add the one container ref. */
function absorb(value: NodePickerRef[], container: StructureNode): NodePickerRef[] {
  const under = new Set<string>();
  const collect = (n: StructureNode) => {
    under.add(refIdFor(n));
    n.children?.forEach(collect);
  };
  collect(container);
  const kept = value.filter((r) => !(r.kind === MANUSCRIPT && under.has(r.id)));
  return [...kept, refForNode(container)];
}

/** Split: replace covering container `c`'s ref with explicit refs for its
 * subtree minus `x` — every sibling off the path from `c` down to `x`, at the
 * coarsest granularity (containers stay containers, scenes stay scenes). */
function split(
  document: StructureDocument,
  value: NodePickerRef[],
  c: StructureNode,
  x: StructureNode,
): NodePickerRef[] {
  const path = pathTo(c, x.id);
  if (path === null) return value; // shouldn't happen; x is under c
  let out = withoutRef(value, refIdFor(c));
  const adds: NodePickerRef[] = [];
  for (let i = 0; i < path.length - 1; i++) {
    const node = path[i];
    const next = path[i + 1];
    for (const sib of node.children ?? []) {
      if (sib.id !== next.id) adds.push(refForNode(sib));
    }
  }
  out = [...out, ...adds];
  return out;
}

/** Toggle the pick state of the manuscript node `nodeId`, returning the new
 * value array. The single entry point the picker calls; it dispatches on the
 * node's current tri-state:
 *  - on        → remove its own ref
 *  - implied   → split the covering ancestor (subtree minus this node)
 *  - scene off → add its scene ref
 *  - container off/indeterminate → absorb (one live container ref)
 */
export function togglePickAt(
  document: StructureDocument,
  value: NodePickerRef[],
  nodeId: string,
): NodePickerRef[] {
  const node = findById(document.root, nodeId);
  if (node === null) return value;
  const sets = pickSets(document, value);
  const ancestor = coveringAncestor(document, node, sets);
  const state = stateFor(node, sets, ancestor !== null);

  if (state === "on") return withoutRef(value, refIdFor(node));
  if (state === "implied" && ancestor !== null) return split(document, value, ancestor, node);
  if (isScene(node)) return [...value, refForNode(node)];
  return absorb(value, node);
}
