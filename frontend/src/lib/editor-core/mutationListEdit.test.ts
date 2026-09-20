// Pure unit tests for collection-mutation list-edit arithmetic (#71, ADR-0017).
import { describe, expect, it } from "vitest";
import { asMembershipList } from "./mutationListEdit";

describe("asMembershipList", () => {
  it("coerces a plain id array, comma-joined string, or empty/absent value", () => {
    expect(asMembershipList(["a", "b", "a"])).toEqual(["a", "b"]);
    expect(asMembershipList("a, b")).toEqual(["a", "b"]);
    expect(asMembershipList(undefined)).toEqual([]);
  });

  it("drops a non-primitive item instead of stringifying it into '[object Object]' (ADR-0089 §3: a list field's effective value may fold to member-map items)", () => {
    expect(asMembershipList([{ a: 1 }, "x"])).toEqual(["x"]);
  });
});
