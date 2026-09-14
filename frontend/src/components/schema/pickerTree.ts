// Pure schema-tree helpers for NodePickerConfigEditor. Extracted to keep the
// component under the file-size cap: these functions have no reactive/component
// state — they turn the project's metadata schema into a per-type scope tree and
// derive each node's tri-state. The component owns selection/collapse state and
// calls into these.
//
// Per-type scope is TRI-STATE (#1947, ADR-0074 Amendment 5): each type is
//   off      — not a source (no leaf)
//   exact    — this type only        → `{type: fqn}`
//   family   — this type + subtypes  → `{descendants_of: fqn}`
// A `family` type covers its whole subtree, so its descendants render as
// `implied` (locked) — the same idiom the runtime picker uses for a node under a
// checked container. The scope is carried as a per-fqn map (mirroring the config's
// `entryTypes`/`families` membership); a FAMILY on a parent is one fact, not the
// parent's leaves enumerated, so a non-leaf concrete type can finally carry its
// own scope (the leaf-only model could not — the misrepresentation Amendment 5
// fixes).

import type { MetadataSchema } from "@/lib/types";

export type SchemaNode = {
  id: string;
  name: string;
  abstract: boolean;
  children: SchemaNode[];
};

// A type's own scope: absent from the map = off.
export type TypeScope = "exact" | "family";
export type ScopeMap = Map<string, TypeScope>;

// What the row's checkbox shows. `exact`/`family` are the node's own scope;
// `implied` = covered by an ancestor's family; `indeterminate` = the node itself
// is off but something in its subtree is scoped; `off` = nothing.
export type PickState = "off" | "exact" | "family" | "implied" | "indeterminate";

// Which cycle a click walks, derived from the node's shape:
//   concrete-branch  off → exact → family → off   (a concrete type WITH subtypes)
//   concrete-leaf    off → exact → off            (no subtypes to fold in)
//   abstract-branch  off → family → off           (no instances, so no `exact`)
//   none             — nothing offerable (an abstract type with no concrete kids)
export type NodeCapability = "concrete-branch" | "concrete-leaf" | "abstract-branch" | "none";

export type RenderedNode = {
  id: string;
  name: string;
  abstract: boolean;
  depth: number;
  state: PickState;
  capability: NodeCapability;
  // Whether a click cycles this node. False when an ancestor family already
  // covers it (implied/locked) or it offers nothing (`none`). Readonly mode is
  // layered on top by the component.
  interactive: boolean;
  hasChildren: boolean;
  collapsed: boolean;
  // Roll-up for the `indeterminate` "N of M" hint: concrete leaves under this
  // node that a scope (here or below) covers, out of the node's concrete leaves.
  pickedCount: number;
  totalLeaves: number;
};

// Build the per-kind tree from the project schema. Roots are entry types whose
// `parent` is null; descendants attach via the parent chain. Abstract types act
// as containers — they're rendered as checkboxes too, but they have no instances
// so they carry only a `family` scope (all subtypes), never `exact`.
// `exclude` drops entry types that aren't offerable content sources — the plot
// kind uses it to hide `plot:board` (a presentation singleton) and `plot:template`
// (a Library lens), leaving plotline + card (ADR-0074 slice 6).
export function buildTree(schema: MetadataSchema | null, kind: string, exclude?: Iterable<string>): SchemaNode[] {
  if (!schema) return [];
  const excludeSet = exclude ? new Set(exclude) : null;
  type Raw = { id: string; name: string; abstract: boolean; parent: string | null };
  const raw: Raw[] = Object.entries(schema.entry_types ?? {})
    .filter(([id, def]) => def.kind === kind && !excludeSet?.has(id))
    .map(([id, def]) => ({
      id,
      name: def.name || id,
      abstract: !!def.abstract,
      parent: def.parent || null,
    }));
  const nodeById = new Map<string, SchemaNode>(
    raw.map((r) => [r.id, { id: r.id, name: r.name, abstract: r.abstract, children: [] }]),
  );
  const roots: SchemaNode[] = [];
  for (const r of raw) {
    const node = nodeById.get(r.id)!;
    if (r.parent && nodeById.has(r.parent)) {
      nodeById.get(r.parent)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sort = (nodes: SchemaNode[]) => {
    nodes.sort((a, b) => {
      if (a.abstract !== b.abstract) return a.abstract ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) sort(n.children);
  };
  sort(roots);
  return roots;
}

// Concrete (instantiable) leaves under a node — abstract types contribute none.
// A concrete node WITH children is a branch, not a leaf (its own id is not a
// concrete leaf here); its instances are covered by an `exact`/`family` scope on
// the node itself, which the scope map records directly.
export function concreteLeaves(node: SchemaNode): string[] {
  if (node.children.length === 0) return node.abstract ? [] : [node.id];
  const out: string[] = [];
  for (const child of node.children) out.push(...concreteLeaves(child));
  return out;
}

// The cycle a click on this node walks — see NodeCapability.
export function nodeCapability(node: SchemaNode): NodeCapability {
  const hasChildren = node.children.length > 0;
  if (node.abstract) return hasChildren ? "abstract-branch" : "none";
  return hasChildren ? "concrete-branch" : "concrete-leaf";
}

// Every descendant id (excluding the node itself).
function descendantIds(node: SchemaNode): string[] {
  const out: string[] = [];
  for (const child of node.children) {
    out.push(child.id);
    out.push(...descendantIds(child));
  }
  return out;
}

// Does anything in the node's subtree (excluding the node) carry its own scope?
function anyDescendantScoped(node: SchemaNode, scope: ScopeMap): boolean {
  for (const child of node.children) {
    if (scope.has(child.id)) return true;
    if (anyDescendantScoped(child, scope)) return true;
  }
  return false;
}

// The node's displayed state, given its own scope, an ancestor's family cover,
// and its subtree. Ancestor-family wins (the node is covered regardless of its
// own scope), matching the runtime picker's "under a checked container" lock.
export function pickState(node: SchemaNode, scope: ScopeMap, ancestorFamily: boolean): PickState {
  if (ancestorFamily) return "implied";
  const own = scope.get(node.id);
  if (own === "family") return "family";
  if (own === "exact") return "exact";
  return anyDescendantScoped(node, scope) ? "indeterminate" : "off";
}

// Concrete leaves under `node` that a scope covers — a `family` here or above
// covers all of them; otherwise a leaf counts when it (or a branch above it
// within the subtree) is `family`, or the leaf is itself scoped.
function coveredLeafCount(node: SchemaNode, scope: ScopeMap, underFamily: boolean): number {
  const family = underFamily || scope.get(node.id) === "family";
  if (node.children.length === 0) {
    if (node.abstract) return 0;
    return family || scope.has(node.id) ? 1 : 0;
  }
  if (family) return concreteLeaves(node).length;
  let sum = 0;
  for (const child of node.children) sum += coveredLeafCount(child, scope, false);
  return sum;
}

// Cycle a node's scope on click, returning a NEW map (pure). Setting a node to
// `family` clears every descendant's own scope — the family fact subsumes them,
// keeping the encoding minimal (one `{descendants_of}`, not parent-family plus
// child leaves).
export function cycleScope(scope: ScopeMap, node: SchemaNode): ScopeMap {
  const next = new Map(scope);
  const cur = next.get(node.id);
  const setFamily = () => {
    next.set(node.id, "family");
    for (const id of descendantIds(node)) next.delete(id);
  };
  switch (nodeCapability(node)) {
    case "concrete-leaf":
      if (cur === "exact") next.delete(node.id);
      else next.set(node.id, "exact");
      break;
    case "abstract-branch":
      if (cur === "family") next.delete(node.id);
      else setFamily();
      break;
    case "concrete-branch":
      if (cur === undefined) next.set(node.id, "exact");
      else if (cur === "exact") setFamily();
      else next.delete(node.id); // family → off
      break;
    case "none":
      break;
  }
  return next;
}

export function flattenForRender(
  roots: SchemaNode[],
  scope: ScopeMap,
  collapsed: Set<string>,
): RenderedNode[] {
  const out: RenderedNode[] = [];
  function walk(node: SchemaNode, depth: number, ancestorFamily: boolean) {
    const capability = nodeCapability(node);
    const hasChildren = node.children.length > 0;
    const isCollapsed = hasChildren && collapsed.has(node.id);
    const leaves = concreteLeaves(node);
    out.push({
      id: node.id,
      name: node.name,
      abstract: node.abstract,
      depth,
      state: pickState(node, scope, ancestorFamily),
      capability,
      interactive: !ancestorFamily && capability !== "none",
      hasChildren,
      collapsed: isCollapsed,
      pickedCount: coveredLeafCount(node, scope, ancestorFamily),
      totalLeaves: leaves.length,
    });
    if (!isCollapsed) {
      const childAncestorFamily = ancestorFamily || scope.get(node.id) === "family";
      for (const child of node.children) walk(child, depth + 1, childAncestorFamily);
    }
  }
  for (const root of roots) walk(root, 0, false);
  return out;
}
