import { describe, expect, it } from "vitest";
import { characterCostRows, rollupCostFor } from "./characterCost";
import type { EditableDocument, LoreEntrySummary } from "@/lib/types";

const lore = (over: Partial<LoreEntrySummary>) => over as LoreEntrySummary;

describe("characterCostRows", () => {
  it("drops non-positive costs, resolves titles, and sorts most-expensive first", () => {
    const rows = characterCostRows(
      { a: 0.5, b: 2, c: 0, d: -1 },
      [lore({ id: "a", title: "Anni" }), lore({ id: "b", title: "Bob" })],
      null,
    );
    expect(rows.map((r) => r.id)).toEqual(["b", "a"]); // c/d filtered, sorted by cost desc
    expect(rows[0]).toMatchObject({ id: "b", title: "Bob", cost: 2 });
    expect(rows[1].title).toBe("Anni");
  });

  it("falls back to the id as title and a deterministic colour when unmatched", () => {
    const first = characterCostRows({ x: 1 }, [], null);
    const second = characterCostRows({ x: 1 }, [], null);
    expect(first[0].title).toBe("x");
    expect(first[0].color).toMatch(/^hsl\(/);
    expect(first[0].color).toBe(second[0].color); // deterministic for the same id
  });
});

describe("rollupCostFor", () => {
  const doc = (computed: Record<string, unknown>) =>
    ({ computed_metadata: computed }) as unknown as EditableDocument;

  it("returns a character rollup only for a lore doc with a positive character_cost", () => {
    expect(rollupCostFor(doc({ character_cost: 3 }), "lore")).toEqual({ kind: "character", value: 3 });
    expect(rollupCostFor(doc({ character_cost: 0 }), "lore")).toBeNull();
    expect(rollupCostFor(doc({ character_cost: 3 }), "project")).toBeNull();
  });

  it("returns a project rollup only for a project doc with a positive project_cost", () => {
    expect(rollupCostFor(doc({ project_cost: 9 }), "project")).toEqual({ kind: "project", value: 9 });
    expect(rollupCostFor(doc({ project_cost: 9 }), "lore")).toBeNull();
  });

  it("returns null with no scene", () => {
    expect(rollupCostFor(null, "lore")).toBeNull();
  });
});
