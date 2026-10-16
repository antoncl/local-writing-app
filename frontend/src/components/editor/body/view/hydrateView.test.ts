// tagEdge assigns the render TYPE that decides which custom edge a connection
// uses: a normal wire → ViewEdge (which carries the × remove affordance, #172),
// a recursion self-loop → SelfLoopEdge (custom routing, no ×). These lock that a
// plain connection is a "wire" — so the × affordance actually applies to it — and
// that re-tagging is idempotent (no churn on the designer's edge sweeps).
import { describe, expect, it } from "vitest";
import type { Edge } from "@xyflow/svelte";
import { buildInferenceGraph, tagEdge, toFlowNode, toGraph, toLayout } from "./hydrateView";

const nodes = [
  toFlowNode("a", "all", {}, { x: 0, y: 0 }),
  toFlowNode("b", "filter", {}, { x: 100, y: 0 }),
];

describe("tagEdge", () => {
  it("types a normal connection as a 'wire' (the ViewEdge × affordance)", () => {
    const tagged = tagEdge({ id: "e1", source: "a", target: "b" } as Edge, nodes, null);
    expect(tagged.type).toBe("wire");
  });

  it("types a self-loop as 'selfloop' (recursion routing, no ×)", () => {
    const tagged = tagEdge({ id: "e2", source: "a", target: "a" } as Edge, nodes, null);
    expect(tagged.type).toBe("selfloop");
  });

  it("is idempotent — re-tagging an already-tagged edge returns the same object", () => {
    const once = tagEdge({ id: "e3", source: "a", target: "b" } as Edge, nodes, null);
    const twice = tagEdge(once, nodes, null);
    expect(twice).toBe(once);
  });
});

describe("canvas → graph converters", () => {
  const edges = [{ id: "e1", source: "a", target: "b", sourceHandle: "orphans" } as Edge];

  it("toGraph keeps the source handle (the Nest orphans output) and nulls absent handles", () => {
    expect(toGraph(nodes, edges).edges).toEqual([
      { id: "e1", source: "a", target: "b", sourceHandle: "orphans", targetHandle: null },
    ]);
  });

  it("toLayout is lossless: positions, cfg and snake_case handles", () => {
    const layout = toLayout(nodes, edges);
    expect(layout.nodes[1]).toEqual({ id: "b", kind: "filter", position: { x: 100, y: 0 }, cfg: {} });
    expect(layout.edges).toEqual([
      { id: "e1", source: "a", target: "b", source_handle: "orphans", target_handle: null },
    ]);
  });

  it("buildInferenceGraph indexes nodes by id and slims edges to the target handle", () => {
    const g = buildInferenceGraph(nodes, edges);
    expect([...g.byId.keys()]).toEqual(["a", "b"]);
    expect(g.edges).toEqual([{ id: "e1", source: "a", target: "b", targetHandle: null }]);
  });
});
