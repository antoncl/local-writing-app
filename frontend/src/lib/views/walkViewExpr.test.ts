import { describe, it, expect } from "vitest";
import { walkViewExpr } from "./walkViewExpr";
import type { ViewExpr } from "@/lib/types";

// A leaf tagged by `hand_picked: [marker]` so we can assert which slots the walker
// descended into. Each slot below buries a uniquely-marked leaf; the walk must
// reach every one (the whole point of the single shared slot list, #275).
const leaf = (marker: string): ViewExpr => ({ hand_picked: [marker] });
const markersOf = (expr: ViewExpr): string[] => {
  const seen: string[] = [];
  walkViewExpr(expr, (e) => {
    if (e.hand_picked) seen.push(...e.hand_picked);
  });
  return seen.sort();
};

describe("walkViewExpr", () => {
  it("descends every sub-expr slot", () => {
    const expr: ViewExpr = {
      union: [
        { intersect: [leaf("intersect"), { complement: leaf("complement") }] },
        { difference: { keep: leaf("keep"), remove: leaf("remove") } },
        { nest: { parents: leaf("nest-parents"), children: leaf("nest-children"), match: { field: "p", direction: "child_to_parent", by: "ref" } } },
        { orphans_of: "n", orphans_nest: { parents: leaf("orphans-parents"), children: leaf("orphans-children"), match: { field: "p", direction: "child_to_parent", by: "ref" } } },
        { annotate: { color: "#111" }, of: leaf("annotate-of") },
        { field_of: { of: leaf("field_of-of"), field: "pov" } },
        { field: { key: "k", op: "overlap", value: { field_of: { of: leaf("field-value-projection"), field: "pov" } } } },
      ],
    };
    expect(markersOf(expr)).toEqual(
      [
        "annotate-of",
        "complement",
        "field-value-projection",
        "field_of-of",
        "intersect",
        "keep",
        "nest-children",
        "nest-parents",
        "orphans-children",
        "orphans-parents",
        "remove",
      ].sort(),
    );
  });

  it("is a no-op on null / undefined", () => {
    let calls = 0;
    walkViewExpr(null, () => calls++);
    walkViewExpr(undefined, () => calls++);
    expect(calls).toBe(0);
  });

  it("visits the root itself, pre-order", () => {
    const order: string[] = [];
    walkViewExpr({ union: [leaf("a"), leaf("b")] }, (e) => {
      order.push(e.union ? "root" : (e.hand_picked?.[0] ?? "?"));
    });
    expect(order).toEqual(["root", "a", "b"]);
  });
});
