import { describe, expect, it } from "vitest";

import { moveBefore } from "@/lib/utils/listOrder";

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
