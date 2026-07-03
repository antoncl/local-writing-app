// The view designer's graph model + its (de)serialization to a `ViewExpr`
// tree (0.5.0 step 3, #80). The designer canvas (ViewBodyView) is a Svelte
// Flow DAG; this pure module is the bridge between that node/edge graph and
// the portable `ViewSpec.expr` the evaluator (evaluateView.ts) consumes.
//
// Kept pure and framework-free so the round-trip (graph → expr → graph) is
// unit-testable, mirroring evaluateView. Auto-layout is deterministic (no
// Date/random) so a reloaded saved view lays out stably.
//
// Set-algebra grammar (ADR-0018/0021): every node has exactly one primary
// slot. Combinators wire children through edges; the `output` node's single
// upstream is the root expr. Difference is non-commutative — its two inputs
// carry explicit `keep` / `remove` handle roles (doc §1.2, the confusable op).

import type { ViewExpr, ViewFieldPredicate } from "@/lib/types";

export type LeafKind = "type" | "descendants_of" | "tagged" | "field" | "hand_picked" | "view_ref";
export type CombinatorKind = "union" | "intersect" | "difference" | "complement";
export type AnnotateKind = "group" | "highlight";
// "output" is the single sink; its upstream node is the view's root expr.
export type GraphNodeKind = "output" | CombinatorKind | AnnotateKind | LeafKind;

// Per-node config. A superset of the slots ViewExpr carries — only the fields
// relevant to a node's `kind` are read. Mirrors ViewExpr field names so
// serialization is a direct lift.
export type ViewNodeData = {
  // leaf configs
  type?: string;
  descendants_of?: string;
  tagged?: string;
  field?: ViewFieldPredicate;
  hand_picked?: string[];
  view_ref?: string;
  // annotate configs (group = label[+color], highlight = color)
  label?: string;
  rank?: number;
  color?: string;
};

export type ViewGraphNode = {
  id: string;
  kind: GraphNodeKind;
  position: { x: number; y: number };
  data: ViewNodeData;
};

// A directed edge source→target. Handles carry explicit ids so Svelte Flow can
// render the edge: `sourceHandle` is always the leaf/op output ("out"),
// `targetHandle` is the input port ("in", or "keep"/"remove" on a difference).
export type ViewGraphEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export type ViewGraph = { nodes: ViewGraphNode[]; edges: ViewGraphEdge[] };

export const OUTPUT_NODE_ID = "output";

const LEAF_KINDS: LeafKind[] = ["type", "descendants_of", "tagged", "field", "hand_picked", "view_ref"];
export function isLeafKind(kind: GraphNodeKind): kind is LeafKind {
  return (LEAF_KINDS as string[]).includes(kind);
}

// How many upstream inputs a node kind accepts. Combinators + annotate consume
// edges; leaves are sources with none.
export function inputArity(kind: GraphNodeKind): "none" | "one" | "many" | "keep_remove" {
  switch (kind) {
    case "union":
    case "intersect":
      return "many";
    case "difference":
      return "keep_remove";
    case "complement":
    case "group":
    case "highlight":
    case "output":
      return "one";
    default:
      return "none"; // leaves
  }
}

// Would adding an edge source→target introduce a cycle? True when `target`
// can already reach `source` following edges upstream→downstream (source→target
// direction), i.e. `source` is downstream of `target`. Used by the designer to
// reject cyclic wiring before it is committed.
export function wouldCycle(edges: ViewGraphEdge[], source: string, target: string): boolean {
  if (source === target) return true;
  // Walk downstream from `target`; if we reach `source`, the new edge closes a loop.
  const stack = [target];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === source) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const e of edges) if (e.source === cur) stack.push(e.target);
  }
  return false;
}

// --- graph → expr --------------------------------------------------------

// Serialize the graph reachable from the output node into a ViewExpr tree.
// Returns null for an empty/unwired graph (→ whole-universe view). Incomplete
// wiring degrades gracefully: a combinator with no valid children collapses to
// null (dropped) rather than throwing, so the live preview stays responsive
// while the user is mid-compose.
export function graphToExpr(graph: ViewGraph): ViewExpr | null {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const root = upstreamOf(graph, OUTPUT_NODE_ID)[0];
  if (!root) return null;
  return buildExpr(graph, byId, root.source, new Set());
}

function upstreamOf(graph: ViewGraph, nodeId: string): ViewGraphEdge[] {
  return graph.edges.filter((e) => e.target === nodeId);
}

function buildExpr(
  graph: ViewGraph,
  byId: Map<string, ViewGraphNode>,
  nodeId: string,
  seen: Set<string>,
): ViewExpr | null {
  if (seen.has(nodeId)) return null; // defensive: designer cycle
  const node = byId.get(nodeId);
  if (!node) return null;
  seen.add(nodeId);
  try {
    switch (node.kind) {
      case "union":
      case "intersect": {
        const children = orderedChildren(graph, byId, nodeId, seen);
        if (children.length === 0) return null;
        return node.kind === "union" ? { union: children } : { intersect: children };
      }
      case "difference": {
        const keepEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "keep");
        const removeEdge = upstreamOf(graph, nodeId).find((e) => e.targetHandle === "remove");
        const keep = keepEdge ? buildExpr(graph, byId, keepEdge.source, seen) : null;
        if (!keep) return null; // nothing to keep → nothing to show
        const remove = removeEdge ? buildExpr(graph, byId, removeEdge.source, seen) : null;
        // No remove wired yet → the difference is a pass-through of `keep`.
        return remove ? { difference: { keep, remove } } : keep;
      }
      case "complement": {
        const inner = orderedChildren(graph, byId, nodeId, seen)[0];
        return inner ? { complement: inner } : null;
      }
      case "group":
      case "highlight": {
        const inner = orderedChildren(graph, byId, nodeId, seen)[0];
        if (!inner) return null;
        return { annotate: annotatePayload(node), of: inner };
      }
      default:
        return leafExpr(node);
    }
  } finally {
    seen.delete(nodeId);
  }
}

// Children of a node in a stable order (upstream node position: top-to-bottom,
// then left-to-right), skipping unwired/incomplete branches.
function orderedChildren(
  graph: ViewGraph,
  byId: Map<string, ViewGraphNode>,
  nodeId: string,
  seen: Set<string>,
): ViewExpr[] {
  const edges = [...upstreamOf(graph, nodeId)].sort((a, b) => {
    const na = byId.get(a.source);
    const nb = byId.get(b.source);
    return (na?.position.y ?? 0) - (nb?.position.y ?? 0) || (na?.position.x ?? 0) - (nb?.position.x ?? 0);
  });
  const out: ViewExpr[] = [];
  for (const e of edges) {
    const child = buildExpr(graph, byId, e.source, seen);
    if (child) out.push(child);
  }
  return out;
}

function annotatePayload(node: ViewGraphNode): ViewExpr["annotate"] {
  if (node.kind === "highlight") {
    return { color: node.data.color ?? "" };
  }
  // group: label (+ optional rank/color)
  const payload: NonNullable<ViewExpr["annotate"]> = { label: node.data.label ?? "" };
  if (node.data.rank !== undefined) payload.rank = node.data.rank;
  if (node.data.color) payload.color = node.data.color;
  return payload;
}

// A leaf node → its ViewExpr leaf slot. Returns null when unconfigured so a
// blank leaf doesn't silently mean "whole universe".
function leafExpr(node: ViewGraphNode): ViewExpr | null {
  const d = node.data;
  switch (node.kind) {
    case "type":
      return d.type ? { type: d.type } : null;
    case "descendants_of":
      return d.descendants_of ? { descendants_of: d.descendants_of } : null;
    case "tagged":
      return d.tagged ? { tagged: d.tagged } : null;
    case "field":
      return d.field?.key ? { field: d.field } : null;
    case "hand_picked":
      return d.hand_picked && d.hand_picked.length > 0 ? { hand_picked: d.hand_picked } : null;
    case "view_ref":
      return d.view_ref ? { view_ref: d.view_ref } : null;
    default:
      return null;
  }
}

// --- expr → graph --------------------------------------------------------

const COL_WIDTH = 260;
const ROW_HEIGHT = 120;

// Rebuild a designer graph from a stored expr, with deterministic layered
// auto-layout: depth 0 (root) sits nearest the output at the right; leaves fan
// out to the left. Rows are assigned by a running counter so siblings stack.
export function exprToGraph(expr: ViewExpr | null | undefined): ViewGraph {
  const nodes: ViewGraphNode[] = [];
  const edges: ViewGraphEdge[] = [];
  const rowCursor = { value: 0 };
  let counter = 0;
  const nextId = () => `n${counter++}`;

  // Output node anchors the right column; its depth is -1 so the root lands at 0.
  const outputNode: ViewGraphNode = {
    id: OUTPUT_NODE_ID,
    kind: "output",
    position: { x: 0, y: 0 },
    data: {},
  };
  nodes.push(outputNode);

  if (expr) {
    const rootId = walk(expr, 0);
    if (rootId) link(rootId, OUTPUT_NODE_ID);
  }

  // Depth → x column (root at high x near output, leaves at low x). Find max
  // depth to invert so leaves sit left. Output pinned rightmost.
  const maxDepth = nodes.reduce((m, n) => Math.max(m, (n.data as { _depth?: number })._depth ?? 0), 0);
  for (const n of nodes) {
    if (n.id === OUTPUT_NODE_ID) {
      n.position.x = (maxDepth + 1) * COL_WIDTH;
    } else {
      const depth = (n.data as { _depth?: number })._depth ?? 0;
      n.position.x = (maxDepth - depth) * COL_WIDTH;
    }
    delete (n.data as { _depth?: number })._depth;
  }
  // Center the output vertically-ish against the spread of rows.
  outputNode.position.y = ((rowCursor.value - 1) * ROW_HEIGHT) / 2;

  return { nodes, edges };

  // Returns the created node's id (or null for an unrepresentable expr).
  function walk(e: ViewExpr, depth: number): string | null {
    if (e.union || e.intersect) {
      const children = (e.union ?? e.intersect)!;
      const id = addNode(e.union ? "union" : "intersect", depth, {});
      for (const child of children) {
        const childId = walk(child, depth + 1);
        if (childId) link(childId, id);
      }
      return id;
    }
    if (e.difference) {
      const id = addNode("difference", depth, {});
      const keepId = walk(e.difference.keep, depth + 1);
      const removeId = walk(e.difference.remove, depth + 1);
      if (keepId) link(keepId, id, "keep");
      if (removeId) link(removeId, id, "remove");
      return id;
    }
    if (e.complement) {
      const id = addNode("complement", depth, {});
      const innerId = walk(e.complement, depth + 1);
      if (innerId) link(innerId, id);
      return id;
    }
    if (e.annotate && e.of) {
      const isGroup = e.annotate.label !== undefined;
      const id = addNode(isGroup ? "group" : "highlight", depth, {
        label: e.annotate.label,
        rank: e.annotate.rank,
        color: e.annotate.color,
      });
      const innerId = walk(e.of, depth + 1);
      if (innerId) link(innerId, id);
      return id;
    }
    // leaves
    if (e.type !== undefined) return addNode("type", depth, { type: e.type });
    if (e.descendants_of !== undefined) return addNode("descendants_of", depth, { descendants_of: e.descendants_of });
    if (e.tagged !== undefined) return addNode("tagged", depth, { tagged: e.tagged });
    if (e.field !== undefined) return addNode("field", depth, { field: e.field });
    if (e.hand_picked !== undefined) return addNode("hand_picked", depth, { hand_picked: e.hand_picked });
    if (e.view_ref !== undefined) return addNode("view_ref", depth, { view_ref: e.view_ref });
    return null;
  }

  // Emit an edge with explicit handle ids so Svelte Flow renders it on load.
  function link(source: string, target: string, targetHandle = "in"): void {
    edges.push({ id: nextId(), source, sourceHandle: "out", target, targetHandle });
  }

  function addNode(kind: GraphNodeKind, depth: number, data: ViewNodeData): string {
    const id = nextId();
    const y = rowCursor.value * ROW_HEIGHT;
    rowCursor.value += 1;
    nodes.push({ id, kind, position: { x: 0, y }, data: { ...data, _depth: depth } as ViewNodeData });
    return id;
  }
}
