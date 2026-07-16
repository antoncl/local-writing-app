import { describe, expect, it } from "vitest";
import type { NodePickerConfig, ViewExpr } from "@/lib/types";
import { defaultView } from "./evaluateView";
import {
  classifyConnection,
  collectParamBindings,
  connectionAllowed,
  exprToGraph,
  graphToExpr,
  graphToSpec,
  inferInputTypes,
  inputKinds,
  tagAppliesToInput,
  outputPayload,
  reachesFieldOf,
  specToGraph,
  valueSlotAccepts,
  FILTER_VALUE_HANDLE,
  NEST_CHILDREN_HANDLE,
  OUTPUT_NODE_ID,
  type ConnectionVerdict,
  type InputTypeSet,
  type TypeResolvers,
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
  it("empty graph → null expr (the empty set, ADR-0036)", () => {
    const graph: ViewGraph = { nodes: [out()], edges: [] };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("round-trips each leaf kind", () => {
    const leaves: ViewExpr[] = [
      { type: "lore:character" },
      { descendants_of: "lore:character" },
      { tagged: "gotham" },
      { field: { key: "pov", op: "overlap", value: "honor" } },
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
    // The `type`/`tagged` predicate leaves canonicalize to `All → Filter` on open
    // (ADR-0038 §B), so each contributes an `all` + a `filter` node.
    expect(kinds).toEqual(["all", "all", "filter", "filter", "output", "union"]);
  });

  it("a label-only annotate is an inert pass-through (grouping is retired)", () => {
    // Pre-#91 layouts may carry annotate label nodes; the expr lowers to just
    // its input (no group), and specToGraph skips the annotate on reopen.
    const expr = { annotate: { label: "Cast" }, of: { type: "lore:character" } } as unknown as ViewExpr;
    const kinds = exprToGraph(expr).nodes.map((n) => n.kind).sort();
    // The `type` leaf canonicalizes to `All → Filter` on open (ADR-0038 §B).
    expect(kinds).toEqual(["all", "filter", "output"]);
  });

  it("drops an unconfigured leaf (blank type ≠ whole universe)", () => {
    const leaf = node("type", {}, 0);
    const graph: ViewGraph = { nodes: [out(), leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });
});

describe("injector: All (universal)", () => {
  it("a bare All → the explicit whole-kind roster (descendants_of the kind root, ADR-0036)", () => {
    const all = node("all", {}, 0);
    const graph: ViewGraph = { nodes: [out(), all], edges: [edge(all.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph, "lore")).toEqual({ descendants_of: "lore:base" });
    // Kind-less (the pure round-trip helper) leaves a bare universe as null.
    expect(graphToExpr(graph)).toBeNull();
  });

  // #211: the kind-root `descendants_of` a duplicated default view carries must
  // LIFT back to an `all` node (not a "Type & subtypes" node whose abstract root
  // the picker filters out). Closes the lower/lift asymmetry.
  it("specToGraph lifts a kind-root descendants_of back to an All node", () => {
    // Abstract-rooted kind: `${kind}:base` fallback (no schema needed).
    const g = specToGraph({ kind: "lore", expr: { descendants_of: "lore:base" } });
    expect(g.nodes.filter((n) => n.kind !== "output").map((n) => n.kind)).toEqual(["all"]);
    // Round-trips: All → descendants_of:lore:base → All again.
    expect(graphToSpec(g, { kind: "lore" }).expr).toEqual({ descendants_of: "lore:base" });
  });

  it("specToGraph canonicalizes a NON-root descendants_of to All → Filter (ADR-0038 §B)", () => {
    const g = specToGraph({ kind: "lore", expr: { descendants_of: "lore:deity" } });
    const kinds = g.nodes.filter((n) => n.kind !== "output").map((n) => n.kind).sort();
    expect(kinds).toEqual(["all", "filter"]);
    const filter = g.nodes.find((n) => n.kind === "filter")!;
    expect(filter.data).toMatchObject({ filter_kind: "descendants_of", descendants_of: "lore:deity", filter_mode: "keep" });
    // Lossless: the graph re-serializes to the same bare descendants_of.
    expect(graphToSpec(g, { kind: "lore" }).expr).toEqual({ descendants_of: "lore:deity" });
  });

  it("specToGraph lifts a concrete-root kind's universe to All when the schema resolves it", () => {
    // Assistant's root is the concrete `assistant:assistant` (no abstract base) —
    // only the threaded schema, not the `${kind}:base` fallback, resolves it.
    const schema = {
      entry_types: { "assistant:assistant": { kind: "assistant", name: "Assistant" } },
    } as unknown as Parameters<typeof specToGraph>[1];
    const g = specToGraph({ kind: "assistant", expr: { descendants_of: "assistant:assistant" } }, schema);
    expect(g.nodes.filter((n) => n.kind !== "output").map((n) => n.kind)).toEqual(["all"]);
    // Without the schema the concrete root doesn't resolve to the universe, so it
    // canonicalizes to All → Filter rather than lifting to a bare All (§B).
    const gNoSchema = specToGraph({ kind: "assistant", expr: { descendants_of: "assistant:assistant" } });
    expect(gNoSchema.nodes.filter((n) => n.kind !== "output").map((n) => n.kind).sort()).toEqual(["all", "filter"]);
  });
});

// ADR-0038 §B: the palette retired the standalone `type / descendants_of /
// tagged / field` predicate leaves. `specToGraph` canonicalizes any surviving
// bare leaf (in a saved or duplicated view) into `All → Filter` on open, so the
// designer never presents vocabulary the palette can't rebuild. The rewrite is
// lossless — `intersect(universe, p) === p` — so graphToSpec re-serializes the
// exact same bytes. `hand_picked` / `view_ref` are sources, not predicates, and
// stay as themselves.
describe("canonicalize bare predicate leaves → All → Filter (ADR-0038 §B)", () => {
  const isFilterOverAll = (g: ViewGraph, pred: Partial<ViewGraphNode["data"]>) => {
    const nonOutput = g.nodes.filter((n) => n.kind !== "output");
    expect(nonOutput.map((n) => n.kind).sort()).toEqual(["all", "filter"]);
    const filter = g.nodes.find((n) => n.kind === "filter")!;
    const all = g.nodes.find((n) => n.kind === "all")!;
    expect(filter.data).toMatchObject({ filter_mode: "keep", ...pred });
    // All feeds the Filter's set input (default handle).
    expect(g.edges.some((e) => e.source === all.id && e.target === filter.id)).toBe(true);
  };

  it("type → All → Filter(type), lossless round-trip", () => {
    const g = specToGraph({ kind: "lore", expr: { type: "lore:character" } });
    isFilterOverAll(g, { filter_kind: "type", type: "lore:character" });
    expect(graphToSpec(g, { kind: "lore" }).expr).toEqual({ type: "lore:character" });
  });

  it("tagged → All → Filter(tagged), lossless round-trip", () => {
    const g = specToGraph({ kind: "lore", expr: { tagged: "gotham" } });
    isFilterOverAll(g, { filter_kind: "tagged", tagged: "gotham" });
    expect(graphToSpec(g, { kind: "lore" }).expr).toEqual({ tagged: "gotham" });
  });

  it("field → All → Filter(field), lossless round-trip", () => {
    const expr: ViewExpr = { field: { key: "pov", op: "overlap", value: "honor" } };
    const g = specToGraph({ kind: "lore", expr });
    isFilterOverAll(g, { filter_kind: "field" });
    expect(graphToSpec(g, { kind: "lore" }).expr).toEqual(expr);
  });

  it("hand_picked / view_ref stay sources (not canonicalized)", () => {
    expect(
      specToGraph({ kind: "lore", expr: { hand_picked: ["a", "b"] } })
        .nodes.filter((n) => n.kind !== "output").map((n) => n.kind),
    ).toEqual(["hand_picked"]);
    expect(
      specToGraph({ kind: "lore", expr: { view_ref: "view-123" } })
        .nodes.filter((n) => n.kind !== "output").map((n) => n.kind),
    ).toEqual(["view_ref"]);
  });

  it("a bare-leaf predicate nested in a combinator canonicalizes in place", () => {
    // union[type, tagged] → union[All→Filter, All→Filter], still round-trips.
    const expr: ViewExpr = { union: [{ type: "lore:character" }, { tagged: "villain" }] };
    const g = specToGraph({ kind: "lore", expr });
    const kinds = g.nodes.filter((n) => n.kind !== "output").map((n) => n.kind).sort();
    expect(kinds).toEqual(["all", "all", "filter", "filter", "union"]);
    expect(graphToSpec(g, { kind: "lore" }).expr).toEqual(expr);
  });

  // The paired ADR requirement — "shipped defaults authored in the All → Filter
  // idiom" — is satisfied for free: All → Filter serializes byte-identically to
  // a bare leaf, so there is no distinct idiom to author at the spec level. The
  // canonicalizer alone guarantees a duplicated default opens palette-buildable:
  // no retired predicate-leaf kind ever appears in a reopened default's graph.
  const RETIRED = new Set(["type", "descendants_of", "tagged", "field"]);
  for (const kind of ["scene", "research", "lore", "assistant", "prompt"]) {
    it(`the ${kind} default view opens with no palette-unbuildable node kinds`, () => {
      const g = specToGraph(defaultView(kind));
      expect(g.nodes.filter((n) => RETIRED.has(n.kind)).map((n) => n.kind)).toEqual([]);
    });
  }

  // The flat defaults re-serialize byte-identically (the canonicalization is lossless).
  for (const kind of ["lore", "assistant", "prompt"]) {
    it(`the ${kind} default view re-serializes to the same expr (lossless)`, () => {
      const spec = defaultView(kind);
      expect(graphToSpec(specToGraph(spec), { kind, sort: spec.sort }).expr).toEqual(spec.expr);
    });
  }

  // The scene/research defaults nest the whole-kind roster as `children`, which
  // lifts to an `All` node on open. That now round-trips losslessly too: `nestBuilt`
  // serializes `parents`/`children` via `materializeOuter`, so an All-roster child
  // re-emits the explicit `{descendants_of:<kind-root>}` instead of dropping the key
  // (which previously collapsed the recursive containment tree to the empty set).
  // See the "nest lowering" block for the unit-level guards on that seam.
  for (const kind of ["scene", "research"]) {
    it(`the ${kind} default view re-serializes to the same expr (lossless, nest All-child)`, () => {
      const spec = defaultView(kind);
      expect(graphToSpec(specToGraph(spec), { kind, sort: spec.sort }).expr).toEqual(spec.expr);
    });
  }
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

  it("a whole-universe handle (bare All) → group with the explicit roster expr (ADR-0036)", () => {
    const output = out({ handles: [{ id: "h0", name: "Everything" }, { id: "h1", name: "Gods" }] });
    const all = node("all", {}, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, all, gods],
      edges: [edge(all.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Everything", expr: { descendants_of: "lore:base" } },
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

// ADR-0037 §2/§8: organize levels are result-node config that rides on the spec
// beside the handle-derived expr/groups — orthogonal to the expr-XOR-groups rule.
describe("group_by (organize levels, ADR-0037 §2/§8)", () => {
  it("no organize levels → spec carries no group_by key", () => {
    const leaf = node("type", { type: "lore:character" }, 0);
    const graph: ViewGraph = { nodes: [out(), leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" })).not.toHaveProperty("group_by");
  });

  it("the single/unnamed group's levels (on its `in` handle) lower onto a flat expr spec", () => {
    const output = out({ handles: [{ id: "in", name: "", group_by: [{ field: "entry_type", order: "label" }, { field: "rank" }] }] });
    const leaf = node("descendants_of", { descendants_of: "lore:base" }, 0);
    const graph: ViewGraph = { nodes: [output, leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.expr).toEqual({ descendants_of: "lore:base" });
    expect(spec.group_by).toEqual([{ field: "entry_type", order: "label" }, { field: "rank" }]);
  });

  it("Amendment 1: each handle's group_by lowers onto its OWN group; no top-level group_by", () => {
    const output = out({
      handles: [
        { id: "h0", name: "Cast", group_by: [{ field: "rank" }] },
        { id: "h1", name: "Gods", group_by: [{ field: "entry_type" }] },
      ],
    });
    const cast = node("type", { type: "lore:character" }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, gods],
      edges: [edge(cast.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toHaveLength(2);
    expect(spec.groups?.[0].group_by).toEqual([{ field: "rank" }]);
    expect(spec.groups?.[1].group_by).toEqual([{ field: "entry_type" }]);
    expect(spec).not.toHaveProperty("group_by"); // Organize is per-group, not result-level
  });

  it("drops blank-field levels (a half-authored dropdown never persists)", () => {
    const output = out({ handles: [{ id: "in", name: "", group_by: [{ field: "" }, { field: "rank" }] }] });
    const leaf = node("type", { type: "lore:character" }, 0);
    const graph: ViewGraph = { nodes: [output, leaf], edges: [edge(leaf.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).group_by).toEqual([{ field: "rank" }]);
  });

  it("specToGraph seeds the `in` handle (flat) and each handle (grouped) with its group_by (Amendment 1)", () => {
    const flat = specToGraph({ kind: "lore", expr: { descendants_of: "lore:base" }, group_by: [{ field: "entry_type" }] });
    const flatHandles = flat.nodes.find((n) => n.id === OUTPUT_NODE_ID)?.data.handles;
    expect(flatHandles?.[0].id).toBe("in");
    expect(flatHandles?.[0].group_by).toEqual([{ field: "entry_type" }]);
    const grouped = specToGraph({
      kind: "lore",
      groups: [
        { name: "Cast", expr: { type: "lore:character" }, group_by: [{ field: "rank" }] },
        { name: "Gods", expr: { type: "lore:deity" } },
      ],
    });
    const handles = grouped.nodes.find((n) => n.id === OUTPUT_NODE_ID)?.data.handles;
    expect(handles?.[0].group_by).toEqual([{ field: "rank" }]);
    expect(handles?.[1].group_by).toBeUndefined();
  });

  it("round-trips the unnamed group's group_by through specToGraph → graphToSpec", () => {
    const spec = { kind: "lore", expr: { descendants_of: "lore:base" }, group_by: [{ field: "entry_type", order: "label" as const }, { field: "rank" }] };
    const back = graphToSpec(specToGraph(spec), { kind: "lore" });
    expect(back.group_by).toEqual(spec.group_by);
  });

  it("round-trips per-group group_by (Amendment 1) through specToGraph → graphToSpec", () => {
    const spec = {
      kind: "lore",
      groups: [
        { name: "Cast", expr: { type: "lore:character" }, group_by: [{ field: "rank" }] },
        { name: "Gods", expr: { type: "lore:deity" } },
      ],
    };
    const back = graphToSpec(specToGraph(spec), { kind: "lore" });
    expect(back.groups).toHaveLength(2);
    expect(back.groups?.[0].group_by).toEqual([{ field: "rank" }]);
    expect(back.groups?.[1].group_by).toBeUndefined();
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

  it("does NOT promote a null-expr view to the universe when it carries a sort (#B1)", () => {
    // A saved empty-but-ordered view (expr null + non-manual sort). Reopening must
    // not wire an input-less Sorter that the #93 empty+sort rule promotes to the
    // whole roster — that would silently flip membership ∅ → everything.
    const back = graphToSpec(specToGraph({ kind: "lore", expr: null, sort: { by: "title", dir: "asc" } }), { kind: "lore" });
    expect(back.expr ?? null).toBeNull(); // still the empty set, not descendants_of
  });

  it("carries a multi-level sort chain (#230) through the Sorter node verbatim", () => {
    const chain = { by: "field" as const, field_key: "rank", dir: "desc" as const, then: { by: "title" as const, dir: "asc" as const } };
    const src = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: chain }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, s],
      edges: [edge(src.id, s.id), edge(s.id, OUTPUT_NODE_ID)],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.sort).toEqual(chain);
    // and specToGraph rebuilds the Sorter with the chain intact.
    const back = graphToSpec(specToGraph(spec), { kind: "lore" });
    expect(back.sort).toEqual(chain);
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

describe("graphToSpec — half-authored 'field' sort keys are stripped from the spec (#254)", () => {
  // A Sorter with `by:"field"` and no field_key is a legitimate transient
  // authoring state (row added, "Field…" chosen, field not yet picked). It is
  // inert in the evaluator but the backend ViewSort model rejects it, silently
  // 422-ing every autosave. graphToSpec must keep it out of the emitted spec.
  it("drops a sole keyless field sort → flat sort is null (manual/stored order)", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: { by: "field", dir: "asc" } }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, s],
      edges: [edge(src.id, s.id), edge(s.id, OUTPUT_NODE_ID)],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.sort).toBeNull();
  });

  it("splices a keyless field key out of the middle of a chain, keeping valid keys", () => {
    const chain = {
      by: "field" as const,
      dir: "asc" as const, // no field_key → inert, must be dropped
      then: { by: "title" as const, dir: "desc" as const },
    };
    const src = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: chain }, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, s],
      edges: [edge(src.id, s.id), edge(s.id, OUTPUT_NODE_ID)],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.sort).toEqual({ by: "title", dir: "desc" });
  });

  it("omits a group's sort when it is only a keyless field key", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const s = node("sorter", { sort: { by: "field", dir: "asc" } }, 50);
    const graph: ViewGraph = {
      nodes: [output, cast, s],
      edges: [edge(cast.id, s.id), edge(s.id, OUTPUT_NODE_ID, "h0")],
    };
    // Single populated handle lowers to the flat form; the inert sort is stripped.
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.sort).toBeNull();
  });
});

describe("graphToSpec — orphaned & sorted-empty handles (#93)", () => {
  it("an edge whose targetHandle names no real handle is adopted by the first handle", () => {
    const output = out({ handles: [{ id: "h0", name: "Cast" }, { id: "h1", name: "Gods" }] });
    const cast = node("type", { type: "lore:character" }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, cast, gods],
      // `cast` wired with the default "in" handle — not h0/h1. Pre-fix its whole
      // subgraph vanished; now it is adopted by the first handle (h0).
      edges: [edge(cast.id, OUTPUT_NODE_ID), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "Cast", expr: { type: "lore:character" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });

  it("a Sorter feeding a handle with no upstream membership → sorted whole-universe group", () => {
    const output = out({ handles: [{ id: "h0", name: "All sorted" }, { id: "h1", name: "Gods" }] });
    const s = node("sorter", { sort: { by: "title", dir: "asc" } }, 0);
    const gods = node("descendants_of", { descendants_of: "lore:deity" }, 100);
    const graph: ViewGraph = {
      nodes: [output, s, gods],
      // The sorter has NO upstream membership; pre-fix the group and its sort were
      // dropped as "empty". Now it persists as a sorted whole-roster group — the
      // universe coercion (empty+sort → UNIVERSE) lowers to the explicit roster
      // expr, not null (ADR-0036).
      edges: [edge(s.id, OUTPUT_NODE_ID, "h0"), edge(gods.id, OUTPUT_NODE_ID, "h1")],
    };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.groups).toEqual([
      { name: "All sorted", expr: { descendants_of: "lore:base" }, sort: { by: "title", dir: "asc" } },
      { name: "Gods", expr: { descendants_of: "lore:deity" } },
    ]);
  });
});

describe("nest lowering + self-loop recursion (ADR-0028)", () => {
  const match = { field: "parent", direction: "child_to_parent" as const, by: "ref" as const };

  it("round-trips a nest (parents + children + match)", () => {
    const expr: ViewExpr = {
      nest: { parents: { field: { key: "parent", op: "unset" } }, children: { type: "lore:location" }, match },
    };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips a recursive nest — the self-loop lowers to recursive:true", () => {
    const expr: ViewExpr = {
      nest: { parents: { field: { key: "parent", op: "unset" } }, match, recursive: true },
    };
    expect(roundTrip(expr)).toEqual(expr);
    // The recursion is carried as a real self-loop edge on the canvas.
    const graph = exprToGraph(expr);
    const nst = graph.nodes.find((n) => n.kind === "nest")!;
    expect(graph.edges.some((e) => e.source === nst.id && e.target === nst.id && e.targetHandle === "parents")).toBe(true);
  });

  it("an unconfigured nest (no match) lowers to nothing", () => {
    const nst = node("nest", {}, 0);
    const graph: ViewGraph = { nodes: [out(), nst], edges: [edge(nst.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("defaults match.by to ref when omitted", () => {
    const nst = node("nest", { match: { field: "p", direction: "child_to_parent" } as never }, 0);
    const graph: ViewGraph = { nodes: [out(), nst], edges: [edge(nst.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toEqual({ nest: { match: { field: "p", direction: "child_to_parent", by: "ref" } } });
  });

  it("a nest whose `children` is fed by an `All` injector re-serializes the whole-kind roster (outer materialize)", () => {
    // The all-roster children lowers through the OUTER materialize: `All` → the
    // explicit `{descendants_of:<kind-root>}`, NOT a dropped key. Without a kind
    // (the pure round-trip helper) there's no universe expr, so it degrades to a
    // missing `children` — the evaluator's unseeded-feed convention. This is the
    // seam that makes the scene/research default view round-trip (see the §B block).
    const all = node("all", {}, 0);
    const nst = node("nest", { match }, 100);
    const graph: ViewGraph = {
      nodes: [out(), all, nst],
      edges: [edge(all.id, nst.id, "children"), edge(nst.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph, "scene")).toEqual({ nest: { children: { descendants_of: "scene:base" }, match } });
    expect(graphToExpr(graph)).toEqual({ nest: { match } });
  });

  it("an unwired `children` handle omits the key (unconfigured feed stays a dropped key)", () => {
    // EMPTY (unconfigured), unlike UNIVERSE (an All roster), must still omit the
    // key so the evaluator applies its whole-universe-on-missing-seed convention.
    const nst = node("nest", { match }, 0);
    const graph: ViewGraph = { nodes: [out(), nst], edges: [edge(nst.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph, "scene")).toEqual({ nest: { match } });
  });
});

describe("#184 field_of / self lowering + round-trip (ADR-0031 §D)", () => {
  it("round-trips field_of over a leaf `of`", () => {
    const expr: ViewExpr = { field_of: { of: { type: "scene:scene" }, field: "pov" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips the $self-backlinks shape field_of($self, references)", () => {
    const expr: ViewExpr = { field_of: { of: { var: "$self" }, field: "references" } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("a standalone $self source lowers to {var: $self}", () => {
    const self = node("self", {}, 0);
    const graph: ViewGraph = { nodes: [out(), self], edges: [edge(self.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toEqual({ var: "$self" });
  });

  it("field_of with no projected field lowers to nothing", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", {}, 100);
    const graph: ViewGraph = {
      nodes: [out(), src, fo],
      edges: [edge(src.id, fo.id), edge(fo.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("field_of with no wired `of` lowers to nothing (grammar has no universal-set leaf)", () => {
    const fo = node("field_of", { project_field: "references" }, 0);
    const graph: ViewGraph = { nodes: [out(), fo], edges: [edge(fo.id, OUTPUT_NODE_ID)] };
    expect(graphToExpr(graph)).toBeNull();
  });

  it("field_of wired from an `All` injector projects over the whole-kind roster (was #203's blocked silent-empty)", () => {
    // Post ADR-0036 `All` lowers to the explicit whole-kind expr, so `field_of(All,
    // pov)` is a concrete projection over every node — e.g. `field_of(All, entry_type)`
    // enumerates the types in use. The #203 wire block is retired accordingly.
    const all = node("all", {}, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const graph: ViewGraph = {
      nodes: [out(), all, fo],
      edges: [edge(all.id, fo.id), edge(fo.id, OUTPUT_NODE_ID)],
    };
    expect(graphToExpr(graph, "lore")).toEqual({ field_of: { of: { descendants_of: "lore:base" }, field: "pov" } });
    // Without a kind (the pure round-trip helper) there's no universe expr to
    // resolve, so a universe `of` still degrades to null.
    expect(graphToExpr(graph)).toBeNull();
  });

  it("specToGraph rebuilds a field_of node wired from its `of` subgraph", () => {
    const graph = specToGraph({ kind: "lore", expr: { field_of: { of: { var: "$self" }, field: "references" } } });
    const fo = graph.nodes.find((n) => n.kind === "field_of")!;
    const self = graph.nodes.find((n) => n.kind === "self")!;
    expect(fo.data.project_field).toBe("references");
    expect(graph.edges.some((e) => e.source === self.id && e.target === fo.id)).toBe(true);
  });

  it("reachesFieldOf enforces the single-hop cut", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const byId = new Map([[src.id, src], [fo.id, fo]]);
    // A field_of output (or anything downstream of it) reaches a field_of.
    expect(reachesFieldOf(byId, [edge(src.id, fo.id)], fo.id)).toBe(true);
    // A plain source does not.
    expect(reachesFieldOf(byId, [edge(src.id, fo.id)], src.id)).toBe(false);
  });
});

describe("#196 value-set pipe (scalar field_of → Filter value slot, ADR-0031 §E)", () => {
  const fieldType = (k: string): string | null =>
    ({ pov: "entity_ref", characters: "entity_ref_list", status: "select" })[k] ?? null;

  it("outputPayload: scalar field_of → value-set; ref/references/other → node-set", () => {
    expect(outputPayload(node("field_of", { project_field: "status" }), fieldType)).toBe("value-set");
    expect(outputPayload(node("field_of", { project_field: "pov" }), fieldType)).toBe("node-set");
    expect(outputPayload(node("field_of", { project_field: "references" }), fieldType)).toBe("node-set");
    expect(outputPayload(node("self", {}), fieldType)).toBe("node-set");
    expect(outputPayload(node("type", { type: "x" }), fieldType)).toBe("node-set");
  });

  it("valueSlotAccepts enforces the two-payload matrix", () => {
    const scalarFO = node("field_of", { project_field: "status" });
    const refFO = node("field_of", { project_field: "pov" });
    const self = node("self", {});
    const typeSrc = node("type", { type: "scene:scene" });
    // scalar field slot ← value-set only
    expect(valueSlotAccepts(scalarFO, { key: "status", op: "overlap" }, fieldType)).toBe(true);
    expect(valueSlotAccepts(refFO, { key: "status", op: "overlap" }, fieldType)).toBe(false);
    // entity_ref field slot ← node-set only (a ref projection or a bare $self)
    expect(valueSlotAccepts(refFO, { key: "pov", op: "overlap" }, fieldType)).toBe(true);
    expect(valueSlotAccepts(self, { key: "pov", op: "overlap" }, fieldType)).toBe(true);
    expect(valueSlotAccepts(scalarFO, { key: "pov", op: "overlap" }, fieldType)).toBe(false);
    // only field_of / self are operand-representable wired sources
    expect(valueSlotAccepts(typeSrc, { key: "pov", op: "overlap" }, fieldType)).toBe(false);
    // no field key → nothing to accept
    expect(valueSlotAccepts(scalarFO, undefined, fieldType)).toBe(false);
  });

  it("lowers a field leaf with a wired scalar field_of into a {field_of} value operand", () => {
    const scenes = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "status" }, 100);
    const field = node("field", { field: { key: "status", op: "overlap" } }, 200);
    const graph: ViewGraph = {
      nodes: [out(), scenes, fo, field],
      edges: [
        edge(scenes.id, fo.id),
        edge(fo.id, field.id, FILTER_VALUE_HANDLE),
        edge(field.id, OUTPUT_NODE_ID),
      ],
    };
    expect(graphToExpr(graph)).toEqual({
      field: { key: "status", op: "overlap", value: { field_of: { of: { type: "scene:scene" }, field: "status" } } },
    });
  });

  it("round-trips a Filter value wired from a field_of", () => {
    const expr: ViewExpr = {
      field: { key: "status", op: "overlap", value: { field_of: { of: { type: "scene:scene" }, field: "status" } } },
    };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("round-trips a Filter value wired from $self", () => {
    const expr: ViewExpr = { field: { key: "pov", op: "overlap", value: { var: "$self" } } };
    expect(roundTrip(expr)).toEqual(expr);
  });

  it("specToGraph rebuilds the value wire (field_of node + edge into the Filter's value handle)", () => {
    const graph = specToGraph({
      kind: "scene",
      expr: { field: { key: "status", op: "overlap", value: { field_of: { of: { type: "scene:scene" }, field: "status" } } } },
    });
    // The field predicate canonicalizes to a Filter (filter_kind: field) fed by All
    // (§B). The `of`'s `type` predicate ALSO canonicalizes, so pick by filter_kind.
    const filter = graph.nodes.find((n) => n.kind === "filter" && n.data.filter_kind === "field")!;
    const fo = graph.nodes.find((n) => n.kind === "field_of")!;
    expect(filter.data.filter_kind).toBe("field");
    expect(fo.data.project_field).toBe("status");
    expect(
      graph.edges.some((e) => e.source === fo.id && e.target === filter.id && e.targetHandle === FILTER_VALUE_HANDLE),
    ).toBe(true);
    // the Filter's inline value is cleared — the wire re-supplies it on lowering.
    expect(filter.data.field?.value ?? null).toBeNull();
  });
});

describe("cycle classifier — recursion vs meaningless (ADR-0028 §D)", () => {
  const match = { field: "parent", direction: "child_to_parent" as const, by: "ref" as const };

  it("a direct self-loop into a nest's parents handle = allowed recursion", () => {
    const nst = node("nest", { match }, 0);
    const byId = new Map([[nst.id, nst]]);
    expect(classifyConnection(byId, [], nst.id, nst.id, "parents")).toBe("nest-recursion");
  });

  it("a self-loop into a nest's children handle is NOT recursion", () => {
    const nst = node("nest", { match }, 0);
    const byId = new Map([[nst.id, nst]]);
    expect(classifyConnection(byId, [], nst.id, nst.id, "children")).toBe("meaningless-cycle");
  });

  it("a cycle with no nest on it is meaningless", () => {
    const a = node("intersect", {}, 0);
    const b = node("union", {}, 100);
    const byId = new Map([[a.id, a], [b.id, b]]);
    // a→b already wired; closing b→a forms a nest-free cycle.
    expect(classifyConnection(byId, [edge(a.id, b.id)], b.id, a.id, "in")).toBe("meaningless-cycle");
  });

  it("a multi-node cycle feeding a nest's parents is detected but unsupported (v2)", () => {
    const nst = node("nest", { match }, 0);
    const f = node("filter", {}, 100);
    const byId = new Map([[nst.id, nst], [f.id, f]]);
    // nest→filter already wired; closing filter→nest.parents is a frontier loop.
    expect(classifyConnection(byId, [edge(nst.id, f.id)], f.id, nst.id, "parents")).toBe("nest-recursion-unsupported");
  });

  it("a plain acyclic edge is ok", () => {
    const src = node("type", { type: "lore:character" }, 0);
    const nst = node("nest", { match }, 100);
    const byId = new Map([[src.id, src], [nst.id, nst]]);
    expect(classifyConnection(byId, [], src.id, nst.id, "children")).toBe("ok");
  });

  it("connectionAllowed permits only clean edges + supported recursion", () => {
    const verdicts: [ConnectionVerdict, boolean][] = [
      ["ok", true],
      ["nest-recursion", true],
      ["nest-recursion-unsupported", false],
      ["meaningless-cycle", false],
    ];
    for (const [v, allowed] of verdicts) expect(connectionAllowed(v)).toBe(allowed);
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

// Promote-in-place (#184 Phase 1b, ADR-0032): a Filter/field value slot ⇄ a
// named ViewSpec.params formal. graphToSpec collects reachable promoted formals;
// specToGraph restores param from the params list on `{var}` values.
describe("promote-in-place params (#184)", () => {
  it("collects a promoted field's formal into spec.params (value → {var})", () => {
    const f = node("field", {
      field: { key: "tags", op: "overlap", value: { var: "P_TAG" } },
      param: { name: "P_TAG", label: "Tag", default: ["hero"] },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.params).toEqual([{ name: "P_TAG", label: "Tag", default: ["hero"] }]);
    expect(spec.expr).toEqual({ field: { key: "tags", op: "overlap", value: { var: "P_TAG" } } });
  });

  it("omits an unbound formal's default but keeps the param", () => {
    const f = node("field", {
      field: { key: "tags", op: "overlap", value: { var: "P" } },
      param: { name: "P", label: "Tag" },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).params).toEqual([{ name: "P", label: "Tag" }]);
  });

  it("skips a promoted formal on a node not wired to the output (no phantom param)", () => {
    const wired = node("type", { type: "lore:character" });
    const orphan = node("field", {
      field: { key: "tags", op: "overlap", value: { var: "GHOST" } },
      param: { name: "GHOST", default: ["x"] },
    });
    const graph: ViewGraph = { nodes: [out(), wired, orphan], edges: [edge(wired.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).params).toBeUndefined();
  });

  it("skips a stale param whose value is no longer its {var}", () => {
    const f = node("field", {
      field: { key: "tags", op: "overlap", value: "literal" },
      param: { name: "P", default: [] },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).params).toBeUndefined();
  });

  it("specToGraph restores param from a {var} value + matching param", () => {
    const spec = {
      kind: "lore",
      expr: { field: { key: "tags", op: "overlap" as const, value: { var: "P" } } },
      params: [{ name: "P", label: "Tag", default: ["hero"] }],
    };
    // The field predicate canonicalizes to a Filter; the promoted formal rides on it (§B).
    const filter = specToGraph(spec).nodes.find((n) => n.kind === "filter");
    expect(filter?.data.param).toEqual({ name: "P", label: "Tag", default: ["hero"] });
    expect(filter?.data.field?.value).toEqual({ var: "P" });
  });

  it("round-trips a promoted formal graph → spec → graph → spec", () => {
    const f = node("field", {
      field: { key: "pov", op: "overlap", value: { var: "POV" } },
      param: { name: "POV", label: "Point of view", default: ["alice"] },
    });
    const graph: ViewGraph = { nodes: [out(), f], edges: [edge(f.id, OUTPUT_NODE_ID)] };
    const spec1 = graphToSpec(graph, { kind: "lore" });
    const spec2 = graphToSpec(specToGraph(spec1), { kind: "lore" });
    expect(spec2.params).toEqual(spec1.params);
    expect(spec2.expr).toEqual(spec1.expr);
  });
});

// ADR-0038 §C Amendment 1 (#222): promotion generalizes from the field value slot
// to the value-carrying LEAF slots — type / descendants_of / tagged. Their slot
// value becomes `{var}`, `collectParams` picks them up generically, and the
// canonicalize-on-open path (§B) reconstructs the param onto the Filter.
describe("promote-in-place params — leaf slots (ADR-0038 §C, #222)", () => {
  it("collects a promoted type leaf's formal (type → {var})", () => {
    const t = node("type", { type: { var: "T" }, param: { name: "T", label: "Type", default: "lore:character" } });
    const graph: ViewGraph = { nodes: [out(), t], edges: [edge(t.id, OUTPUT_NODE_ID)] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.params).toEqual([{ name: "T", label: "Type", default: "lore:character" }]);
    expect(spec.expr).toEqual({ type: { var: "T" } });
  });

  it("collects a promoted tagged leaf's formal, omitting an absent default", () => {
    const t = node("tagged", { tagged: { var: "TAG" }, param: { name: "TAG", label: "Tag" } });
    const graph: ViewGraph = { nodes: [out(), t], edges: [edge(t.id, OUTPUT_NODE_ID)] };
    const spec = graphToSpec(graph, { kind: "lore" });
    expect(spec.params).toEqual([{ name: "TAG", label: "Tag" }]);
    expect(spec.expr).toEqual({ tagged: { var: "TAG" } });
  });

  it("skips a stale leaf param whose slot value is no longer its {var}", () => {
    const t = node("type", { type: "lore:character", param: { name: "T", default: "lore:deity" } });
    const graph: ViewGraph = { nodes: [out(), t], edges: [edge(t.id, OUTPUT_NODE_ID)] };
    expect(graphToSpec(graph, { kind: "lore" }).params).toBeUndefined();
  });

  it("specToGraph restores a promoted type leaf's param (canonicalized to a Filter, §B)", () => {
    const spec = {
      kind: "lore",
      expr: { type: { var: "T" } },
      params: [{ name: "T", label: "Type", default: "lore:character" }],
    };
    const filter = specToGraph(spec).nodes.find((n) => n.kind === "filter");
    expect(filter?.data.filter_kind).toBe("type");
    expect(filter?.data.type).toEqual({ var: "T" });
    expect(filter?.data.param).toEqual({ name: "T", label: "Type", default: "lore:character" });
  });

  it("round-trips a promoted tagged leaf graph → spec → graph → spec", () => {
    const t = node("tagged", { tagged: { var: "TAG" }, param: { name: "TAG", label: "Tag", default: "hero" } });
    const graph: ViewGraph = { nodes: [out(), t], edges: [edge(t.id, OUTPUT_NODE_ID)] };
    const spec1 = graphToSpec(graph, { kind: "lore" });
    const spec2 = graphToSpec(specToGraph(spec1), { kind: "lore" });
    expect(spec2.params).toEqual(spec1.params);
    expect(spec2.expr).toEqual(spec1.expr);
  });

  // The §D Parameters rail lists these — each row needs the owning node id + slot
  // to navigate to and expand it.
  it("collectParamBindings pairs each formal with its owning node and slot", () => {
    const t = node("type", { type: { var: "T" }, param: { name: "T", label: "Type" } });
    const f = node("field", {
      field: { key: "tags", op: "overlap", value: { var: "TAG" } },
      param: { name: "TAG", label: "Tag", default: ["hero"] },
    });
    const graph: ViewGraph = {
      nodes: [out(), t, f],
      edges: [edge(t.id, OUTPUT_NODE_ID), edge(f.id, OUTPUT_NODE_ID)],
    };
    const bindings = collectParamBindings(graph);
    expect(bindings.map((b) => [b.nodeId, b.slot, b.param.name])).toEqual([
      [t.id, "type", "T"],
      [f.id, "field", "TAG"],
    ]);
  });
});

describe("field-picker type inference (ADR-0031 §F)", () => {
  // pov = entity_ref → lore; characters = entity_ref_list → lore; owner = a
  // multi-kind ref (lore + scene); status = scalar.
  const fieldType = (k: string): string | null =>
    ({ pov: "entity_ref", characters: "entity_ref_list", owner: "entity_ref", status: "select" })[k] ?? null;
  const resolvers: TypeResolvers = {
    fieldType,
    refTargetTypes: (k) =>
      k === "pov" || k === "characters"
        ? new Map([["lore", null]])
        : k === "owner"
          ? new Map([
              ["lore", null],
              ["scene", null],
            ])
          : null,
    descendantsOf: (fqn) => (fqn === "lore:character" ? ["lore:character", "lore:protagonist"] : [fqn]),
    kindOfType: (fqn) => fqn.split(":")[0] ?? null,
  };
  const byIdOf = (nodes: ViewGraphNode[]) => new Map(nodes.map((n) => [n.id, n]));
  // Normalize a type-set to a comparable plain object (sorted fqns, or null).
  const dump = (ts: InputTypeSet | null) =>
    ts === null ? null : Object.fromEntries([...ts].map(([k, s]) => [k, s === null ? null : [...s].sort()]));
  const infer = (nodes: ViewGraphNode[], edges: ReturnType<typeof edge>[], id: string, anchor = "scene") =>
    dump(inferInputTypes(byIdOf(nodes), edges, id, anchor, resolvers));

  it("a Filter over a `type` leaf infers that exact entry_type", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const filter = node("filter", { filter_kind: "field" }, 100);
    const nodes = [out(), src, filter];
    const edges = [edge(src.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, filter.id)).toEqual({ scene: ["scene:scene"] });
  });

  it("a `descendants_of` leaf infers the whole subtype family (seed-inclusive)", () => {
    const src = node("descendants_of", { descendants_of: "lore:character" }, 0);
    const filter = node("filter", { filter_kind: "field" }, 100);
    const nodes = [out(), src, filter];
    const edges = [edge(src.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, filter.id, "lore")).toEqual({ lore: ["lore:character", "lore:protagonist"] });
  });

  it("a node downstream of a ref `field_of` infers the ref field's target kind (the §F remap)", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const filter = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), src, fo, filter];
    const edges = [edge(src.id, fo.id), edge(fo.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, filter.id)).toEqual({ lore: null });
  });

  it("a multi-kind ref `field_of` yields a cross-kind set (§14.3), not a null fallback", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "owner" }, 100);
    const filter = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), src, fo, filter];
    const edges = [edge(src.id, fo.id), edge(fo.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, filter.id)).toEqual({ lore: null, scene: null });
  });

  it("a `field_of`'s own project-field picker sees its INPUT type, not its output", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const nodes = [out(), src, fo];
    const edges = [edge(src.id, fo.id), edge(fo.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, fo.id)).toEqual({ scene: ["scene:scene"] });
  });

  it("downstream of a SCALAR `field_of` (value-set) → indeterminate (null → anchor fallback)", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "status" }, 100);
    const filter = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), src, fo, filter];
    const edges = [edge(src.id, fo.id), edge(fo.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, filter.id)).toBeNull();
  });

  it("downstream of a `references` (any-kind) `field_of` → indeterminate", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "references" }, 100);
    const filter = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), src, fo, filter];
    const edges = [edge(src.id, fo.id), edge(fo.id, filter.id), edge(filter.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, filter.id)).toBeNull();
  });

  it("a Filter/Sorter preserves its input type through the remap", () => {
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "characters" }, 100);
    const f1 = node("filter", { filter_kind: "tagged" }, 200);
    const f2 = node("sorter", { sort: { by: "field" } }, 300);
    const nodes = [out(), src, fo, f1, f2];
    const edges = [edge(src.id, fo.id), edge(fo.id, f1.id), edge(f1.id, f2.id), edge(f2.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, f2.id)).toEqual({ lore: null });
  });

  it("a keep-Filter on a `type` predicate narrows the downstream type-set", () => {
    // All(lore) → Filter(keep type=character) → sink: the sink sees character only.
    const all = node("all", {}, 0);
    const tf = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:character" }, 100);
    const sink = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), all, tf, sink];
    const edges = [edge(all.id, tf.id), edge(tf.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, sink.id, "lore")).toEqual({ lore: ["lore:character"] });
  });

  it("a drop-Filter and a promoted-`{var}` type Filter impose no type narrowing (passthrough)", () => {
    const all = node("all", {}, 0);
    const drop = node("filter", { filter_kind: "type", filter_mode: "drop", type: "lore:character" }, 100);
    const sink = node("filter", { filter_kind: "field" }, 200);
    const nodes = [out(), all, drop, sink];
    const edges = [edge(all.id, drop.id), edge(drop.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, sink.id, "lore")).toEqual({ lore: null });
  });

  it("complement widens to the whole kind (universe ∖ A ≠ A's types)", () => {
    // All(lore) → keep-Filter type=character → complement → sink. The complement
    // holds all lore EXCEPT characters, so the sink must see the whole lore kind,
    // not `{lore:character}`.
    const all = node("all", {}, 0);
    const tf = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:character" }, 100);
    const comp = node("complement", {}, 200);
    const sink = node("filter", { filter_kind: "field" }, 300);
    const nodes = [out(), all, tf, comp, sink];
    const edges = [edge(all.id, tf.id), edge(tf.id, comp.id), edge(comp.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, sink.id, "lore")).toEqual({ lore: null });
  });

  it("a nest handle unions ALL its inbound sources, not just the first", () => {
    // Two type leaves wired into a nest's children handle → the join-field picker
    // must see BOTH types (lowering unions them), not only the first edge's type.
    const l1 = node("type", { type: "scene:action" }, 0);
    const l2 = node("type", { type: "scene:sequel" }, 100);
    const nest = node("nest", { match: { field: "parent", direction: "child_to_parent", by: "ref" } }, 200);
    const nodes = [out(), l1, l2, nest];
    const edges = [
      edge(l1.id, nest.id, NEST_CHILDREN_HANDLE),
      edge(l2.id, nest.id, NEST_CHILDREN_HANDLE),
      edge(nest.id, OUTPUT_NODE_ID),
    ];
    expect(infer(nodes, edges, nest.id)).toEqual({ scene: ["scene:action", "scene:sequel"] });
  });

  it("a provably-empty intersect (disjoint types) yields an empty type-set, not the anchor kind", () => {
    // All(lore)→keep character  ∩  All(lore)→keep location  = ∅ (empty Map, NOT null).
    const a = node("all", {}, 0);
    const fa = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:character" }, 100);
    const b = node("all", {}, 200);
    const fb = node("filter", { filter_kind: "type", filter_mode: "keep", type: "lore:location" }, 300);
    const x = node("intersect", {}, 400);
    const sink = node("filter", { filter_kind: "field" }, 500);
    const nodes = [out(), a, fa, b, fb, x, sink];
    const edges = [
      edge(a.id, fa.id),
      edge(fa.id, x.id),
      edge(b.id, fb.id),
      edge(fb.id, x.id),
      edge(x.id, sink.id),
      edge(sink.id, OUTPUT_NODE_ID),
    ];
    // The kind is kept but with an empty concrete-type set — `concreteTypesOf`
    // then yields no fqns, so the roster becomes intrinsics-only (not the anchor
    // union). Distinct from `null` (indeterminate → anchor fallback).
    expect(infer(nodes, edges, sink.id, "lore")).toEqual({ lore: [] });
  });

  it("an unwired node falls back to the whole anchor kind", () => {
    const filter = node("filter", { filter_kind: "field" }, 0);
    expect(infer([out(), filter], [], filter.id)).toEqual({ scene: null });
  });

  it("a union of two kinds yields a cross-kind set", () => {
    const a = node("type", { type: "scene:scene" }, 0);
    const b = node("descendants_of", { descendants_of: "lore:character" }, 100);
    const u = node("union", {}, 200);
    const sink = node("filter", { filter_kind: "field" }, 300);
    const nodes = [out(), a, b, u, sink];
    const edges = [edge(a.id, u.id), edge(b.id, u.id), edge(u.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
    expect(infer(nodes, edges, sink.id)).toEqual({
      scene: ["scene:scene"],
      lore: ["lore:character", "lore:protagonist"],
    });
  });

  it("a base-type-scoped tag reaches a concrete-subtype input; a leaf tag does not cross types", () => {
    const descendantsOf = (fqn: string): string[] =>
      fqn === "lore:base"
        ? ["lore:base", "lore:character", "lore:location"]
        : fqn === "lore:character"
          ? ["lore:character", "lore:protagonist"]
          : [fqn];
    const scope = (sources: NodePickerConfig["sources"]): NodePickerConfig => ({ sources });
    const typeScope = (k: string, fqn?: string): NodePickerConfig =>
      scope([fqn ? { kind: k, expr: { type: fqn } } : { kind: k }]);
    const applies = (sc: NodePickerConfig, ts: InputTypeSet) => tagAppliesToInput(sc, ts, descendantsOf);
    const charInput: InputTypeSet = new Map([["lore", new Set(["lore:character"])]]);
    const locInput: InputTypeSet = new Map([["lore", new Set(["lore:location"])]]);

    expect(applies(scope([]), charInput)).toBe(true); // unscoped → anywhere
    expect(applies(typeScope("lore", "lore:base"), charInput)).toBe(true); // base → subtype (the pattern)
    expect(applies(typeScope("lore", "lore:character"), charInput)).toBe(true); // own type
    expect(applies(typeScope("lore", "lore:character"), locInput)).toBe(false); // disjoint leaf types
    expect(applies(typeScope("lore"), locInput)).toBe(true); // kind-scoped → any type
    expect(applies(typeScope("lore", "lore:character"), new Map([["lore", null]]))).toBe(true); // whole-kind input
    expect(applies(typeScope("scene", "scene:scene"), new Map([["lore", null]]))).toBe(false); // other kind
  });

  it("a diamond over a ref `field_of` still remaps (independent `seen` per branch)", () => {
    // scene → field_of(pov→lore) fans into filterA + filterB → union → sink.
    // A shared `seen` set would null the second branch → wrong anchor fallback.
    const src = node("type", { type: "scene:scene" }, 0);
    const fo = node("field_of", { project_field: "pov" }, 100);
    const fa = node("filter", { filter_kind: "tagged" }, 200);
    const fb = node("filter", { filter_kind: "tagged" }, 300);
    const u = node("union", {}, 400);
    const sink = node("filter", { filter_kind: "field" }, 500);
    const nodes = [out(), src, fo, fa, fb, u, sink];
    const edges = [
      edge(src.id, fo.id),
      edge(fo.id, fa.id),
      edge(fo.id, fb.id),
      edge(fa.id, u.id),
      edge(fb.id, u.id),
      edge(u.id, sink.id),
      edge(sink.id, OUTPUT_NODE_ID),
    ];
    expect(infer(nodes, edges, sink.id)).toEqual({ lore: null });
  });

  // Slice B (#215): `inputKinds` reduces an inferred type-set to the kinds it
  // spans — the cross-kind (>1) authoring-warning signal (ADR-0031 §F / Consequences).
  describe("inputKinds — cross-kind warning signal (Slice B)", () => {
    const kindsOf = (nodes: ViewGraphNode[], edges: ReturnType<typeof edge>[], id: string, anchor = "scene") =>
      inputKinds(inferInputTypes(byIdOf(nodes), edges, id, anchor, resolvers)).sort();

    it("a single-kind input spans one kind (no warning)", () => {
      const src = node("type", { type: "scene:scene" }, 0);
      const sink = node("filter", { filter_kind: "field" }, 100);
      const nodes = [out(), src, sink];
      const edges = [edge(src.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
      expect(kindsOf(nodes, edges, sink.id)).toEqual(["scene"]);
    });

    it("a union of two kinds spans both (cross-kind → warn)", () => {
      const a = node("type", { type: "scene:scene" }, 0);
      const b = node("descendants_of", { descendants_of: "lore:character" }, 100);
      const u = node("union", {}, 200);
      const sink = node("filter", { filter_kind: "field" }, 300);
      const nodes = [out(), a, b, u, sink];
      const edges = [edge(a.id, u.id), edge(b.id, u.id), edge(u.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
      expect(kindsOf(nodes, edges, sink.id)).toEqual(["lore", "scene"]);
    });

    it("a multi-kind ref `field_of` spans its target kinds (cross-kind → warn)", () => {
      const src = node("type", { type: "scene:scene" }, 0);
      const fo = node("field_of", { project_field: "owner" }, 100);
      const sink = node("filter", { filter_kind: "field" }, 200);
      const nodes = [out(), src, fo, sink];
      const edges = [edge(src.id, fo.id), edge(fo.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
      expect(kindsOf(nodes, edges, sink.id)).toEqual(["lore", "scene"]);
    });

    it("an indeterminate input (scalar field_of → null) spans no kinds (anchor fallback, not cross-kind)", () => {
      const src = node("type", { type: "scene:scene" }, 0);
      const fo = node("field_of", { project_field: "status" }, 100);
      const sink = node("filter", { filter_kind: "field" }, 200);
      const nodes = [out(), src, fo, sink];
      const edges = [edge(src.id, fo.id), edge(fo.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
      expect(kindsOf(nodes, edges, sink.id)).toEqual([]);
    });

    it("an empty cross-kind INTERSECT is determinate (non-null) yet spans no kinds — the thinnest roster, still a cross-kind case", () => {
      // scene ∩ character = ∅ across kinds → combineTypeSets(intersect) drops every
      // kind → a size-0 (NON-null) Map. `rosterWarningFor` must treat this as
      // cross-kind (ts !== null && size !== 1), NOT confuse it with the null
      // (indeterminate) anchor-fallback case above.
      const a = node("type", { type: "scene:scene" }, 0);
      const b = node("descendants_of", { descendants_of: "lore:character" }, 100);
      const x = node("intersect", {}, 200);
      const sink = node("filter", { filter_kind: "field" }, 300);
      const nodes = [out(), a, b, x, sink];
      const edges = [edge(a.id, x.id), edge(b.id, x.id), edge(x.id, sink.id), edge(sink.id, OUTPUT_NODE_ID)];
      // Determinate empty set: an empty object from `dump` (a real Map of size 0),
      // distinct from `null`; `inputKinds` of it is [].
      expect(infer(nodes, edges, sink.id)).toEqual({});
      expect(kindsOf(nodes, edges, sink.id)).toEqual([]);
    });
  });
});
