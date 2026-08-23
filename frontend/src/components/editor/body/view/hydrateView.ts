// Canvas hydration + wire tagging, extracted from ViewBodyView (size cap).
//
// Build the canvas graph for a view: from its persisted designer `layout`
// (author's exact positions + wiring) when present, else auto-laid-out from
// the semantic `expr` (designer-less / legacy / backend-authored views).
import type { Node, Edge } from "@xyflow/svelte";
import {
  specToGraph,
  outputPayload,
  type GraphNodeKind,
  type ViewGraphNode,
  type ViewNodeData,
} from "@/lib/views/viewGraph";
import { repairGraphCycles as repairEdges } from "@/lib/views/cycleCheck";
import type { MetadataSchema, ViewNode } from "@/lib/types";

/** The custom node payload every canvas node carries. */
export type FlowData = { kind: GraphNodeKind; cfg: ViewNodeData };

export function toFlowNode(id: string, k: GraphNodeKind, cfg: ViewNodeData, position: { x: number; y: number }): Node<FlowData> {
  return { id, type: "viewNode", position, data: { kind: k, cfg }, deletable: k !== "output" };
}

// The two wire types (ADR-0031 §D): a node-set pipe (solid, the default) vs a
// value-set pipe (a scalar `field_of` — dashed, tinted the value colour). The
// class is derived from the source's `outputPayload`, so it survives a layout
// round-trip (never persisted) — recomputed on hydrate, connect, and whenever a
// field_of's projected field changes its payload.
export function edgeClass(sourceId: string, nodes: Node<FlowData>[], schema: MetadataSchema | null): string | undefined {
  const s = nodes.find((n) => n.id === sourceId);
  if (!s) return undefined;
  const gn: ViewGraphNode = { id: s.id, kind: s.data.kind, position: s.position, data: s.data.cfg ?? {} };
  const fieldDef = (key: string) => schema?.fields?.[key] ?? null;
  return outputPayload(gn, fieldDef) === "value-set" ? "value-wire" : undefined;
}

// Assign both the stroke class (node-set vs value-set) and the render type. A
// normal wire uses the custom `ViewEdge` (which carries the × remove affordance,
// #172); a recursion self-loop keeps `SelfLoopEdge` (custom routing, no ×).
export function tagEdge(e: Edge, nodes: Node<FlowData>[], schema: MetadataSchema | null): Edge {
  const cls = edgeClass(e.source, nodes, schema);
  const type = e.source === e.target ? "selfloop" : "wire";
  return (e.class ?? undefined) === cls && e.type === type ? e : { ...e, class: cls, type };
}

export function hydrateGraph(node: ViewNode, schema: MetadataSchema | null): { nodes: Node<FlowData>[]; edges: Edge[] } {
  const layout = node.layout;
  if (layout && layout.nodes.length > 0) {
    const rawNodes = layout.nodes.map((n) =>
      toFlowNode(n.id, n.kind as GraphNodeKind, (n.cfg ?? {}) as ViewNodeData, n.position),
    );
    const rawEdges = layout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_handle ?? undefined,
      targetHandle: e.target_handle ?? undefined,
      type: e.source === e.target ? "selfloop" : "wire",
    }));
    // A persisted layout is authored in the first-class idiom (#271 retired the
    // bare-predicate-leaf → `All → Filter` canonicalization), so it hydrates as-is.
    return { nodes: rawNodes, edges: rawEdges.map((e) => ({ ...e, class: edgeClass(e.source, rawNodes, schema) })) };
  }
  const g = specToGraph(node.spec, schema);
  const nodes = g.nodes.map((n) => toFlowNode(n.id, n.kind, n.data, n.position));
  return {
    nodes,
    edges: g.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle ?? undefined,
      targetHandle: e.targetHandle ?? undefined,
      type: e.source === e.target ? "selfloop" : "wire",
      class: edgeClass(e.source, nodes, schema),
    })),
  };
}

// Load-time DAG-invariant repair (#275, ADR-0028 §D): silently drop any illegal
// back-edge in the hydrated graph (a hand-edited file / a previously-buggy
// designer's output) so the view still opens; the repair persists on the next
// debounced save. The invariant + the one legal exception live in cycleCheck.
export function repairGraphCycles(graph: { nodes: Node<FlowData>[]; edges: Edge[] }): {
  nodes: Node<FlowData>[];
  edges: Edge[];
} {
  const kindById = new Map(graph.nodes.map((n) => [n.id, n.data.kind]));
  const { edges, dropped } = repairEdges(kindById, graph.edges);
  if (dropped.length > 0 && import.meta.env.DEV) {
    console.warn(`[views] load-time repair: dropped ${dropped.length} cyclic edge(s)`, dropped);
  }
  return { nodes: graph.nodes, edges };
}
