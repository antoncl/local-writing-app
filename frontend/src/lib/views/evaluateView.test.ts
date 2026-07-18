import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewExpr, ViewSort, ViewSpec } from "@/lib/types";
import {
  defaultView,
  evaluateView,
  isBareDescendantsOf,
  nestWarnings,
  type EvalNode,
  type ViewGroup,
} from "@/lib/views/evaluateView";

// A tiny lore-like roster. Order is load-bearing (manual sort == input order).
const NODES: EvalNode[] = [
  { id: "a", entry_type: "lore:character", title: "Zed", metadata: { tags: ["hero"], pov: "honor" } },
  { id: "b", entry_type: "lore:character", title: "Alice", metadata: { tags: "villain, gotham" } },
  { id: "c", entry_type: "lore:deity", title: "Mara", metadata: { tags: ["gotham"], power: 9 } },
  { id: "d", entry_type: "lore:location", title: "Kitchen", metadata: { locations: ["kitchen", "hall"] } },
  { id: "e", entry_type: "lore:demigod", title: "Cass", metadata: { power: 3 } },
];

// Schema with a `parent:` chain rooted at the abstract `lore:base` (mirrors the
// real default schema): character / deity / location hang off the base; demigod
// → deity. So `descendants_of: "lore:base"` selects the whole roster — the
// explicit "everything" the default view lowers to post-ADR-0036.
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:deity": { name: "Deity", kind: "lore", parent: "lore:base", fields: [] },
    "lore:demigod": { name: "Demigod", kind: "lore", parent: "lore:deity", fields: [] },
    "lore:location": { name: "Location", kind: "lore", parent: "lore:base", fields: [] },
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

// The explicit "whole roster" expr — what the default view lowers to (ADR-0036).
const ALL: ViewSpec["expr"] = { descendants_of: "lore:base" };

describe("group_by A–Z: reference bucket colliding with a bare member (#A2)", () => {
  const refSchema = {
    version: 1,
    entry_types: {
      "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
      "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
      "lore:location": { name: "Location", kind: "lore", parent: "lore:base", fields: [] },
    },
    fields: {
      title: { name: "Title", type: "text", category: "intrinsic" },
      entry_type: { name: "Type", type: "text", category: "intrinsic" },
      located_in: { name: "Located in", type: "entity_ref" },
    },
  } as unknown as MetadataSchema;
  // Referencing nodes come BEFORE their targets, so node:paris / node:marseille
  // are stored as label buckets; paris/marseille (no located_in) then collide as
  // bare members on the same `node:<id>` key.
  const nodes: EvalNode[] = [
    { id: "amelie", entry_type: "lore:character", title: "Amelie", metadata: { located_in: "paris" } },
    { id: "zed", entry_type: "lore:character", title: "Zed", metadata: { located_in: "marseille" } },
    { id: "cass", entry_type: "lore:character", title: "Cass", metadata: {} }, // pure bare member
    { id: "paris", entry_type: "lore:location", title: "Paris", metadata: {} },
    { id: "marseille", entry_type: "lore:location", title: "Marseille", metadata: {} },
  ];
  it("colliding reference buckets ALPHABETIZE; only pure bare members sink", () => {
    const r = evaluateView(
      { kind: "lore", expr: ALL, group_by: [{ field: "located_in", order: "label" }] } as ViewSpec,
      nodes,
      { schema: refSchema },
    );
    // Marseille, Paris (real-node buckets sorted A–Z) — NOT sunk because they
    // collide with a bare member — then Cass (a genuine bare member) last.
    expect((r.groups ?? []).map((g) => g.label)).toEqual(["Marseille", "Paris", "Cass"]);
  });
});

describe("multi-level sort (#230)", () => {
  const roster: EvalNode[] = [
    { id: "1", entry_type: "lore:character", title: "Bob", metadata: { team: "red" } },
    { id: "2", entry_type: "lore:character", title: "Alice", metadata: { team: "red" } },
    { id: "3", entry_type: "lore:character", title: "Dave", metadata: { team: "blue" } },
    { id: "4", entry_type: "lore:character", title: "Carol", metadata: {} }, // no team → last
  ];
  const run = (sort: ViewSort): string[] =>
    evaluateView({ kind: "lore", expr: ALL, sort } as ViewSpec, roster, { schema: SCHEMA }).nodes.map((n) => n.id);

  it("sorts by A, then breaks ties by B", () => {
    // team asc (blue<red), tie → title asc; empty team sorts last regardless.
    const order = run({ by: "field", field_key: "team", dir: "asc", then: { by: "title", dir: "asc" } });
    expect(order).toEqual(["3", "2", "1", "4"]); // Dave(blue), Alice/Bob(red asc), Carol(empty)
  });
  it("the single-key form is unchanged (no `then`)", () => {
    expect(run({ by: "title", dir: "asc" })).toEqual(["2", "1", "4", "3"]); // Alice, Bob, Carol, Dave
  });
  it("a `manual` key TERMINATES the chain — later keys don't re-sort", () => {
    // {by:manual, then:title} must keep INPUT order, not title-sort (else a pane
    // offering manual drag would actually render title-ordered — a broken drag).
    expect(run({ by: "manual", then: { by: "title", dir: "asc" } })).toEqual(["1", "2", "3", "4"]);
  });
  it("a cyclic `then` chain does not hang (cycle guard)", () => {
    const cyclic: ViewSort = { by: "title", dir: "asc" };
    (cyclic as { then?: ViewSort }).then = cyclic; // self-reference (malformed spec)
    expect(run(cyclic)).toEqual(["2", "1", "4", "3"]); // terminates, sorts by title once
  });
  it("a full tie across all keys keeps input order (stable)", () => {
    // Everyone ties on team=... no: give a constant key, tiebreak absent → input order.
    const tie = [
      { id: "x", entry_type: "lore:character", title: "Z", metadata: { team: "red" } },
      { id: "y", entry_type: "lore:character", title: "Z", metadata: { team: "red" } },
    ];
    const order = evaluateView({ kind: "lore", expr: ALL, sort: { by: "field", field_key: "team" } } as ViewSpec, tie, {
      schema: SCHEMA,
    }).nodes.map((n) => n.id);
    expect(order).toEqual(["x", "y"]);
  });
});

describe("sort excludes unorderable fields (#237)", () => {
  // A schema declaring a set-valued field: sorting on it has no natural order, so
  // the comparator must NOT collapse the array to a stringly-coerced key.
  const tagSchema = {
    version: 1,
    entry_types: { "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] } },
    fields: {
      title: { name: "Title", type: "text", category: "intrinsic" },
      factions: { name: "Factions", type: "tags", category: "stored" },
      accent: { name: "Accent", type: "color", category: "stored" },
      rank: { name: "Rank", type: "number", category: "stored" },
    },
  } as unknown as MetadataSchema;
  // Authored (input) order is z, a, m; tag arrays are deliberately anti-sorted so
  // any accidental first-token/joined-string order would visibly reorder them.
  // `accent` is a SCALAR swatch string (not an array), so only the schema-type
  // sub-guard — not the Array.isArray backstop — can no-op a sort on it.
  const roster: EvalNode[] = [
    { id: "z", entry_type: "lore:base", title: "Zed", metadata: { factions: ["beta", "alpha"], accent: "rust", rank: 3 } },
    { id: "a", entry_type: "lore:base", title: "Ann", metadata: { factions: ["alpha"], accent: "azure", rank: 1 } },
    { id: "m", entry_type: "lore:base", title: "Mia", metadata: { factions: ["gamma"], accent: "moss", rank: 2 } },
  ];
  const run = (sort: ViewSort, nodes = roster): string[] =>
    evaluateView({ kind: "lore", expr: { descendants_of: "lore:base" }, sort } as ViewSpec, nodes, { schema: tagSchema }).nodes.map(
      (n) => n.id,
    );

  it("sorting by a tags field is a no-op — input order is preserved, not array-coerced", () => {
    expect(run({ by: "field", field_key: "factions", dir: "asc" })).toEqual(["z", "a", "m"]);
  });
  it("sorting by a scalar-but-orderless field (color) is a no-op via the schema-type guard", () => {
    // accent is a plain string ("rust"/"azure"/"moss"), so the Array.isArray
    // backstop never fires — only the schema-type sub-guard no-ops it. Without
    // that sub-guard the swatches would localeCompare to azure<moss<rust = a,m,z.
    expect(run({ by: "field", field_key: "accent", dir: "asc" })).toEqual(["z", "a", "m"]);
  });
  it("an unorderable key defers to the next key in a multi-level chain", () => {
    // factions is inert → rank asc decides: a(1), m(2), z(3).
    expect(run({ by: "field", field_key: "factions", dir: "asc", then: { by: "field", field_key: "rank", dir: "asc" } })).toEqual([
      "a",
      "m",
      "z",
    ]);
  });
  it("the array backstop no-ops even when the field's type is unknown", () => {
    // `factions` carries no field def here (mirrors the schema-less first render,
    // where the type isn't resolved yet) — a raw array value still must not be
    // collapsed; the array-shape check backstops the missing type.
    const noTypeSchema = {
      version: 1,
      entry_types: { "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] } },
      fields: { title: { name: "Title", type: "text", category: "intrinsic" } },
    } as unknown as MetadataSchema;
    const order = evaluateView(
      { kind: "lore", expr: { descendants_of: "lore:base" }, sort: { by: "field", field_key: "factions" } } as ViewSpec,
      roster,
      { schema: noTypeSchema },
    ).nodes.map((n) => n.id);
    expect(order).toEqual(["z", "a", "m"]);
  });
  it("an orderable field is unaffected — the guard does not over-fire", () => {
    expect(run({ by: "field", field_key: "rank", dir: "asc" })).toEqual(["a", "m", "z"]);
  });
});

describe("scalar collation is type-driven (#237): text lexicographic, number numeric", () => {
  const schema = {
    version: 1,
    entry_types: { "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] } },
    fields: {
      title: { name: "Title", type: "text", category: "intrinsic" },
      code: { name: "Code", type: "text", category: "stored" }, // numeric-LOOKING text
      seq: { name: "Seq", type: "number", category: "stored" },
    },
  } as unknown as MetadataSchema;
  // Titles + a text `code` field both hold values that look numeric; only the
  // real number field `seq` should order numerically.
  const roster: EvalNode[] = [
    { id: "n2", entry_type: "lore:base", title: "2", metadata: { code: "2", seq: 2 } },
    { id: "n10", entry_type: "lore:base", title: "10", metadata: { code: "10", seq: 10 } },
    { id: "n1", entry_type: "lore:base", title: "1", metadata: { code: "1", seq: 1 } },
  ];
  const run = (sort: ViewSort): string[] =>
    evaluateView({ kind: "lore", expr: { descendants_of: "lore:base" }, sort } as ViewSpec, roster, { schema }).nodes.map((n) => n.id);

  it("a TEXT field sorts lexicographically even when the values look numeric (1, 10, 2)", () => {
    expect(run({ by: "field", field_key: "code", dir: "asc" })).toEqual(["n1", "n10", "n2"]);
  });
  it("the intrinsic title (a text field) sorts lexicographically via the field path", () => {
    expect(run({ by: "field", field_key: "title", dir: "asc" })).toEqual(["n1", "n10", "n2"]);
  });
  it("the legacy by:\"title\" fast-path agrees — also lexicographic", () => {
    expect(run({ by: "title", dir: "asc" })).toEqual(["n1", "n10", "n2"]);
  });
  it("a real NUMBER field sorts numerically (1, 2, 10)", () => {
    expect(run({ by: "field", field_key: "seq", dir: "asc" })).toEqual(["n1", "n2", "n10"]);
  });
});

describe("isBareDescendantsOf (dense-null tolerant whole-roster detection)", () => {
  it("accepts a sparse whole-roster expr", () => {
    expect(isBareDescendantsOf({ descendants_of: "lore:base" })).toBe(true);
  });
  it("accepts the backend's dense-null dump (every other slot present as null)", () => {
    // Regression: a round-tripped spec has ~14 keys, all null but descendants_of.
    // A key-count check (`Object.keys(...).length === 1`) misfired here, silently
    // disabling drag-reorder on saved/duplicated whole-roster views.
    // Slots typed `ViewExpr[] | undefined` arrive as `null` at runtime, so the
    // literal is cast through `unknown` — that asymmetry is exactly what the
    // `== null` checks (not key counting) exist to absorb.
    expect(
      isBareDescendantsOf({
        descendants_of: "lore:base",
        union: null,
        intersect: null,
        difference: null,
        complement: null,
        annotate: null,
        type: null,
        tagged: null,
        field: null,
        hand_picked: null,
        field_of: null,
        var: null,
      } as unknown as ViewExpr),
    ).toBe(true);
  });
  it("rejects an expr with another primary slot set (a filtered roster)", () => {
    expect(isBareDescendantsOf({ descendants_of: "lore:base", tagged: "hero" })).toBe(false);
  });
  it("rejects an expr with no descendants_of", () => {
    expect(isBareDescendantsOf({ tagged: "hero" })).toBe(false);
  });
});

describe("default view", () => {
  it("is the explicit whole-kind roster (descendants_of the kind root) plus the kind's honest shape (ADR-0037 §7)", () => {
    expect(defaultView("lore", SCHEMA)).toEqual({
      kind: "lore",
      expr: { descendants_of: "lore:base" },
      sort: { by: "manual" },
      group_by: [{ field: "entry_type", order: "label" }],
    });
    expect(ids(defaultView("lore", SCHEMA))).toEqual(["a", "b", "c", "d", "e"]);
  });
  it("an absent/null expr evaluates to the empty set — not the universe (ADR-0036)", () => {
    expect(ids({ kind: "lore" })).toEqual([]);
    expect(ids({ kind: "lore", expr: null })).toEqual([]);
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
      { kind: "lore", expr: ALL, sort: { by: "field", field_key: "title", dir: "asc" } },
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

// Filter is a first-class derived operator (ADR-0041 §C): the evaluator carries
// no bespoke Filter branch — it desugars to the declared lowering
// (keep ≝ intersect(of, pred), drop ≝ difference(of, pred)) at entry. These lock
// the semantic equivalence ADR-0041 §G requires: a stored `{filter}` yields the
// same set as the hand-written intersect/difference it replaces — at the source
// position (evalSource), buried in the set algebra (evalExpr), and over a
// row-producer (the row-preserving σ branch of evalSource, ADR-0037 §5).
describe("filter (first-class derived operator, ADR-0041 §C)", () => {
  const OF: ViewExpr = { type: "lore:character" }; // a, b
  const PRED: ViewExpr = { tagged: "gotham" }; // b, c
  it("keep ≡ intersect(of, pred), at the source position", () => {
    expect(ids({ kind: "lore", expr: { filter: { of: OF, pred: PRED } } })).toEqual(["b"]);
    expect(ids({ kind: "lore", expr: { intersect: [OF, PRED] } })).toEqual(["b"]);
  });
  it("drop ≡ difference(keep: of, remove: pred)", () => {
    expect(ids({ kind: "lore", expr: { filter: { of: OF, pred: PRED, mode: "drop" } } })).toEqual(["a"]);
    expect(ids({ kind: "lore", expr: { difference: { keep: OF, remove: PRED } } })).toEqual(["a"]);
  });
  it("lowers when buried inside the set algebra (evalExpr path)", () => {
    const buried: ViewExpr = { intersect: [{ descendants_of: "lore:base" }, { filter: { of: OF, pred: PRED } }] };
    expect(ids({ kind: "lore", expr: buried })).toEqual(["b"]);
  });
  it("over a row-producer, rows survive the σ (evalSource row-preserving path)", () => {
    // `of` is a union (a row-producer): the lowered intersect goes through the
    // row-preserving branch, narrowing rows by the predicate rather than flattening.
    expect(ids({ kind: "lore", expr: { filter: { of: { union: [OF] }, pred: PRED } } })).toEqual(["b"]);
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

// ADR-0038 §C Amendment 1 (#222): the type / descendants_of / tagged leaves now
// carry a promoted `{var}` alongside the string literal, resolving from bindings
// exactly like a field predicate value. A literal degenerates to a one-element
// set (behaviour-preserving); an unbound formal is inactive (no constraint).
describe("promoted leaf slots resolve from bindings (ADR-0038 §C, #222)", () => {
  const leafIds = (expr: ViewExpr, bindings?: Record<string, string[] | Set<string>>) =>
    evaluateView({ kind: "lore", expr } as ViewSpec, NODES, { schema: SCHEMA, bindings }).nodes.map((n) => n.id);

  it("a literal type leaf is unchanged (behaviour-preserving)", () => {
    expect(leafIds({ type: "lore:character" })).toEqual(["a", "b"]);
  });
  it("a bound type leaf matches the bound entry_type", () => {
    expect(leafIds({ type: { var: "T" } }, { T: ["lore:deity"] })).toEqual(["c"]);
  });
  it("a bound type leaf matches ANY of a multi-value binding", () => {
    expect(leafIds({ type: { var: "T" } }, { T: ["lore:deity", "lore:location"] })).toEqual(["c", "d"]);
  });
  it("a bound descendants_of leaf includes the subtype family", () => {
    // lore:deity + its lore:demigod descendant.
    expect(leafIds({ descendants_of: { var: "T" } }, { T: ["lore:deity"] })).toEqual(["c", "e"]);
  });
  it("a bound tagged leaf matches nodes carrying the tag (array + CSV)", () => {
    expect(leafIds({ tagged: { var: "TAG" } }, { TAG: ["gotham"] })).toEqual(["b", "c"]);
  });
  it("an UNBOUND type leaf is inactive — shows everything at top level (#198)", () => {
    expect(leafIds({ type: { var: "T" } })).toEqual(["a", "b", "c", "d", "e"]);
  });
  it("an UNBOUND type leaf in a DROP removes nothing (#198 polarity)", () => {
    expect(leafIds({ difference: { keep: { descendants_of: "lore:base" }, remove: { type: { var: "T" } } } })).toEqual([
      "a",
      "b",
      "c",
      "d",
      "e",
    ]);
  });
  it("a BOUND type leaf in a DROP subtracts its matches", () => {
    expect(
      leafIds({ difference: { keep: { descendants_of: "lore:base" }, remove: { type: { var: "T" } } } }, { T: ["lore:character"] }),
    ).toEqual(["c", "d", "e"]);
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

  it("a group with no expr is empty — not the universe (ADR-0036)", () => {
    const spec: ViewSpec = {
      kind: "lore",
      groups: [
        { name: "Everything", expr: ALL },
        { name: "Unspecified", expr: null }, // no members → pruned from the output
        { name: "Deities", expr: { descendants_of: "lore:deity" } },
      ],
    };
    const res = evaluateView(spec, NODES, { schema: SCHEMA });
    // The null-expr group contributes nothing and (being empty) drops out.
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
    expect(ids({ kind: "lore", expr: ALL, sort: { by: "manual" } })).toEqual(["a", "b", "c", "d", "e"]);
  });
  it("by title asc/desc", () => {
    expect(ids({ kind: "lore", expr: ALL, sort: { by: "title", dir: "asc" } })).toEqual(["b", "e", "d", "c", "a"]);
    expect(ids({ kind: "lore", expr: ALL, sort: { by: "title", dir: "desc" } })).toEqual(["a", "c", "d", "e", "b"]);
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
    expect(ids({ kind: "lore", expr: ALL, sort: { by: "field", field_key: "power", dir: "desc" } })).toEqual([
      "c", "e", "a", "b", "d",
    ]);
  });
});

// --- nest: relational denormalization from lore links (ADR-0028, #107) -----

// Compact a group tree (#181 tree-uniform): a container is `[label, children]`;
// a leaf is a childless group → its nodeId.
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

// --- nest: orphans as a routable second output (ADR-0028 Amendment 1, #260) ---

// The Aleph/Bet/Gimmel case from the ADR. Three acts, each with a chapter and a
// scene down a `parent` entity_ref chain. Only Bet is seeded into `parents`, so
// Bet's subtree is placed and EVERYTHING under Aleph and Gimmel — the acts, their
// chapters AND their scenes (6 nodes) — is unplaced: an orphan that OWNS a
// subtree, the case the retired `"keep"` scalar shredded into flat siblings.
const ABG: EvalNode[] = [
  { id: "aleph", entry_type: "lore:note", title: "Aleph", metadata: {} },
  { id: "aleph-ch", entry_type: "lore:note", title: "Aleph Ch", metadata: { parent: "aleph" } },
  { id: "aleph-s", entry_type: "lore:note", title: "Aleph S", metadata: { parent: "aleph-ch" } },
  { id: "bet", entry_type: "lore:note", title: "Bet", metadata: {} },
  { id: "bet-ch", entry_type: "lore:note", title: "Bet Ch", metadata: { parent: "bet" } },
  { id: "bet-s", entry_type: "lore:note", title: "Bet S", metadata: { parent: "bet-ch" } },
  { id: "gimmel", entry_type: "lore:note", title: "Gimmel", metadata: {} },
  { id: "gimmel-ch", entry_type: "lore:note", title: "Gimmel Ch", metadata: { parent: "gimmel" } },
  { id: "gimmel-s", entry_type: "lore:note", title: "Gimmel S", metadata: { parent: "gimmel-ch" } },
];
const ABG_MATCH = { field: "parent", direction: "child_to_parent" as const, by: "ref" as const };
// Seed ONLY Bet into parents; children = the whole universe (handle omitted). An
// `id` lets the Nest's orphan node-set be referenced by `{orphans_of: id}`.
const abgNest = (id?: string): ViewExpr => ({
  nest: { ...(id ? { id } : {}), parents: { hand_picked: ["bet"] }, match: ABG_MATCH, recursive: true },
});

describe("nest — orphans as a routable node-set (ADR-0028 Amendment 1)", () => {
  it("(a) unwired ⇒ drops the unplaced set and counts it (default preserved)", () => {
    const res = evaluateView({ kind: "lore", expr: abgNest() }, ABG);
    // Only Bet's subtree renders; Aleph and Gimmel (+ their subtrees) are gone.
    expect(nrows(res.groups)).toEqual([["Bet", [["Bet Ch", ["bet-s"]]]]]);
    expect(res.nodes.map((n) => n.id)).toEqual(["bet", "bet-ch", "bet-s"]);
    // 6 unplaced children: the two acts, their chapters, their scenes.
    expect(res.diagnostics?.orphansDropped).toBe(6);
  });

  it("(b) `orphans_of` unioned with the tree ⇒ orphans rejoin the root, not dropped", () => {
    // The orphan output is a plain node-set: union the Nest's tree with its
    // `{orphans_of}` and the 6 unplaced nodes sit beside it — the routed
    // equivalent of the retired keep, and NOT counted dropped.
    const res = evaluateView({ kind: "lore", expr: { union: [abgNest("n"), { orphans_of: "n" }] } }, ABG);
    expect(res.diagnostics?.orphansDropped).toBe(0);
    expect(nrows(res.groups)).toEqual([
      ["Bet", [["Bet Ch", ["bet-s"]]]],
      "aleph",
      "aleph-ch",
      "aleph-s",
      "gimmel",
      "gimmel-ch",
      "gimmel-s",
    ]);
    expect(new Set(res.nodes.map((n) => n.id)).size).toBe(9);
  });

  it("(c) `orphans_of` into a second Nest ⇒ the two acts' subtrees are rebuilt intact", () => {
    // The orphan node-set seeds a second Nest: parents = orphan roots (orphans ∩
    // parent-unset = Aleph, Gimmel — Bet is placed, so excluded), children = the
    // orphan set. Rebuilds both subtrees — the hierarchy the flat keep shredded.
    const rebuild: ViewExpr = {
      nest: {
        parents: { intersect: [{ orphans_of: "n" }, { field: { key: "parent", op: "unset" } }] },
        children: { orphans_of: "n" },
        match: ABG_MATCH,
        recursive: true,
      },
    };
    const res = evaluateView({ kind: "lore", expr: { union: [abgNest("n"), rebuild] } }, ABG);
    expect(res.diagnostics?.orphansDropped).toBe(0);
    expect(nrows(res.groups)).toEqual([
      ["Bet", [["Bet Ch", ["bet-s"]]]],
      ["Aleph", [["Aleph Ch", ["aleph-s"]]]],
      ["Gimmel", [["Gimmel Ch", ["gimmel-s"]]]],
    ]);
    expect(res.groups![1].nodeId).toBe("aleph"); // real-node header, not a synthetic bucket
    expect(res.groups![2].nodeId).toBe("gimmel");
  });

  it("two named groups: the tree in one, its orphan node-set in another (the Strip-acts shape)", () => {
    // The case that was broken: a two-output Nest → two groups. Both names appear;
    // the Nest is evaluated once (single-sink DAG) and referenced by both.
    const res = evaluateView(
      {
        kind: "lore",
        groups: [
          { name: "Placed", expr: abgNest("n") },
          { name: "Orphans", expr: { orphans_of: "n" } },
        ],
      },
      ABG,
    );
    expect(res.groups!.map((g) => g.label)).toEqual(["Placed", "Orphans"]);
    expect(nrows(res.groups)).toEqual([
      ["Placed", [["Bet", [["Bet Ch", ["bet-s"]]]]]],
      ["Orphans", ["aleph", "aleph-ch", "aleph-s", "gimmel", "gimmel-ch", "gimmel-s"]],
    ]);
    expect(res.diagnostics?.orphansDropped).toBe(0);
  });

  it("`orphans_of` participates in set algebra as a plain node-set", () => {
    // Intersect the orphan set with the roster → exactly the 6 unplaced nodes.
    const res = evaluateView(
      {
        kind: "lore",
        groups: [
          { name: "Tree", expr: abgNest("n") },
          { name: "Loose", expr: { intersect: [{ orphans_of: "n" }, { type: "lore:note" }] } },
        ],
      },
      ABG,
    );
    const loose = res.groups!.find((g) => g.label === "Loose")!;
    expect(new Set(loose.children.map((c) => c.nodeId))).toEqual(
      new Set(["aleph", "aleph-ch", "aleph-s", "gimmel", "gimmel-ch", "gimmel-s"]),
    );
  });

  it("an `orphans_of` naming no Nest resolves to the empty set (not a crash)", () => {
    const res = evaluateView({ kind: "lore", expr: { orphans_of: "missing" } }, ABG);
    expect(res.nodes).toEqual([]);
  });

  it("(#275) an orphans-only reference carries the Nest inline and resolves to the orphan set", () => {
    // No `{nest}` anywhere — the definition rides on the reference (`orphans_nest`),
    // so `collectNests` registers it and `{orphans_of}` resolves to the real set
    // instead of dangling to empty (the save→reload-with-results-unwired case).
    const op = abgNest("n").nest!;
    const res = evaluateView({ kind: "lore", expr: { orphans_of: "n", orphans_nest: op } }, ABG);
    expect(new Set(res.nodes.map((n) => n.id))).toEqual(
      new Set(["aleph", "aleph-ch", "aleph-s", "gimmel", "gimmel-ch", "gimmel-s"]),
    );
    expect(res.diagnostics?.orphansDropped).toBe(0);
  });

  // NOTE (#275): a cyclic `{orphans_of}` spec (a Nest referencing its own orphans,
  // or a mutual A↔B cycle) is no longer defended against in the evaluator. It
  // cannot reach here: the designer's `isValidConnection` rejects every such wiring
  // as a `meaningless-cycle` (see viewGraph.test.ts) and the load-time repair drops
  // any back-edge in a hand-edited/legacy graph before it lowers. The former
  // re-entrancy guard (`nestInProgress`) was redundant and has been removed.
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
