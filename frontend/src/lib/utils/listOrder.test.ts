import { describe, expect, it } from "vitest";

import { moveBefore, reorderByPosition } from "@/lib/utils/listOrder";

describe("reorderByPosition", () => {
  // The removal-shift correction is the whole point (#698 review): without
  // `to > from ? to - 1 : to`, every downward drag lands one row past the
  // indicator. Pin both directions and both positions.
  it("downward drag, before: lands immediately before the target row", () => {
    expect(reorderByPosition(["a", "b", "c", "d", "e"], 0, 3, "before")).toEqual(["b", "c", "a", "d", "e"]);
  });

  it("downward drag, after: lands immediately after the target row", () => {
    expect(reorderByPosition(["a", "b", "c", "d", "e"], 0, 3, "after")).toEqual(["b", "c", "d", "a", "e"]);
  });

  it("upward drag, before: lands immediately before the target row", () => {
    expect(reorderByPosition(["a", "b", "c", "d"], 3, 1, "before")).toEqual(["a", "d", "b", "c"]);
  });

  it("upward drag, after: lands immediately after the target row", () => {
    expect(reorderByPosition(["a", "b", "c", "d"], 3, 1, "after")).toEqual(["a", "b", "d", "c"]);
  });

  it("is a no-op copy for out-of-range indices", () => {
    const input = ["a", "b"];
    expect(reorderByPosition(input, -1, 1, "before")).toEqual(["a", "b"]);
    expect(reorderByPosition(input, 0, 5, "before")).toEqual(["a", "b"]);
    expect(reorderByPosition(input, 0, 1, "before")).not.toBe(input);
  });
});

describe("moveBefore", () => {
  it("moves an item to just before a later target", () => {
    expect(moveBefore(["a", "b", "c", "d"], "a", "d")).toEqual(["b", "c", "a", "d"]);
  });

  it("moves an item to just before an earlier target", () => {
    expect(moveBefore(["a", "b", "c", "d"], "d", "b")).toEqual(["a", "d", "b", "c"]);
  });

  it("is a no-op when dropping an item on itself", () => {
    expect(moveBefore(["a", "b", "c"], "b", "b")).toEqual(["a", "b", "c"]);
  });

  it("is a no-op when either id is absent", () => {
    expect(moveBefore(["a", "b"], "z", "a")).toEqual(["a", "b"]);
    expect(moveBefore(["a", "b"], "a", "z")).toEqual(["a", "b"]);
  });

  it("returns a fresh array, never mutating the input", () => {
    const input = ["a", "b", "c"];
    const out = moveBefore(input, "a", "c");
    expect(out).not.toBe(input);
    expect(input).toEqual(["a", "b", "c"]);
  });
});
