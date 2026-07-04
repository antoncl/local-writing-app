import { describe, expect, it } from "vitest";
import type { ViewExpr } from "@/lib/types";
import {
  exprToGraph,
  graphToExpr,
  graphToSpec,
  specToGraph,
  OUTPUT_NODE_ID,
  type ViewGraph,
  type ViewGraphNode,
} from "./viewGraph";

// Round-trip an expr through a graph and back. exprToGraph lays it out; the
// deterministic top-to-bottom row order is what graphToExpr reads back for
// n-ary child ordering, so a lossless round-trip is the core invariant.
function roundTrip(expr: ViewExpr): ViewExpr | null {
  return graphToExpr(exprToGraph(expr));
}

// Small graph-builder helpers so the role/lowering tests read declaratively.
const out = (data: ViewGraphNode["data"] = {}): ViewGraphNode => ({
  id: OUTPUT_NODE_ID,
  kind: "output",
  position: { x: 1000, y: 0 },
  data,
});
let seq = 0;
const node = (kind: ViewGraphNode["kind"], data: ViewGraphNode["data"], y = seq++ * 100): ViewGraphNode => ({
  id: `x${seq++}`,
  kind,
  position: { x: 0, y },
  data,
});
const edge = (source: string, target: string, targetHandle = "in"): ViewGraph["edges"][number] => ({
  id: `e${seq++}`,
  source,
  sourceHandle: "out",
  target,
  targetHandle,
});

describe("viewGraph serialization (round-trip)", () => {
  it("empty graph → null expr (whole universe)", () => {
    const graph: ViewGraph = { nodes: [out()], edges: [] };
    expect(graphToExpr(graph)).toBeNull();
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

  it("round-trips union / intersect / difference / complement", () => {
    const exprs: ViewExpr[] = [
      { union: [{ type: "lore:character" }, { tagged: "villain" }] },
      { intersect: [{ descendants_of: "lore:deity" }, { tagged: "gotham" }] },
      { difference: { keep: { descendants_of: "lore:character" }, remove: { descendants_of: "lore:deity" } } },
      { complement: { tagged: "draft" } },
    ];
    for (const e of exprs) expect(roundTrip(e)).toEqual(e);
  });

  it("round-trips a highlight (color annotate) over a leaf", () => {
    const expr: ViewExpr = { annotate: { color: "gotham" }, of: { tagged: "gotham" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("rebuilds leaf kinds from a dense-null expr (backend API shape)", () => {
    const dense = (o: Partial<ViewExpr>): ViewExpr =>
      ({
        union: null, intersect: null, difference: null, complement: null,
        annotate: null, of: null, type: null, descendants_of: null,
        tagged: null, field: null, hand_picked: null, view_ref: null, ...o,
      }) as unknown as ViewExpr;
    const expr = dense({ union: [dense({ type: "assistant:assistant" }), dense({ tagged: "OpenAI" })] });
    const kinds = exprToGraph(expr).nodes.map((n) => n.kind).sort();
    expect(kinds).toEqual(["output", "tagged", "type", "union"]);
  });

  it("a label-only annotate is an inert pass-through (grouping is retired)", () => {
    // Pre-#91 layouts may carry annotate label nodes; the expr lowers to just
    // its input (no group), and specToGraph skips the annotate on reopen.
    const expr = { annotate: { label: "Cast" }, of: { type: "lore:character" } } as unknown as ViewExpr;
    const kinds = exprToGraph(expr).nodes.map((n) => n.kind).sort();
    expect(kinds).toEqual(["output", "type"]);
  });

  it("drops an unconfigured leaf (blank type ≠ whole universe)", () => {
    const leaf = node("type", {}, 0);
    const graph: ViewGraph = { nodes: [out(), leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });
});

describe("injector: All (universal)", () => {
  it("a bare All → whole universe (null expr)", () => {
    const all = node("all", {}, 0);
    const graph: ViewGraph = { nodes: [out(), all], edges: [edge(all.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });
});

describe("filter lowering (sugar → set ops)", () => {
  it("keep off All collapses to the bare predicate", () => {
    const all = node("all", {}, 0);
    const f = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:character" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), all, f],
      edges: [edge(all.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ type: "lore:character" });
  });

  it("drop off All → complement of the predicate", () => {
    const all = node("all", {}, 0);
    const f = node("filter", { filter_kind: "tagged", filter_mode: "drop", tagged: "archived" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), all, f],
      edges: [edge(all.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ complement: { tagged: "archived" } });
  });

  it("keep on a concrete input → intersect(input, predicate)", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const f = node("filter", { filter_kind: "tagged", filter_mode: "keep", tagged: "hero" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, f],
      edges: [edge(src.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ intersect: [{ type: "lore:character" }, { tagged: "hero" }] });
  });

  it("drop on a concrete input → difference(input, predicate)", () => {
    const src = node("descendants_of", { descendants_of: "lore:deity" }, 0);
    const f = node("filter", { filter_kind: "type", filter_mode: "drop", type: "lore:demigod" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, f],
      edges: [edge(src.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({
      difference: { keep: { descendants_of: "lore:deity" }, remove: { type: "lore:demigod" } },
    });
  });

  it("an unconfigured filter is a pass-through", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const f = node("filter", { filter_kind: "field", filter_mode: "keep" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, f],
      edges: [edge(src.id, f.id), edge(f.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ type: "lore:character" });
  });

  it("chained filters narrow successively (series = AND)", () => {
    const all = node("all", {}, 0);
    const f1 = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:character" }, 100);
    const f2 = node("filter", { filter_kind: "tagged", filter_mode: "keep", tagged: "hero" }, 200);
    const graph: ViewGraph = {
      nodes: [out(), all, f1, f2],
      edges: [edge(all.id, f1.id), edge(f1.id, f2.id), edge(f2.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toEqual({ intersect: [{ type: "lore:character" }, { tagged: "hero" }] });
  });
});

describe("named handles → grouped spec", () => {
  it("2 handles → an ordered groups list (handle order = group order)", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Gods" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, gods],
      edges: [edge(cast.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
    expect(spec.expr).toBeUndefined();
  });

  it("multiple wires into one handle → union + dedupe (same-handle)", () => {
    const output = out({ handles: [{ id: "h0", name: "Folk" }, { id: "h1", name: "Places" }] });
    const a = node("type", { type: "lore:character" }, 0);
    const b = node("type", { type: "lore:deity" }, 100);
    const c = node("type", { type: "lore:location" }, 200);
    const graph: ViewGraph = {
      nodes: [output, a, b, c],
      edges: [
        edge(a.id, OUTPUT_NODE_ID, "h0"),
        edge(b.id, OUTPUT_NODE_ID, "h0"),
        edge(c.id, OUTPUT_NODE_ID, "h1"),
      ],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Folk", expr: { union: [{ type: "lore:character" }, { type: "lore:deity" }] } },
      { name: "Places", expr: { type: "lore:location" } },
    ]);
  });

  it("a whole-universe handle (bare All) → group with null expr", () => {
    const output = out({ handles: [{ id: "h0", name: "Everything" }, { id: "h1", name: "Gods" }] });
    const all = node("all", {}, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, all, gods],
      edges: [edge(all.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Everything", expr: null },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });

  it("only one populated handle collapses to a flat expr", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Empty" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const graph: ViewGraph = { nodes: [output, cast], edges: [edge(cast.id, OUTPUT_NODE_ID, "h0")] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toBeUndefined();
    expect(spec.expr).toEqual({ type: "lore:character" });
  });
});

describe("sorter (per-segment sort)", () => {
  it("a Sorter feeding the View sets the flat sort", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: { by: "title", dir: "asc" } }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, s],
      edges: [edge(src.id, s.id), edge(s.id, OUTPUT_NODE_ID)],
    };
    const spec = graphToSpec(graph, { kind: "lore", sort: { by: "manual" } });
    expect(spec.expr).toEqual({ type: "lore:character" });
    expect(spec.sort).toEqual({ by: "title", dir: "asc" });
  });

  it("a Sorter before a handle sets that group's sort", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Gods" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: { by: "title", dir: "asc" } }, 50);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, s, gods],
      edges: [
        edge(cast.id, s.id),
        edge(s.id, OUTPUT_NODE_ID, "h0"),
        edge(gods.id, OUTPUT_NODE_ID, "h1"),
      ],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" }, sort: { by: "title", dir: "asc" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });
});

describe("specToGraph (reopen fallback)", () => {
  it("rebuilds a grouped spec into named handles + one source each", () => {
    const graph = exprToGraph(null); // sanity: empty
    expect(graph.nodes.map((n) => n.kind)).toEqual(["output"]);

    const spec = {
      kind: "lore",
      groups: [
        { name: "Cast", expr: { type: "lore:character" } },
        { name: "Gods", expr: { descendants_of: "lore:deity" }, sort: { by: "title" as const } },
      ],
    };
    const rebuilt = graphToSpec(specToGraph(spec), { kind: "lore" });
    expect(rebuilt.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" }, sort: { by: "title" } },
    ]);
  });
});
