import { beforeEach, describe, expect, it } from "vitest";

import { loreBrainstorm } from "./loreBrainstorm.svelte";
import type { EntryPatch } from "@/lib/types";

// The cross-pane hand-off is the contract both ends of the lore brainstorm rely
// on: the chat pane publishes a committed patch by entry id, the entry pane reads
// it back by that same id (scene.id). If the keying drifts, the commit runs, the
// AI bills, and the review flip silently never appears (ADR-0046 slice 2/3 review).
const patch = (body: string | null, fields: EntryPatch["fields"] = {}): EntryPatch => ({
  body,
  fields,
});

describe("loreBrainstorm cross-pane store", () => {
  beforeEach(() => {
    for (const id of ["a", "b", "missing"]) loreBrainstorm.clear(id);
  });

  it("round-trips a patch by entry id", () => {
    expect(loreBrainstorm.proposalFor("a")).toBeNull();
    const p = patch("revised body", { bio: "new bio" });
    loreBrainstorm.propose("a", p);
    expect(loreBrainstorm.proposalFor("a")).toEqual(p);
  });

  it("keys proposals per entry with no cross-talk", () => {
    loreBrainstorm.propose("a", patch("body A"));
    expect(loreBrainstorm.proposalFor("b")).toBeNull();
    loreBrainstorm.propose("b", patch("body B"));
    expect(loreBrainstorm.proposalFor("a")?.body).toBe("body A");
    expect(loreBrainstorm.proposalFor("b")?.body).toBe("body B");
  });

  it("a second proposal supersedes the first (re-finalise before review)", () => {
    loreBrainstorm.propose("a", patch("first"));
    loreBrainstorm.propose("a", patch("second"));
    expect(loreBrainstorm.proposalFor("a")?.body).toBe("second");
  });

  it("carries a fields-only patch (no body change)", () => {
    loreBrainstorm.propose("a", patch(null, { bio: "just the field" }));
    expect(loreBrainstorm.proposalFor("a")?.body).toBeNull();
    expect(loreBrainstorm.proposalFor("a")?.fields).toEqual({ bio: "just the field" });
  });

  it("clear drops the proposal so the review closes", () => {
    loreBrainstorm.propose("a", patch("body"));
    loreBrainstorm.clear("a");
    expect(loreBrainstorm.proposalFor("a")).toBeNull();
  });

  it("clear on an entry with no proposal is a safe no-op", () => {
    expect(() => loreBrainstorm.clear("missing")).not.toThrow();
    expect(loreBrainstorm.proposalFor("missing")).toBeNull();
  });
});
