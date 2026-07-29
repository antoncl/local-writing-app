import { describe, expect, it } from "vitest";
import { moveAt, removeAt, updateAt } from "@/lib/utils/listEdits";

describe("updateAt", () => {
  it("merges the patch into item i, leaving siblings untouched", () => {
    const list = [{ k: "a", n: 1 }, { k: "b", n: 2 }, { k: "c", n: 3 }];
    const out = updateAt(list, 1, { n: 20 });
    expect(out).toEqual([{ k: "a", n: 1 }, { k: "b", n: 20 }, { k: "c", n: 3 }]);
  });

  it("does not mutate the input (returns a new array, new item)", () => {
    const list = [{ n: 1 }];
    const out = updateAt(list, 0, { n: 9 });
    expect(out).not.toBe(list);
    expect(out[0]).not.toBe(list[0]);
    expect(list[0].n).toBe(1);
  });

  it("is a no-op copy when i is out of range", () => {
    const list = [{ n: 1 }];
    expect(updateAt(list, 5, { n: 9 })).toEqual([{ n: 1 }]);
  });
});

describe("removeAt", () => {
  it("drops item i", () => {
    expect(removeAt(["a", "b", "c"], 1)).toEqual(["a", "c"]);
  });

  it("does not mutate the input", () => {
    const list = ["a", "b"];
    const out = removeAt(list, 0);
    expect(out).not.toBe(list);
    expect(list).toEqual(["a", "b"]);
  });

  it("is a no-op copy when i is out of range", () => {
    expect(removeAt(["a", "b"], 9)).toEqual(["a", "b"]);
  });
});

describe("moveAt", () => {
  it("swaps item i with i-1 (move up)", () => {
    expect(moveAt(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
  });

  it("swaps item i with i+1 (move down)", () => {
    expect(moveAt(["a", "b", "c"], 1, 1)).toEqual(["a", "c", "b"]);
  });

  it("returns null (no commit) at the top edge", () => {
    expect(moveAt(["a", "b"], 0, -1)).toBeNull();
  });

  it("returns null (no commit) at the bottom edge", () => {
    expect(moveAt(["a", "b"], 1, 1)).toBeNull();
  });

  it("returns null when i itself is out of range", () => {
    expect(moveAt(["a", "b"], -1, 1)).toBeNull();
    expect(moveAt(["a", "b"], 5, -1)).toBeNull();
  });

  it("does not mutate the input", () => {
    const list = ["a", "b", "c"];
    const out = moveAt(list, 0, 1);
    expect(out).toEqual(["b", "a", "c"]);
    expect(list).toEqual(["a", "b", "c"]);
  });
});
