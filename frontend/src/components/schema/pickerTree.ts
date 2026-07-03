// Pure schema-tree helpers for NodePickerConfigEditor. Extracted to keep the
// component under the file-size cap: these functions have no reactive/component
// state — they turn the project's metadata schema into a checkbox tree and
// derive per-node checked state. The component owns selection/collapse state and
// calls into these.

import type { MetadataSchema } from "@/lib/types";

export type SchemaNode = {
  id: string;
  name: string;
  abstract: boolean;
  children: SchemaNode[];
};

export type RenderedNode = {
  id: string;
  name: string;
  abstract: boolean;
  depth: number;
  state: "checked" | "indeterminate" | "unchecked";
  hasLeaves: boolean;
  hasChildren: boolean;
  collapsed: boolean;
  pickedCount: number;
  totalLeaves: number;
};

// Build the per-kind tree from the project schema. Roots are entry types whose
// `parent` is null; descendants attach via the parent chain. Abstract types act
// as containers — they're rendered as checkboxes too, but checking them toggles
// their concrete descendants (abstracts have no instances so they're not stored).
export function buildTree(schema: MetadataSchema | null, kind: string): SchemaNode[] {
  if (!schema) return [];
  type Raw = { id: string; name: string; abstract: boolean; parent: string | null };
  const raw: Raw[] = Object.entries(schema.entry_types ?? {})
    .filter(([, def]) => def.kind === kind)
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

export function concreteLeaves(node: SchemaNode): string[] {
  if (node.children.length === 0) return node.abstract ? [] : [node.id];
  const out: string[] = [];
  for (const child of node.children) out.push(...concreteLeaves(child));
  return out;
}

export function nodeState(
  node: SchemaNode,
  selection: Set<string>,
): "checked" | "indeterminate" | "unchecked" {
  const leaves = concreteLeaves(node);
  if (leaves.length === 0) return "unchecked";
  const inSet = leaves.filter((id) => selection.has(id)).length;
  if (inSet === leaves.length) return "checked";
  if (inSet === 0) return "unchecked";
  return "indeterminate";
}

export function flattenForRender(
  roots: SchemaNode[],
  selection: Set<string>,
  collapsed: Set<string>,
): RenderedNode[] {
  const out: RenderedNode[] = [];
  function walk(node: SchemaNode, depth: number) {
    const leaves = concreteLeaves(node);
    const picked = leaves.filter((id) => selection.has(id)).length;
    const hasChildren = node.children.length > 0;
    const isCollapsed = hasChildren && collapsed.has(node.id);
    out.push({
      id: node.id,
      name: node.name,
      abstract: node.abstract,
      depth,
      state: nodeState(node, selection),
      hasLeaves: leaves.length > 0,
      hasChildren,
      collapsed: isCollapsed,
      pickedCount: picked,
      totalLeaves: leaves.length,
    });
    if (!isCollapsed) {
      for (const child of node.children) walk(child, depth + 1);
    }
  }
  for (const root of roots) walk(root, 0);
  return out;
}
