import { describe, expect, it } from "vitest";
import { scrubRefreshAction } from "./scrubRefreshAction";

describe("scrubRefreshAction (ADR-0095 §8 decision 1)", () => {
  it("a genuinely different entity (including null <-> id) resets to base: load", () => {
    expect(scrubRefreshAction(null, "e1")).toBe("load");
    expect(scrubRefreshAction("e1", "e2")).toBe("load");
    expect(scrubRefreshAction("e1", null)).toBe("load");
  });

  it("the SAME entity re-anchors in place: reload", () => {
    expect(scrubRefreshAction("e1", "e1")).toBe("reload");
  });

  it("no entity either side (never opened a lore card): none", () => {
    expect(scrubRefreshAction(null, null)).toBe("none");
  });
});
