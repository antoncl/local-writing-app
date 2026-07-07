import { describe, expect, it } from "vitest";
import type { MetadataSchema, StructureDocument, StructureNode, ViewSpec } from "@/lib/types";
import { defaultView, evaluateView, nestWarnings, treeNodeIds, type EvalNode, type ViewGroup } from "@/lib/views/evaluateView";
import { structureToEvalNodes } from "@/lib/views/structureNodes";

// A tiny lore-like roster. Order is load-bearing (manual sort == input order).
const NODES: EvalNode[] = [
  { id: "a", entry_type: "lore:character", title: "Zed", metadata: { tags: ["hero"], pov: "honor" } },
  { id: "b", entry_type: "lore:character", title: "Alice", metadata: { tags: "villain, gotham" } },
  { id: "c", entry_type: "lore:deity", title: "Mara", metadata: { tags: ["gotham"], power: 9 } },
  { id: "d", entry_type: "lore:location", title: "Kitchen", metadata: { locations: ["kitchen", "hall"] } },
  { id: "e", entry_type: "lore:demigod", title: "Cass", metadata: { power: 3 } },
];

// Schema with a `parent:` chain: demigod → deity → (root). character is separate.
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: [] },
    "lore:deity": { name: "Deity", kind: "lore", fields: [] },
    "lore:demigod": { name: "Demigod", kind: "lore", parent: "lore:deity", fields: [] },
    "lore:location": { name: "Location", kind: "lore", fields: [] },
  },
  // Intrinsic fields carry the resolver-stamped `category` so `fieldValue`
  // routes them to the node top-level property, not `metadata` (ADR-0029 §D).
  fields: {
    title: { name: "Title", type: "text", category: "intrinsic" },
    entry_type: { name: "Type", type: "text", category: "intrinsic" },
    id: { name: "ID", type: "text", category: "intrinsic" },
  },
} as unknown as MetadataSchema;

const ids = (spec: ViewSpec, nodes = NODES, ctx = { schema: SCHEMA }) =>
  evaluateView(spec, nodes, ctx).nodes.map((n) => n.id);

describe("default view", () => {
  it("returns the whole universe in input order", () => {
    expect(ids(defaultView("lore"))).toEqual(["a", "b", "c", "d", "e"]);
  });
  it("null expr == whole universe", () => {
    expect(ids({ kind: "lore" })).toEqual(["a", "b", "c", "d", "e"]);
  });
});

describe("leaves", () => {
  it("type: exact entry_type", () => {
    expect(ids({ kind: "lore", expr: { type: "lore:character" } })).toEqual(["a", "b"]);
  });
  it("descendants_of: self + inheriting types", () => {
    expect(ids({ kind: "lore", expr: { descendants_of: "lore:deity" } })).toEqual(["c", "e"]);
  });
  it("descendants_of: a leaf type resolves to just itself", () => {
    expect(ids({ kind: "lore", expr: { descendants_of: "lore:character" } })).toEqual(["a", "b"]);
  });
  it("tagged: matches array and CSV tag fields", () => {
    expect(ids({ kind: "lore", expr: { tagged: "gotham" } })).toEqual(["b", "c"]);
  });
  it("hand_picked: explicit ids, in universe order", () => {
    expect(ids({ kind: "lore", expr: { hand_picked: ["e", "a"] } })).toEqual(["a", "e"]);
  });

  // `title` is a top-level node property, not metadata — a field predicate on it
  // must read node.title, not the absent metadata.title (regression for the
  // missing-Title field the picker now surfaces).
  it("field predicate on `title` reads the node title", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "title", op: "eq", value: "Alice" } } })).toEqual(["b"]);
    expect(ids({ kind: "lore", expr: { field: { key: "title", op: "set" } } })).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("field sort on `title` orders by the node title", () => {
    const sorted = evaluateView(
      { kind: "lore", sort: { by: "field", field_key: "title", dir: "asc" } },
      NODES,
      { schema: SCHEMA },
    ).nodes.map((n) => n.title);
    expect(sorted).toEqual(["Alice", "Cass", "Kitchen", "Mara", "Zed"]);
  });

  // The intrinsic resolver generalizes beyond title: `entry_type` is also a
  // top-level node property (#116), so a field predicate on it reads
  // node.entry_type, not the absent metadata.entry_type.
  it("field predicate on `entry_type` reads the node entry_type", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "entry_type", op: "eq", value: "lore:character" } } })).toEqual([
      "a",
      "b",
    ]);
  });
});

// The backend (Pydantic) serializes a ViewExpr with *every* slot present —
// unset ones as explicit `null`, not omitted. The evaluator must treat those
// nulls as "unset" and not misfire on the first slot it checks. Regression for
// the step-4 bug where a saved `descendants_of` view matched nothing because
// `expr.type` (null) tripped the `!== undefined` guard.
describe("backend-dense exprs (explicit null slots)", () => {
  const NULLS = {
    union: null,
    intersect: null,
    difference: null,
    complement: null,
    annotate: null,
    of: null,
    type: null,
    descendants_of: null,
    tagged: null,
    field: null,
    hand_picked: null,
    view_ref: null,
  } as const;
  // Cast through `unknown`: the ViewExpr/ViewSort types model unset slots as
  // `undefined`, but the backend serializes them as explicit `null`. This test
  // exercises exactly that runtime shape, which the authoring types don't (and
  // needn't) admit.
  const dense = (overlay: Record<string, unknown>): ViewSpec => ({
    kind: "lore",
    expr: { ...NULLS, ...overlay } as unknown as ViewSpec["expr"],
    sort: { by: "manual", field_key: null, dir: "asc" } as unknown as ViewSpec["sort"],
  });

  it("descendants_of survives sibling nulls", () => {
    expect(ids(dense({ descendants_of: "lore:deity" }))).toEqual(["c", "e"]);
  });
  it("tagged survives sibling nulls", () => {
    expect(ids(dense({ tagged: "gotham" }))).toEqual(["b", "c"]);
  });
  it("field survives sibling nulls", () => {
    expect(ids(dense({ field: { key: "pov", op: "eq", value: "honor" } }))).toEqual(["a"]);
  });
  it("color-only annotate (label null) makes no group", () => {
    const spec = dense({ annotate: { label: null, color: "red", rank: null }, of: { ...NULLS, tagged: "gotham" } });
    const result = evaluateView(spec, NODES, { schema: SCHEMA });
    expect(result.groups).toBeNull();
    expect(result.annotations.get("b")?.color).toBe("red");
  });
});

describe("field predicates", () => {
  it("eq", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "pov", op: "eq", value: "honor" } } })).toEqual(["a"]);
  });
  it("neq excludes the match (and keeps unset rows)", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "pov", op: "neq", value: "honor" } } })).toEqual([
      "b", "c", "d", "e",
    ]);
  });
  it("eq coerces numbers", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "power", op: "eq", value: "9" } } })).toEqual(["c"]);
  });
  it("includes: membership in a collection field", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "locations", op: "includes", value: "kitchen" } } })).toEqual([
      "d",
    ]);
  });
  it("not_includes", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "locations", op: "not_includes", value: "kitchen" } } })).toEqual([
      "a", "b", "c", "e",
    ]);
  });
  it("set / unset", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "power", op: "set" } } })).toEqual(["c", "e"]);
    expect(ids({ kind: "lore", expr: { field: { key: "power", op: "unset" } } })).toEqual(["a", "b", "d"]);
  });
});

describe("combinators", () => {
  it("union (n-ary)", () => {
    expect(ids({ kind: "lore", expr: { union: [{ type: "lore:character" }, { type: "lore:deity" }] } })).toEqual([
      "a", "b", "c",
    ]);
  });
  it("intersect", () => {
    expect(
      ids({ kind: "lore", expr: { intersect: [{ descendants_of: "lore:deity" }, { tagged: "gotham" }] } }),
    ).toEqual(["c"]);
  });
  it("difference is keep ∖ remove (not commutative)", () => {
    expect(
      ids({
        kind: "lore",
        expr: { difference: { keep: { descendants_of: "lore:deity" }, remove: { type: "lore:demigod" } } },
      }),
    ).toEqual(["c"]);
  });
  it("complement is universe ∖ A", () => {
    expect(ids({ kind: "lore", expr: { complement: { type: "lore:character" } } })).toEqual(["c", "d", "e"]);
  });
});

describe("named-handle groups (#91)", () => {
  const grouped: ViewSpec = {
    kind: "lore",
    groups: [
      { name: "Cast", expr: { type: "lore:character" } },
      { name: "Deities", expr: { descendants_of: "lore:deity" } },
    ],
  };

  it("2+ handles render as groups, in handle order", () => {
    const res = evaluateView(grouped, NODES, { schema: SCHEMA });
    expect(res.groups?.map((g) => [g.label, g.children.map((c) => c.nodeId)])).toEqual([
      ["Cast", ["a", "b"]],
      ["Deities", ["c", "e"]],
    ]);
  });

  it("flat membership (nodes) unions the handles, deduped, in handle order", () => {
    const res = evaluateView(grouped, NODES, { schema: SCHEMA });
    expect(res.nodes.map((n) => n.id)).toEqual(["a", "b", "c", "e"]);
  });

  it("a node in two handles appears under both groups but once in nodes", () => {
    const overlap: ViewSpec = {
      kind: "lore",
      groups: [
        { name: "Gotham", expr: { tagged: "gotham" } }, // b, c
        { name: "Deities", expr: { descendants_of: "lore:deity" } }, // c, e
      ],
    };
    const res = evaluateView(overlap, NODES, { schema: SCHEMA });
    expect(res.groups?.map((g) => [g.label, g.children.map((c) => c.nodeId)])).toEqual([
      ["Gotham", ["b", "c"]],
      ["Deities", ["c", "e"]],
    ]);
    expect(res.nodes.map((n) => n.id)).toEqual(["b", "c", "e"]);
  });

  it("a single populated handle renders flat (groups null)", () => {
    const one: ViewSpec = { kind: "lore", groups: [{ name: "Cast", expr: { type: "lore:character" } }] };
    const res = evaluateView(one, NODES, { schema: SCHEMA });
    expect(res.groups).toBeNull();
    expect(res.nodes.map((n) => n.id)).toEqual(["a", "b"]);
  });

  it("empty handles drop out; if only one is populated it collapses to flat", () => {
    const withEmpty: ViewSpec = {
      kind: "lore",
      groups: [
        { name: "Cast", expr: { type: "lore:character" } },
        { name: "Robots", expr: { type: "lore:robot" } }, // no members
      ],
    };
    const res = evaluateView(withEmpty, NODES, { schema: SCHEMA });
    expect(res.groups).toBeNull();
    expect(res.nodes.map((n) => n.id)).toEqual(["a", "b"]);
  });

  it("a group with null expr is the whole universe", () => {
    const spec: ViewSpec = {
      kind: "lore",
      groups: [
        { name: "Everything", expr: null },
        { name: "Deities", expr: { descendants_of: "lore:deity" } },
      ],
    };
    const res = evaluateView(spec, NODES, { schema: SCHEMA });
    expect(res.groups?.map((g) => [g.label, g.children.map((c) => c.nodeId)])).toEqual([
      ["Everything", ["a", "b", "c", "d", "e"]],
      ["Deities", ["c", "e"]],
    ]);
  });

  it("per-segment sort overrides the fallback sort", () => {
    const spec: ViewSpec = {
      kind: "lore",
      sort: { by: "manual" },
      groups: [
        { name: "Cast", expr: { type: "lore:character" }, sort: { by: "title", dir: "asc" } },
        { name: "Deities", expr: { descendants_of: "lore:deity" } },
      ],
    };
    const res = evaluateView(spec, NODES, { schema: SCHEMA });
    // Cast sorted by title (Alice before Zed → b, a); Deities keeps manual order.
    expect(res.groups?.map((g) => [g.label, g.children.map((c) => c.nodeId)])).toEqual([
      ["Cast", ["b", "a"]],
      ["Deities", ["c", "e"]],
    ]);
  });

  it("color annotate (Highlight) stamps annotations without creating a group", () => {
    const res = evaluateView(
      { kind: "lore", expr: { annotate: { color: "amber" }, of: { tagged: "gotham" } } },
      NODES,
      { schema: SCHEMA },
    );
    expect(res.groups).toBeNull();
    expect(res.annotations.get("b")?.color).toBe("amber");
    expect(res.annotations.get("c")?.color).toBe("amber");
    expect(res.annotations.has("a")).toBe(false);
  });
});

describe("sort", () => {
  it("manual preserves input order", () => {
    expect(ids({ kind: "lore", expr: null, sort: { by: "manual" } })).toEqual(["a", "b", "c", "d", "e"]);
  });
  it("by title asc/desc", () => {
    expect(ids({ kind: "lore", sort: { by: "title", dir: "asc" } })).toEqual(["b", "e", "d", "c", "a"]);
    expect(ids({ kind: "lore", sort: { by: "title", dir: "desc" } })).toEqual(["a", "c", "d", "e", "b"]);
  });
  it("by field, numeric", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "power", op: "set" } }, sort: { by: "field", field_key: "power" } })).toEqual([
      "e", "c",
    ]);
  });
  it("by field desc keeps empty/unset values last (not floated to the top)", () => {
    // power: c=9, e=3; a/b/d unset. desc orders the populated rows, empties stay
    // last in input order — regression for the `dir * compareScalar` flip that
    // sent blanks to the top of a descending sort.
    expect(ids({ kind: "lore", sort: { by: "field", field_key: "power", dir: "desc" } })).toEqual([
      "c", "e", "a", "b", "d",
    ]);
  });
});

describe("view_ref", () => {
  const saved: Record<string, ViewSpec> = {
    "cast-view": { kind: "lore", expr: { type: "lore:character" } },
  };
  const ctx = { schema: SCHEMA, resolveView: (id: string) => saved[id] ?? null };

  it("embeds a saved view's membership", () => {
    expect(evaluateView({ kind: "lore", expr: { view_ref: "cast-view" } }, NODES, ctx).nodes.map((n) => n.id)).toEqual([
      "a", "b",
    ]);
  });

  it("embeds a GROUPED saved view's flat membership (union of handles, not the universe)", () => {
    // Regression: a view_ref to a grouped view (expr null, groups set — the shape
    // graphToSpec emits for any 2+ handle view) used to fall through to the whole
    // kind roster because evalViewRef read only ref.expr.
    const withGroups: Record<string, ViewSpec> = {
      "cast-and-gods": {
        kind: "lore",
        groups: [
          { name: "Cast", expr: { type: "lore:character" } }, // a, b
          { name: "Gods", expr: { descendants_of: "lore:deity" } }, // c, e
        ],
      },
    };
    const res = evaluateView({ kind: "lore", expr: { view_ref: "cast-and-gods" } }, NODES, {
      schema: SCHEMA,
      resolveView: (id) => withGroups[id] ?? null,
    });
    expect(res.nodes.map((n) => n.id)).toEqual(["a", "b", "c", "e"]); // NOT d (location)
  });

  it("a cycle contributes nothing rather than looping", () => {
    const cyclic: Record<string, ViewSpec> = { self: { kind: "lore", expr: { view_ref: "self" } } };
    const res = evaluateView({ kind: "lore", expr: { view_ref: "self" } }, NODES, {
      schema: SCHEMA,
      resolveView: (id) => cyclic[id] ?? null,
    });
    expect(res.nodes).toEqual([]);
  });
});

// --- sub-flow nesting: a bare view_ref to a GROUPED view contributes its group
// structure instead of flattening (#101). This is the "sub-flow → handle" path.
describe("sub-flow nesting (#101)", () => {
  // castAndGods: two handles; heroes/gods: one handle each (still grouped specs).
  const saved: Record<string, ViewSpec> = {
    "cast-and-gods": {
      kind: "lore",
      groups: [
        { name: "Cast", expr: { type: "lore:character" } }, // a, b
        { name: "Gods", expr: { descendants_of: "lore:deity" } }, // c, e
      ],
    },
    heroes: { kind: "lore", groups: [{ name: "Heroes", expr: { type: "lore:character" } }] }, // a, b
    gods: { kind: "lore", groups: [{ name: "Gods", expr: { descendants_of: "lore:deity" } }] }, // c, e
    overlap: {
      kind: "lore",
      groups: [
        { name: "Gotham", expr: { tagged: "gotham" } }, // b, c
        { name: "Gods", expr: { descendants_of: "lore:deity" } }, // c, e
      ],
    },
    flat: { kind: "lore", expr: { type: "lore:character" } }, // no group structure
  };
  const ctx = { schema: SCHEMA, resolveView: (id: string) => saved[id] ?? null };
  // Compact a group tree to [label, [child ids]] rows for readable assertions.
  // Tree-uniform (#181): a leaf is a childless group → its bare nodeId; a
  // container → [label, its children compacted].
  const rows = (groups: ViewGroup[] | null): unknown =>
    groups?.map((g) => (g.children.length ? [g.label, rows(g.children)] : g.nodeId));

  it("a top-level bare grouped view_ref inherits the sub-view's groups (no wrapper)", () => {
    const res = evaluateView({ kind: "lore", expr: { view_ref: "cast-and-gods" } }, NODES, ctx);
    expect(rows(res.groups)).toEqual([
      ["Cast", ["a", "b"]],
      ["Gods", ["c", "e"]],
    ]);
    expect(res.nodes.map((n) => n.id)).toEqual(["a", "b", "c", "e"]); // flat membership preserved
  });

  it("a handle fed by a grouped view_ref nests it under the handle name", () => {
    const spec: ViewSpec = {
      kind: "lore",
      groups: [
        { name: "By type", expr: { view_ref: "cast-and-gods" } },
        { name: "Places", expr: { type: "lore:location" } }, // d
      ],
    };
    const res = evaluateView(spec, NODES, ctx);
    expect(rows(res.groups)).toEqual([
      ["By type", [
        ["Cast", ["a", "b"]],
        ["Gods", ["c", "e"]],
      ]],
      ["Places", ["d"]],
    ]);
  });

  it("a lone handle over a grouped sub-flow drops the wrapper (top level not considered)", () => {
    const spec: ViewSpec = { kind: "lore", groups: [{ name: "By type", expr: { view_ref: "cast-and-gods" } }] };
    const res = evaluateView(spec, NODES, ctx);
    expect(rows(res.groups)).toEqual([
      ["Cast", ["a", "b"]],
      ["Gods", ["c", "e"]],
    ]);
  });

  it("union of two grouped view_refs concatenates their rows, preserving paths", () => {
    // Anton's semantic: in the denormalized model a union is a concatenation of
    // (node, path) rows — each operand keeps its own group structure.
    const res = evaluateView(
      { kind: "lore", expr: { union: [{ view_ref: "heroes" }, { view_ref: "gods" }] } },
      NODES,
      ctx,
    );
    expect(rows(res.groups)).toEqual([
      ["Heroes", ["a", "b"]],
      ["Gods", ["c", "e"]],
    ]);
  });

  it("a node in two sub-groups appears under both (dedupe is per (node, path))", () => {
    const res = evaluateView({ kind: "lore", expr: { view_ref: "overlap" } }, NODES, ctx);
    expect(rows(res.groups)).toEqual([
      ["Gotham", ["b", "c"]],
      ["Gods", ["c", "e"]], // c appears under both branches
    ]);
    expect(res.nodes.map((n) => n.id)).toEqual(["b", "c", "e"]); // once in flat membership
  });

  it("a view_ref buried in the set algebra flattens (no group structure to preserve)", () => {
    const res = evaluateView(
      { kind: "lore", expr: { intersect: [{ view_ref: "cast-and-gods" }, { tagged: "gotham" }] } },
      NODES,
      ctx,
    );
    expect(res.groups).toBeNull();
    // cast-and-gods flattens to {a,b,c,e}; ∩ gotham {b,c} → b, c (c is a deity).
    expect(res.nodes.map((n) => n.id)).toEqual(["b", "c"]);
  });

  it("a bare view_ref to a FLAT view stays flat", () => {
    const res = evaluateView({ kind: "lore", expr: { view_ref: "flat" } }, NODES, ctx);
    expect(res.groups).toBeNull();
    expect(res.nodes.map((n) => n.id)).toEqual(["a", "b"]);
  });
});

// --- tree presentation (#101) ----------------------------------------------

// A small manuscript: two acts, chapters, scenes, plus one empty chapter. Tags
// live in computed_metadata so `tagged` leaves apply (structureToEvalNodes maps
// computed_metadata → EvalNode.metadata).
const sn = (
  id: string,
  type: string,
  title: string,
  children: StructureNode[] = [],
  tags: string[] = [],
): StructureNode => ({ id, type, title, children, computed_metadata: { tags } });

const MANUSCRIPT: StructureDocument = {
  root: sn("root", "manuscript:base", "Book", [
    sn("act1", "manuscript:act", "Act 1", [
      sn("ch1", "manuscript:chapter", "Ch 1", [
        sn("s1", "manuscript:scene", "Scene 1", [], ["honor"]),
        sn("s2", "manuscript:scene", "Scene 2", []),
      ]),
      sn("ch2", "manuscript:chapter", "Ch 2 (empty)", []),
    ]),
    sn("act2", "manuscript:act", "Act 2", [
      sn("ch3", "manuscript:chapter", "Ch 3", [sn("s3", "manuscript:scene", "Scene 3", [], ["honor"])]),
    ]),
  ]),
};

// Compact a group tree for readable assertions: a leaf is its bare label; a
// container is `[label, [children...]]`.
const shape = (groups: ViewGroup[]): unknown =>
  groups.map((g) => (g.children.length ? [g.label, shape(g.children)] : g.label));

const tree = (expr: ViewSpec["expr"] = null) => {
  const nodes = structureToEvalNodes(MANUSCRIPT);
  return evaluateView({ kind: "manuscript", presentation: "tree", expr }, nodes);
};

describe("tree presentation (#101)", () => {
  it("structureToEvalNodes carries each node's ancestry outer→inner", () => {
    const nodes = structureToEvalNodes(MANUSCRIPT);
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n.ancestry?.map((s) => s.key)]));
    expect(byId.act1).toEqual([]);
    expect(byId.ch1).toEqual(["act1"]);
    expect(byId.s1).toEqual(["act1", "ch1"]);
    expect(byId.s3).toEqual(["act2", "ch3"]);
  });

  it("an unfiltered view nests the whole structure, keeping empty containers", () => {
    expect(shape(tree().groups!)).toEqual([
      ["Act 1", [
        ["Ch 1", ["Scene 1", "Scene 2"]],
        "Ch 2 (empty)", // empty container (a member) still appears, childless
      ]],
      ["Act 2", [["Ch 3", ["Scene 3"]]]],
    ]);
  });

  it("ancestor segments are real nodes (nodeId set) → render as NodeRows", () => {
    const act1 = tree().groups![0];
    expect(act1.nodeId).toBe("act1");
    expect(act1.children[0].nodeId).toBe("ch1");
    expect(act1.children[0].children[0].nodeId).toBe("s1");
  });

  it("a filtered view keeps a match's ancestors and prunes empty branches", () => {
    // Only the honor-tagged scenes survive; ch2 (no match) and its siblings drop.
    expect(shape(tree({ tagged: "honor" }).groups!)).toEqual([
      ["Act 1", [["Ch 1", ["Scene 1"]]]], // s2 gone, ch2 gone
      ["Act 2", [["Ch 3", ["Scene 3"]]]],
    ]);
  });

  it("a matched container and its matched scene merge into one branch (no double appearance)", () => {
    // ch1 itself is tagged AND its scene s1 is tagged: ch1 appears once, with s1 nested.
    const withTag: StructureDocument = {
      root: sn("root", "manuscript:base", "Book", [
        sn("act1", "manuscript:act", "Act 1", [
          sn("ch1", "manuscript:chapter", "Ch 1", [sn("s1", "manuscript:scene", "Scene 1", [], ["x"])], ["x"]),
        ]),
      ]),
    };
    const res = evaluateView(
      { kind: "manuscript", presentation: "tree", expr: { tagged: "x" } },
      structureToEvalNodes(withTag),
    );
    expect(shape(res.groups!)).toEqual([["Act 1", [["Ch 1", ["Scene 1"]]]]]);
    // ch1 occurs exactly once across the tree.
    const act1 = res.groups![0];
    expect(act1.children.filter((g) => g.nodeId === "ch1")).toHaveLength(1);
  });

  it("flat membership still lists every matching node (containers + leaves)", () => {
    expect(tree({ tagged: "honor" }).nodes.map((n) => n.id)).toEqual(["s1", "s3"]);
  });

  it("composes handle grouping with structural nesting (#181): a chapter tree within each bucket", () => {
    // The old fork returned before reading `groups`, so group-by + nest-by-chapter
    // were mutually exclusive. Now handles are the outer path, ancestry the inner.
    const res = evaluateView(
      {
        kind: "manuscript",
        presentation: "tree",
        groups: [
          { name: "Honored", expr: { tagged: "honor" } }, // s1, s3
          { name: "Scenes", expr: { type: "manuscript:scene" } }, // s1, s2, s3
        ],
      },
      structureToEvalNodes(MANUSCRIPT),
    );
    expect(shape(res.groups!)).toEqual([
      ["Honored", [
        ["Act 1", [["Ch 1", ["Scene 1"]]]],
        ["Act 2", [["Ch 3", ["Scene 3"]]]],
      ]],
      ["Scenes", [
        ["Act 1", [["Ch 1", ["Scene 1", "Scene 2"]]]],
        ["Act 2", [["Ch 3", ["Scene 3"]]]],
      ]],
    ]);
    // Ancestors stay structural context — flat membership is the matched scenes only.
    expect(res.nodes.map((n) => n.id)).toEqual(["s1", "s3", "s2"]);
  });

  it("treeNodeIds collects matches + kept ancestors, dropping pruned branches", () => {
    // Filtered tree keeps s1/s3 and their ancestors; s2 and ch2 are gone.
    expect(treeNodeIds(tree({ tagged: "honor" }).groups)).toEqual(
      new Set(["act1", "ch1", "s1", "act2", "ch3", "s3"]),
    );
    // Unfiltered → every structure node is visible.
    expect(treeNodeIds(tree().groups)).toEqual(
      new Set(["act1", "ch1", "s1", "s2", "ch2", "act2", "ch3", "s3"]),
    );
  });
});

// --- nest: relational denormalization from lore links (ADR-0028, #107) -----

// Compact a group tree the same way the sub-flow suite does (#181 tree-uniform):
// a container is `[label, children]`; a leaf is a childless group → its nodeId.
const nrows = (groups: ViewGroup[] | null): unknown =>
  groups?.map((g) => (g.children.length ? [g.label, nrows(g.children)] : g.nodeId));

// Nested locations via a `parent` entity_ref (child → parent). Aeria is a root
// (no parent); nowhere points at a ghost id → orphan.
const LOCS: EvalNode[] = [
  { id: "aeria", entry_type: "lore:location", title: "Aeria", metadata: {} },
  { id: "valen", entry_type: "lore:location", title: "Valen", metadata: { parent: "aeria" } },
  { id: "dawn", entry_type: "lore:location", title: "Dawnhold", metadata: { parent: "valen" } },
  { id: "nowhere", entry_type: "lore:location", title: "Nowhere", metadata: { parent: "ghost" } },
];
const roots = { field: { key: "parent", op: "unset" as const } };
const nestLocs = (recursive: boolean): ViewSpec => ({
  kind: "lore",
  expr: { nest: { parents: roots, match: { field: "parent", direction: "child_to_parent", by: "ref" }, recursive } },
});

describe("nest — child→parent by ref", () => {
  it("recursive self-loop walks an unknown-depth hierarchy; parents are real-node headers", () => {
    const res = evaluateView(nestLocs(true), LOCS);
    expect(nrows(res.groups)).toEqual([["Aeria", [["Valen", ["dawn"]]]]]);
    // Parent segments carry identity (nodeId set) → collapsible NodeRows.
    expect(res.groups![0].nodeId).toBe("aeria");
    expect(res.groups![0].children[0].nodeId).toBe("valen");
    // Flat membership includes the interior parents, ancestors before leaf.
    expect(res.nodes.map((n) => n.id)).toEqual(["aeria", "valen", "dawn"]);
  });

  it("non-recursive attaches exactly one level (grandchildren stay orphans)", () => {
    const res = evaluateView(nestLocs(false), LOCS);
    expect(nrows(res.groups)).toEqual([["Aeria", ["valen"]]]);
    // dawn (a grandchild) and nowhere never attach in a single pass.
    expect(res.diagnostics?.orphansDropped).toBe(2);
  });

  it("counts orphans (children matching no parent) and drops them", () => {
    const res = evaluateView(nestLocs(true), LOCS);
    expect(res.nodes.some((n) => n.id === "nowhere")).toBe(false);
    expect(res.diagnostics?.orphansDropped).toBe(1);
    expect(res.diagnostics?.cyclicLinksSkipped).toBe(0);
  });

  it("a childless root stays (renders as a leaf, not a header)", () => {
    const lone: EvalNode[] = [{ id: "solo", entry_type: "lore:location", title: "Solo", metadata: {} }];
    const res = evaluateView(nestLocs(true), lone);
    // No paths → flat list, solo present.
    expect(res.nodes.map((n) => n.id)).toEqual(["solo"]);
  });
});

describe("nest — many-to-many & data cycles", () => {
  it("a child under two parents appears under both (dedupe is per (node, path))", () => {
    const FAM: EvalNode[] = [
      { id: "gp", entry_type: "lore:character", title: "Grandpa", metadata: {} },
      { id: "mom", entry_type: "lore:character", title: "Mom", metadata: { parents: ["gp"] } },
      { id: "dad", entry_type: "lore:character", title: "Dad", metadata: { parents: ["gp"] } },
      { id: "kid", entry_type: "lore:character", title: "Kid", metadata: { parents: ["mom", "dad"] } },
    ];
    const res = evaluateView(
      {
        kind: "lore",
        expr: {
          nest: {
            parents: { field: { key: "parents", op: "unset" } },
            match: { field: "parents", direction: "child_to_parent", by: "ref" },
            recursive: true,
          },
        },
      },
      FAM,
    );
    expect(nrows(res.groups)).toEqual([["Grandpa", [["Mom", ["kid"]], ["Dad", ["kid"]]]]]);
  });

  it("the ancestor-path guard drops cyclic links and still terminates (thicket seed)", () => {
    const CYC: EvalNode[] = [
      { id: "a", entry_type: "lore:location", title: "A", metadata: { parent: "b" } },
      { id: "b", entry_type: "lore:location", title: "B", metadata: { parent: "a" } },
    ];
    // Seed parents = whole universe (no roots exist) → both expand, hitting the
    // A↔B cycle; the guard drops the back-edges. Reaching here proves termination.
    const res = evaluateView(
      { kind: "lore", expr: { nest: { match: { field: "parent", direction: "child_to_parent", by: "ref" }, recursive: true } } },
      CYC,
    );
    expect(res.diagnostics?.cyclicLinksSkipped).toBe(2);
    expect(nrows(res.groups)).toEqual([["A", ["b"]], ["B", ["a"]]]);
  });

  it("runaway fan-out trips the K·N ceiling, hard-stops, and truncates", () => {
    // 5 nodes each referencing the other 4 as parents → a near-complete relation;
    // simple paths blow past K·N (8·5). Must terminate with the truncation flag.
    const FULL: EvalNode[] = Array.from({ length: 5 }, (_, i) => ({
      id: `f${i}`,
      entry_type: "lore:location",
      title: `F${i}`,
      metadata: { parent: Array.from({ length: 5 }, (_, j) => `f${j}`).filter((id) => id !== `f${i}`) },
    }));
    const res = evaluateView(
      { kind: "lore", expr: { nest: { match: { field: "parent", direction: "child_to_parent", by: "ref" }, recursive: true } } },
      FULL,
    );
    expect(res.diagnostics?.fanoutTruncated).toBe(true);
  });
});

describe("nest — other match modes", () => {
  it("by title: a child's tag equals the parent's title (case-insensitive)", () => {
    const TITLED: EvalNode[] = [
      { id: "stark", entry_type: "lore:faction", title: "Stark", metadata: {} },
      { id: "arya", entry_type: "lore:character", title: "Arya", metadata: { house: ["stark"] } },
    ];
    const res = evaluateView(
      {
        kind: "lore",
        expr: {
          nest: {
            parents: { field: { key: "house", op: "unset" } }, // Stark has no house tag → a root
            match: { field: "house", direction: "child_to_parent", by: "title" },
            recursive: true,
          },
        },
      },
      TITLED,
    );
    expect(nrows(res.groups)).toEqual([["Stark", ["arya"]]]);
  });

  it("parent→children: the parent card holds the refs to its children", () => {
    const TEAMS: EvalNode[] = [
      { id: "team", entry_type: "lore:group", title: "Team", metadata: { members: ["alice", "bob"] } },
      { id: "alice", entry_type: "lore:character", title: "Alice", metadata: {} },
      { id: "bob", entry_type: "lore:character", title: "Bob", metadata: {} },
    ];
    const res = evaluateView(
      {
        kind: "lore",
        expr: {
          nest: {
            parents: { type: "lore:group" },
            match: { field: "members", direction: "parent_to_children", by: "ref" },
          },
        },
      },
      TEAMS,
    );
    expect(nrows(res.groups)).toEqual([["Team", ["alice", "bob"]]]);
  });

  it("does not run for non-relational views (diagnostics stays absent)", () => {
    const res = evaluateView({ kind: "lore", expr: { type: "lore:character" } }, NODES);
    expect(res.diagnostics).toBeUndefined();
  });
});

describe("nestWarnings — surfacing diagnostics (#110)", () => {
  it("no diagnostics → no warnings", () => {
    expect(nestWarnings(undefined)).toEqual([]);
    expect(nestWarnings({ cyclicLinksSkipped: 0, orphansDropped: 0, fanoutTruncated: false })).toEqual([]);
  });

  it("fan-out truncation warns first, with the likely cause", () => {
    const w = nestWarnings({ cyclicLinksSkipped: 3, orphansDropped: 2, fanoutTruncated: true });
    expect(w).toHaveLength(3);
    expect(w[0]).toMatch(/fan-out/i); // most severe first
    expect(w[0]).toMatch(/roots/i); // names the likely cause / fix
  });

  it("pluralizes cyclic-link and orphan counts", () => {
    expect(nestWarnings({ cyclicLinksSkipped: 1, orphansDropped: 1, fanoutTruncated: false })).toEqual([
      "1 cyclic link skipped (a card is its own ancestor).",
      "1 unmatched child dropped (matched no parent).",
    ]);
    expect(nestWarnings({ cyclicLinksSkipped: 2, orphansDropped: 3, fanoutTruncated: false })).toEqual([
      "2 cyclic links skipped (a card is its own ancestor).",
      "3 unmatched children dropped (matched no parent).",
    ]);
  });

  it("threads through a real evaluation (orphan drop → a warning)", () => {
    const res = evaluateView(nestLocs(true), LOCS);
    expect(nestWarnings(res.diagnostics)).toEqual(["1 unmatched child dropped (matched no parent)."]);
  });
});
