import { describe, expect, it } from "vitest";
import type { ViewExpr } from "@/lib/types";
import { exprToGraph, graphToExpr, OUTPUT_NODE_ID, type ViewGraph } from "./viewGraph";

// Round-trip an expr through a graph and back. exprToGraph lays it out; the
// deterministic top-to-bottom row order is what graphToExpr reads back for
// n-ary child ordering, so a lossless round-trip is the core invariant.
function roundTrip(expr: ViewExpr): ViewExpr | null {
  return graphToExpr(exprToGraph(expr));
}

describe("viewGraph serialization", () => {
  it("empty graph → null expr (whole universe)", () => {
    const graph: ViewGraph = { nodes: [{ id: OUTPUT_NODE_ID, kind: "output", position: { x: 0, y: 0 }, data: {} }], edges: [] };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("round-trips a single type leaf", () => {
    const expr: ViewExpr = { type: "lore:character" };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips each leaf kind", () => {
    const leaves: ViewExpr[] = [
      { type: "lore:character" },
      { descendants_of: "lore:character" },
      { tagged: "gotham" },
      { field: { key: "pov", op: "eq", value: "honor" } },
      { hand_picked: ["a", "b"] },
      { view_ref: "view-123" },
    ];
    for (const leaf of leaves) expect(roundTrip(leaf)).toEqual(leaf);
  });

  it("rebuilds leaf kinds from a dense-null expr (backend API shape)", () => {
    // The backend serializes ViewExpr densely: every unused slot is present as
    // null, not omitted. exprToGraph must key off `!= null`, not `!== undefined`
    // — otherwise every leaf matches the `type` slot (type: null) and reloads as
    // a "type" node. Regression for the "everything is a type-picker" bug.
    const dense = (o: Partial<ViewExpr>): ViewExpr =>
      ({
        union: null, intersect: null, difference: null, complement: null,
        annotate: null, of: null, type: null, descendants_of: null,
        tagged: null, field: null, hand_picked: null, view_ref: null, ...o,
      }) as unknown as ViewExpr;
    const expr = dense({
      union: [
        dense({ annotate: { label: "Anthropic", rank: 10 }, of: dense({ type: "assistant:assistant" }) }),
        dense({ annotate: { label: "OpenAI", rank: -3 }, of: dense({ tagged: "OpenAI" }) }),
      ],
    });
    const kinds = exprToGraph(expr).nodes.map((n) => n.kind).sort();
    expect(kinds).toEqual(["group", "group", "output", "tagged", "type", "union"]);
  });

  it("round-trips a union of two leaves", () => {
    const expr: ViewExpr = { union: [{ type: "lore:character" }, { tagged: "villain" }] };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips a difference with keep/remove roles", () => {
    const expr: ViewExpr = {
      difference: { keep: { descendants_of: "lore:character" }, remove: { descendants_of: "lore:deity" } },
    };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips complement", () => {
    const expr: ViewExpr = { complement: { tagged: "draft" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips a group annotate over a leaf", () => {
    const expr: ViewExpr = { annotate: { label: "Characters", rank: 1 }, of: { descendants_of: "lore:character" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips a highlight annotate over a leaf", () => {
    const expr: ViewExpr = { annotate: { color: "gotham" }, of: { tagged: "gotham" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips the doc §2 worked example (union of two grouped branches)", () => {
    const expr: ViewExpr = {
      union: [
        {
          annotate: { label: "Characters", rank: 1 },
          of: {
            difference: { keep: { descendants_of: "lore:character" }, remove: { descendants_of: "lore:deity" } },
          },
        },
        { annotate: { label: "Deities", rank: 2 }, of: { descendants_of: "lore:deity" } },
      ],
    };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("drops an unconfigured leaf (blank type ≠ whole universe)", () => {
    const graph: ViewGraph = {
      nodes: [
        { id: OUTPUT_NODE_ID, kind: "output", position: { x: 0, y: 0 }, data: {} },
        { id: "leaf", kind: "type", position: { x: -260, y: 0 }, data: {} },
      ],
      edges: [{ id: "e", source: "leaf", target: OUTPUT_NODE_ID, targetHandle: "in" }],
    };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("treats a difference with no remove wired as a pass-through of keep", () => {
    const graph: ViewGraph = {
      nodes: [
        { id: OUTPUT_NODE_ID, kind: "output", position: { x: 0, y: 0 }, data: {} },
        { id: "diff", kind: "difference", position: { x: -260, y: 0 }, data: {} },
        { id: "keep", kind: "type", position: { x: -520, y: 0 }, data: { type: "lore:character" } },
      ],
      edges: [
        { id: "e1", source: "diff", target: OUTPUT_NODE_ID, targetHandle: "in" },
        { id: "e2", source: "keep", target: "diff", targetHandle: "keep" },
      ],
    };
    expect(graphToExpr(graph)).toEqual({ type: "lore:character" });
  });
});
