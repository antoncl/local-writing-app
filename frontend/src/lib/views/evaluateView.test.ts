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
    expect(ids({ kind: "lore", expr: { field: { key: "title", op: "overlap", value: "Alice" } } })).toEqual(["b"]);
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
    expect(ids({ kind: "lore", expr: { field: { key: "entry_type", op: "overlap", value: "lore:character" } } })).toEqual([
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
    field_of: null,
    type: null,
    descendants_of: null,
    tagged: null,
    field: null,
    hand_picked: null,
    view_ref: null,
    var: null,
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
    expect(ids(dense({ field: { key: "pov", op: "overlap", value: "honor" } }))).toEqual(["a"]);
  });
  it("color-only annotate (label null) makes no group", () => {
    const spec = dense({ annotate: { label: null, color: "red", rank: null }, of: { ...NULLS, tagged: "gotham" } });
    const result = evaluateView(spec, NODES, { schema: SCHEMA });
    expect(result.groups).toBeNull();
    expect(result.annotations.get("b")?.color).toBe("red");
  });
});

describe("field predicates (op enum 6→4: overlap/disjoint/set/unset)", () => {
  it("overlap: single value (== case)", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "pov", op: "overlap", value: "honor" } } })).toEqual(["a"]);
  });
  it("disjoint excludes the match (and keeps unset rows)", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "pov", op: "disjoint", value: "honor" } } })).toEqual([
      "b", "c", "d", "e",
    ]);
  });
  it("overlap coerces numbers to strings", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "power", op: "overlap", value: "9" } } })).toEqual(["c"]);
  });
  it("overlap: single-valued field against a SET of allowed values (∈, no storage change)", () => {
    // The 6→4 win: `status ∈ {draft, revised}` / `pov ∈ {honor, gotham}` — a
    // single-valued field filters against a multi-pick operand set (ADR-0031 §E).
    expect(ids({ kind: "lore", expr: { field: { key: "pov", op: "overlap", value: ["honor", "none"] } } })).toEqual([
      "a",
    ]);
  });
  it("overlap: membership in a collection field (former `includes`)", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "locations", op: "overlap", value: "kitchen" } } })).toEqual([
      "d",
    ]);
  });
  it("disjoint: former `not_includes`", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "locations", op: "disjoint", value: "kitchen" } } })).toEqual([
      "a", "b", "c", "e",
    ]);
  });
  it("set / unset (presence, operand ignored)", () => {
    expect(ids({ kind: "lore", expr: { field: { key: "power", op: "set" } } })).toEqual(["c", "e"]);
    expect(ids({ kind: "lore", expr: { field: { key: "power", op: "unset" } } })).toEqual(["a", "b", "d"]);
  });
});

// #202: the 6→4 op collapse routed EVERY comparison through comma-splitting,
// tokenizing scalar values (a title, a select) and dropping the numeric
// equivalence the old `scalarEq` had. A genuinely scalar field must compare its
// WHOLE value; only collection fields (multi_select / entity_ref_list / tags, or
// an array value) tokenize.
describe("scalar fields compare whole, collections tokenize (#202)", () => {
  const ROWS: EvalNode[] = [
    { id: "q", entry_type: "lore:character", title: "Alice, Queen of Hearts", metadata: { power: 9, faction: "Red, White", roles: "red, white" } },
    { id: "p", entry_type: "lore:character", title: "Bob", metadata: { power: 3, faction: "Blue", roles: "blue" } },
  ];
  const SC = {
    version: 1,
    entry_types: {},
    fields: {
      title: { name: "Title", type: "text", category: "intrinsic" },
      power: { name: "Power", type: "number", category: "stored" },
      faction: { name: "Faction", type: "text", category: "stored" },
      roles: { name: "Roles", type: "tags", category: "stored" },
    },
  } as unknown as MetadataSchema;
  const run = (spec: ViewSpec) => evaluateView(spec, ROWS, { schema: SC }).nodes.map((n) => n.id);

  it("intrinsic title with a comma is ONE token — a fragment does not match", () => {
    expect(run({ kind: "lore", expr: { field: { key: "title", op: "overlap", value: "Alice" } } })).toEqual([]);
  });
  it("intrinsic title matches its whole comma-bearing value", () => {
    expect(run({ kind: "lore", expr: { field: { key: "title", op: "overlap", value: "Alice, Queen of Hearts" } } })).toEqual(["q"]);
  });
  it("disjoint on a title fragment keeps the comma-bearing row (was wrongly dropped)", () => {
    expect(run({ kind: "lore", expr: { field: { key: "title", op: "disjoint", value: "Alice" } } })).toEqual(["q", "p"]);
  });
  it("scalar text field with a comma compares whole, not split", () => {
    expect(run({ kind: "lore", expr: { field: { key: "faction", op: "overlap", value: "Red" } } })).toEqual([]);
    expect(run({ kind: "lore", expr: { field: { key: "faction", op: "overlap", value: "Red, White" } } })).toEqual(["q"]);
  });
  it("number field keeps numeric equivalence (9 matches '9.0')", () => {
    expect(run({ kind: "lore", expr: { field: { key: "power", op: "overlap", value: "9.0" } } })).toEqual(["q"]);
  });
  it("numeric equivalence is gated to `number` fields — a text/select code '007' does NOT match '7'", () => {
    // faction is `text`; the numeric arm must not fire, or zero-padded/decimal
    // codes would conflate. (power, a `number`, still coerces above.)
    const ROWS2: EvalNode[] = [
      { id: "z", entry_type: "lore:character", title: "Z", metadata: { faction: "007" } },
    ];
    const r = evaluateView({ kind: "lore", expr: { field: { key: "faction", op: "overlap", value: "7" } } }, ROWS2, { schema: SC });
    expect(r.nodes.map((n) => n.id)).toEqual([]);
  });
  it("a declared collection field (tags) still tokenizes a CSV string", () => {
    expect(run({ kind: "lore", expr: { field: { key: "roles", op: "overlap", value: "red" } } })).toEqual(["q"]);
    expect(run({ kind: "lore", expr: { field: { key: "roles", op: "disjoint", value: "red" } } })).toEqual(["p"]);
  });
  it("a scalar field_of projection stays whole when fed as an operand (#202 projection-side gap)", () => {
    const rows: EvalNode[] = [
      { id: "q", entry_type: "lore:character", title: "Q", metadata: { faction: "Red, White" } },
      { id: "r", entry_type: "lore:character", title: "R", metadata: { faction: "Red" } },
    ];
    // Project q's scalar faction → {"Red, White"} (NOT {"Red","White"}), then keep
    // characters whose faction overlaps it. Only q matches; a comma-split
    // projection (the pre-fix projectField) would also drag in r ("Red").
    const spec: ViewSpec = {
      kind: "lore",
      expr: { field: { key: "faction", op: "overlap", value: { field_of: { of: { hand_picked: ["q"] }, field: "faction" } } } },
    };
    expect(evaluateView(spec, rows, { schema: SC }).nodes.map((n) => n.id)).toEqual(["q"]);
  });
});

// #184 forward model: free variables (`{var}` / `$self`), a bindings environment,
// and `field_of` forward projection. A small ref-carrying roster: scenes point at
// characters via `pov`; a couple of tag-carrying nodes for value projection.
describe("parameterized views (#184: bindings, $self, field_of)", () => {
  const REFS: EvalNode[] = [
    { id: "s1", entry_type: "scene:scene", title: "Scene 1", metadata: { pov: "bob", status: "draft" } },
    { id: "s2", entry_type: "scene:scene", title: "Scene 2", metadata: { pov: "alice", status: "revised" } },
    { id: "s3", entry_type: "scene:scene", title: "Scene 3", metadata: { pov: "bob", status: "draft" } },
    { id: "bob", entry_type: "lore:character", title: "Bob", metadata: { tags: ["hero"] } },
    { id: "alice", entry_type: "lore:character", title: "Alice", metadata: { tags: ["hero", "villain"] } },
  ];
  const evalIds = (spec: ViewSpec, ctx: Parameters<typeof evaluateView>[2]) =>
    evaluateView(spec, REFS, ctx).nodes.map((n) => n.id);

  it("bound promoted formal: scenes whose pov ∈ {bob}", () => {
    const spec: ViewSpec = { kind: "scene", expr: { field: { key: "pov", op: "overlap", value: { var: "POV" } } } };
    expect(evalIds(spec, { bindings: { POV: new Set(["bob"]) } })).toEqual(["s1", "s3"]);
  });
  it("bound formal accepts a multi-pick set (pov ∈ {bob, alice})", () => {
    const spec: ViewSpec = { kind: "scene", expr: { field: { key: "pov", op: "overlap", value: { var: "POV" } } } };
    expect(evalIds(spec, { bindings: { POV: ["bob", "alice"] } })).toEqual(["s1", "s2", "s3"]);
  });
  it("UNBOUND formal ⇒ predicate inactive (whole input passes through)", () => {
    const spec: ViewSpec = { kind: "scene", expr: { field: { key: "pov", op: "overlap", value: { var: "POV" } } } };
    expect(evalIds(spec, {})).toEqual(["s1", "s2", "s3", "bob", "alice"]);
  });
  // #198: an unbound formal is "no constraint" and must show EVERYTHING in a drop
  // or complement too — not empty the list. Before the polarity fix the inactive
  // operand resolved to universe in every position, so `input − universe = ∅`.
  it("UNBOUND formal in a DROP (difference.remove) ⇒ removes nothing (#198)", () => {
    // "exclude scenes whose pov ∈ {param}", param unset → drop nothing → all scenes.
    const spec: ViewSpec = {
      kind: "scene",
      expr: { difference: { keep: { type: "scene:scene" }, remove: { field: { key: "pov", op: "overlap", value: { var: "POV" } } } } },
    };
    expect(evalIds(spec, {})).toEqual(["s1", "s2", "s3"]);
  });
  it("BOUND formal in a DROP still subtracts (drop is live once picked)", () => {
    const spec: ViewSpec = {
      kind: "scene",
      expr: { difference: { keep: { type: "scene:scene" }, remove: { field: { key: "pov", op: "overlap", value: { var: "POV" } } } } },
    };
    expect(evalIds(spec, { bindings: { POV: ["bob"] } })).toEqual(["s2"]);
  });
  it("UNBOUND formal in a COMPLEMENT ⇒ whole universe (#198)", () => {
    // Drop off `All` lowers to complement(p) (viewGraph differenceBuilt); unset
    // param → complement of ∅ → everything, not universe − universe = ∅.
    const spec: ViewSpec = { kind: "scene", expr: { complement: { field: { key: "pov", op: "overlap", value: { var: "POV" } } } } };
    expect(evalIds(spec, {})).toEqual(["s1", "s2", "s3", "bob", "alice"]);
  });
  it("BOUND formal in a COMPLEMENT excludes the matches", () => {
    const spec: ViewSpec = { kind: "scene", expr: { complement: { field: { key: "pov", op: "overlap", value: { var: "POV" } } } } };
    // pov ∈ {bob} matches s1,s3 → complement is everything else.
    expect(evalIds(spec, { bindings: { POV: ["bob"] } })).toEqual(["s2", "bob", "alice"]);
  });
  // #198 (review follow-up): an inactive predicate is the IDENTITY of its
  // IMMEDIATE combinator, not a sign propagated from the root. A global keep/drop
  // sign mishandled these nested cases.
  it("UNBOUND formal INSIDE an intersect that sits in a DROP ⇒ removes the intersect's OTHER constraint", () => {
    // "all scenes EXCEPT (draft AND pov∈{param})", param unset. The inactive pov
    // is the intersect's identity (universe), so remove = draft-scenes and the
    // result is all-scenes − draft-scenes. (A global sign gave ∅ → kept everything.)
    const spec: ViewSpec = {
      kind: "scene",
      expr: {
        difference: {
          keep: { type: "scene:scene" },
          remove: { intersect: [{ field: { key: "status", op: "overlap", value: "draft" } }, { field: { key: "pov", op: "overlap", value: { var: "POV" } } }] },
        },
      },
    };
    expect(evalIds(spec, {})).toEqual(["s2"]); // s1,s3 are draft → removed; s2 (revised) stays
  });
  it("UNBOUND formal in a UNION ⇒ drops out (∪ identity ∅), not blows up to the universe", () => {
    // "scenes that are revised OR pov∈{param}", param unset → just the revised set,
    // NOT every scene. (A global keep sign gave universe → union absorbed to all.)
    const spec: ViewSpec = {
      kind: "scene",
      expr: { union: [{ field: { key: "status", op: "overlap", value: "revised" } }, { field: { key: "pov", op: "overlap", value: { var: "POV" } } }] },
    };
    expect(evalIds(spec, {})).toEqual(["s2"]);
  });
  it("BOUND formal in that union still contributes its matches", () => {
    const spec: ViewSpec = {
      kind: "scene",
      expr: { union: [{ field: { key: "status", op: "overlap", value: "revised" } }, { field: { key: "pov", op: "overlap", value: { var: "POV" } } }] },
    };
    // Top-level union preserves OPERAND order (not roster order): revised {s2}
    // rows first, then pov∈{bob} {s1,s3}.
    expect(evalIds(spec, { bindings: { POV: ["bob"] } })).toEqual(["s2", "s1", "s3"]);
  });
  it("$self as a predicate operand: scenes where THIS character is pov", () => {
    const spec: ViewSpec = { kind: "scene", expr: { field: { key: "pov", op: "overlap", value: { var: "$self" } } } };
    expect(evalIds(spec, { bindings: { $self: ["bob"] } })).toEqual(["s1", "s3"]);
  });
  it("unresolved $self ⇒ empty set ⇒ no matches (not inactive)", () => {
    const spec: ViewSpec = { kind: "scene", expr: { field: { key: "pov", op: "overlap", value: { var: "$self" } } } };
    expect(evalIds(spec, {})).toEqual([]);
  });
  it("field_of on a reference field projects to a node-set (scenes → their povs)", () => {
    // field_of(scenes, pov) → the pov characters, deduped. Used standalone as
    // membership: the projected ids that exist in the roster (bob, alice).
    const spec: ViewSpec = { kind: "scene", expr: { field_of: { of: { type: "scene:scene" }, field: "pov" } } };
    expect(evalIds(spec, {}).sort()).toEqual(["alice", "bob"]);
  });
  it("field_of($self, pov) — the N=1 projection", () => {
    const spec: ViewSpec = { kind: "scene", expr: { field_of: { of: { var: "$self" }, field: "pov" } } };
    expect(evalIds(spec, { bindings: { $self: ["s2"] } })).toEqual(["alice"]);
  });
  it("field_of feeding a Filter operand: same-tag matching (value-set projection)", () => {
    // field_of(Alice, tags) → {hero, villain}; scenes… no, characters sharing a
    // tag with Alice. Project alice's tags, then keep characters overlapping them.
    const spec: ViewSpec = {
      kind: "lore",
      expr: {
        field: { key: "tags", op: "overlap", value: { field_of: { of: { hand_picked: ["alice"] }, field: "tags" } } },
      },
    };
    expect(evalIds(spec, {}).sort()).toEqual(["alice", "bob"]); // both carry "hero"
  });
  it("malformed {field_of} operand (no `of`) degrades to INACTIVE (no constraint), not a crash (#203)", () => {
    // A corrupt/hand-edited operand with no `of`. The designer never emits this,
    // but the evaluator must not throw. It resolves to INACTIVE (no constraint),
    // NOT the empty set — so at the membership root an overlap shows everything.
    const spec = { kind: "scene", expr: { field: { key: "pov", op: "overlap" as const, value: { field_of: { field: "pov" } } } } } as unknown as ViewSpec;
    expect(() => evalIds(spec, {})).not.toThrow();
    expect(evalIds(spec, {})).toEqual(["s1", "s2", "s3", "bob", "alice"]);
  });
  it("malformed {field_of} operand under DISJOINT does NOT match everything (#203 — the empty-set inversion trap)", () => {
    // The bug the empty-set degradation would cause: `disjoint ∅` is true for every
    // node. As INACTIVE it's no-constraint instead → in a drop it removes nothing.
    const spec = {
      kind: "scene",
      expr: { difference: { keep: { type: "scene:scene" }, remove: { field: { key: "pov", op: "disjoint", value: { field_of: { field: "pov" } } } } } },
    } as unknown as ViewSpec;
    expect(evalIds(spec, {})).toEqual(["s1", "s2", "s3"]); // remove is inert → all scenes kept
  });
  it("malformed field_of in membership position (no `of`) is the empty set, not a crash (#203)", () => {
    const spec = { kind: "scene", expr: { field_of: { field: "pov" } } } as unknown as ViewSpec;
    expect(() => evalIds(spec, {})).not.toThrow();
    expect(evalIds(spec, {})).toEqual([]);
  });
  it("field_of on `references` uses the reverse index (Phase-2 wiring hook)", () => {
    // field_of($self, references) → the referrers of the anchored node, resolved
    // through ctx.referenceIndex. Here bob is referenced by s1 and s3.
    const spec: ViewSpec = { kind: "scene", expr: { field_of: { of: { var: "$self" }, field: "references" } } };
    const referenceIndex = new Map([["bob", new Set(["s1", "s3"])]]);
    expect(evalIds(spec, { bindings: { $self: ["bob"] }, referenceIndex }).sort()).toEqual(["s1", "s3"]);
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

  it("a tree matching only top-level nodes stays a tree (does not collapse to groups:null)", () => {
    // Regression (#181): a filtered tree whose matches are all top-level (empty
    // ancestry) has all-empty row paths. Collapsing that to `groups:null` (the
    // handle/flat rule) blanks `treeNodeIds` → the Draft tree hides real matches.
    // A set of top-level scenes is still a (single-level) tree of leaf nodes.
    const FLAT: StructureDocument = {
      root: sn("root", "manuscript:base", "Book", [
        sn("s1", "manuscript:scene", "Scene 1", [], ["pick"]),
        sn("s2", "manuscript:scene", "Scene 2", []),
        sn("s3", "manuscript:scene", "Scene 3", [], ["pick"]),
      ]),
    };
    const res = evaluateView(
      { kind: "manuscript", presentation: "tree", expr: { tagged: "pick" } },
      structureToEvalNodes(FLAT),
    );
    expect(res.groups).not.toBeNull();
    expect(shape(res.groups!)).toEqual(["Scene 1", "Scene 3"]);
    expect(treeNodeIds(res.groups)).toEqual(new Set(["s1", "s3"]));
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
