import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewSpec } from "@/lib/types";
import { defaultView, evaluateView, type EvalNode } from "@/lib/views/evaluateView";

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
  fields: {},
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

describe("annotate", () => {
  const grouped: ViewSpec = {
    kind: "lore",
    expr: {
      union: [
        { annotate: { label: "Deities", rank: 2 }, of: { descendants_of: "lore:deity" } },
        { annotate: { label: "Cast", rank: 1 }, of: { type: "lore:character" } },
        // An unlabeled leaf: the location `d` is a member but carries no label,
        // so it must land in the trailing "everything else" bucket.
        { type: "lore:location" },
      ],
    },
  };

  it("labels build rank-ordered groups with an 'everything else' bucket", () => {
    const res = evaluateView(grouped, NODES, { schema: SCHEMA });
    // rank 1 before rank 2; unlabeled (location d) falls into the trailing bucket.
    expect(res.groups?.map((g) => [g.label, g.nodes.map((n) => n.id)])).toEqual([
      ["Cast", ["a", "b"]],
      ["Deities", ["c", "e"]],
      [null, ["d"]],
    ]);
  });

  it("color annotate stamps annotations without creating a group", () => {
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

  it("annotate is a pass-through: membership equals its input set", () => {
    expect(ids(grouped)).toEqual(["a", "b", "c", "d", "e"]);
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

  it("a cycle contributes nothing rather than looping", () => {
    const cyclic: Record<string, ViewSpec> = { self: { kind: "lore", expr: { view_ref: "self" } } };
    const res = evaluateView({ kind: "lore", expr: { view_ref: "self" } }, NODES, {
      schema: SCHEMA,
      resolveView: (id) => cyclic[id] ?? null,
    });
    expect(res.nodes).toEqual([]);
  });
});
