import { describe, expect, it } from "vitest";
import { isInactiveParamNode } from "./viewGraph";

// The designer's "inactive parameter" affordance decision (#198/#206). Backs the
// dashed tint + "inactive" chip in ViewFlowNode — a promoted formal with no
// default imposes no constraint ("unset = show everything", ADR-0031 §B), so the
// node is surfaced as inert rather than silently filtering. Split out of
// viewGraph.test.ts (which is at the file-size cap).
describe("isInactiveParamNode (#206 inactive-node affordance)", () => {
  const empty = { name: "P", default: null };
  const bound = { name: "P", default: ["draft"] };

  it("is inactive: promoted formal, empty default, value-less slot (type/descendants_of/tagged)", () => {
    expect(isInactiveParamNode(empty, "type", false)).toBe(true);
    expect(isInactiveParamNode(empty, "descendants_of", false)).toBe(true);
    expect(isInactiveParamNode(empty, "tagged", false)).toBe(true);
  });

  it("is inactive: field slot whose op takes a value (overlap/disjoint) with an empty default", () => {
    expect(isInactiveParamNode(empty, "field", true)).toBe(true);
  });

  it("is NOT inactive: a field slot with a set/unset op carries no operand", () => {
    // opNeedsValue=false → the predicate is a presence test, never inactive.
    expect(isInactiveParamNode(empty, "field", false)).toBe(false);
  });

  it("is NOT inactive: a bound default (empty-string / empty-array / null are the only 'empty')", () => {
    expect(isInactiveParamNode(bound, "field", true)).toBe(false);
    expect(isInactiveParamNode({ default: "x" }, "type", false)).toBe(false);
    // Empty string and empty array DO count as empty → inactive.
    expect(isInactiveParamNode({ default: "" }, "type", false)).toBe(true);
    expect(isInactiveParamNode({ default: [] }, "field", true)).toBe(true);
  });

  it("is NOT inactive: a node with no promoted formal at all", () => {
    expect(isInactiveParamNode(null, "field", true)).toBe(false);
    expect(isInactiveParamNode(undefined, "type", false)).toBe(false);
  });
});
