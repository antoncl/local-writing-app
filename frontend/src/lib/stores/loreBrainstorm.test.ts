import { beforeEach, describe, expect, it } from "vitest";

import { loreBrainstorm } from "./loreBrainstorm.svelte";

// The cross-pane hand-off is the contract both ends of the lore brainstorm rely
// on: the chat pane publishes a committed body by entry id, the entry pane reads
// it back by that same id (scene.id). If the keying drifts, the commit runs, the
// AI bills, and the review flip silently never appears (ADR-0046 slice 2 review).
describe("loreBrainstorm cross-pane store", () => {
  beforeEach(() => {
    for (const id of ["a", "b", "missing"]) loreBrainstorm.clear(id);
  });

  it("round-trips a proposal by entry id", () => {
    expect(loreBrainstorm.proposalFor("a")).toBeNull();
    loreBrainstorm.propose("a", "revised body");
    expect(loreBrainstorm.proposalFor("a")).toBe("revised body");
  });

  it("keys proposals per entry with no cross-talk", () => {
    loreBrainstorm.propose("a", "body A");
    expect(loreBrainstorm.proposalFor("b")).toBeNull();
    loreBrainstorm.propose("b", "body B");
    expect(loreBrainstorm.proposalFor("a")).toBe("body A");
    expect(loreBrainstorm.proposalFor("b")).toBe("body B");
  });

  it("a second proposal supersedes the first (re-finalise before review)", () => {
    loreBrainstorm.propose("a", "first");
    loreBrainstorm.propose("a", "second");
    expect(loreBrainstorm.proposalFor("a")).toBe("second");
  });

  it("clear drops the proposal so the review closes", () => {
    loreBrainstorm.propose("a", "body");
    loreBrainstorm.clear("a");
    expect(loreBrainstorm.proposalFor("a")).toBeNull();
  });

  it("clear on an entry with no proposal is a safe no-op", () => {
    expect(() => loreBrainstorm.clear("missing")).not.toThrow();
    expect(loreBrainstorm.proposalFor("missing")).toBeNull();
  });
});
