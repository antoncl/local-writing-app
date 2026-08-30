import { describe, expect, it } from "vitest";

import { setLevelField, toggleLevelOrder } from "./groupLevelEdits";
import type { ViewGroupByLevel } from "@/lib/types";

describe("setLevelField", () => {
  it("changes the target level's field", () => {
    const levels: ViewGroupByLevel[] = [{ field: "status" }];
    expect(setLevelField(levels, 0, "tags")).toEqual([{ field: "tags" }]);
  });

  it("drops show_empty on a field change (it declares that field's vocabulary, #374)", () => {
    const levels: ViewGroupByLevel[] = [{ field: "listed", show_empty: true }];
    expect(setLevelField(levels, 0, "tags")).toEqual([{ field: "tags" }]);
  });

  it("preserves order across a field change", () => {
    const levels: ViewGroupByLevel[] = [{ field: "listed", order: "label", show_empty: true }];
    expect(setLevelField(levels, 0, "tags")).toEqual([{ field: "tags", order: "label" }]);
  });

  it("re-selecting the SAME field is a no-op — show_empty survives (#1693)", () => {
    // #374's drop is for a REAL field change; picking the current field again
    // must not silently strip the flag (a non-change is not an edit).
    const levels: ViewGroupByLevel[] = [{ field: "listed", show_empty: true, order: "label" }];
    const result = setLevelField(levels, 0, "listed");
    expect(result[0]).toBe(levels[0]); // identity preserved, nothing dropped
  });

  it("leaves other levels and the input array untouched", () => {
    const levels: ViewGroupByLevel[] = [
      { field: "listed", show_empty: true },
      { field: "status" },
    ];
    const result = setLevelField(levels, 1, "tags");
    expect(result[0]).toBe(levels[0]); // untouched level keeps identity
    expect(result[1]).toEqual({ field: "tags" });
    expect(levels[1]).toEqual({ field: "status" }); // no mutation of input
  });
});

describe("toggleLevelOrder", () => {
  it("adds order:label when absent (first-seen -> alphabetical)", () => {
    const levels: ViewGroupByLevel[] = [{ field: "status" }];
    expect(toggleLevelOrder(levels, 0)).toEqual([{ field: "status", order: "label" }]);
  });

  it("removes order when present (alphabetical -> first-seen)", () => {
    const levels: ViewGroupByLevel[] = [{ field: "status", order: "label" }];
    expect(toggleLevelOrder(levels, 0)).toEqual([{ field: "status" }]);
  });

  it("preserves show_empty when toggling order (the #374 regression)", () => {
    // Turn A–Z on: show_empty must survive alongside the new order.
    const on: ViewGroupByLevel[] = [{ field: "listed", show_empty: true }];
    expect(toggleLevelOrder(on, 0)).toEqual([{ field: "listed", show_empty: true, order: "label" }]);
    // Turn A–Z back off: show_empty still survives.
    const off: ViewGroupByLevel[] = [{ field: "listed", show_empty: true, order: "label" }];
    expect(toggleLevelOrder(off, 0)).toEqual([{ field: "listed", show_empty: true }]);
  });

  it("does not mutate the input array or its levels", () => {
    const levels: ViewGroupByLevel[] = [{ field: "listed", show_empty: true }];
    toggleLevelOrder(levels, 0);
    expect(levels).toEqual([{ field: "listed", show_empty: true }]);
  });
});
