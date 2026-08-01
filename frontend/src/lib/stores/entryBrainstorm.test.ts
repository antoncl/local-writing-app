import { beforeEach, describe, expect, it } from "vitest";

import { entryBrainstorm } from "./entryBrainstorm.svelte";
import type { EntryPatch } from "@/lib/types";

// The cross-pane hand-off is the contract both ends of the entry-patch brainstorm
// rely on: the chat pane publishes a committed patch by node id, the entry pane
// reads it back by that same id. If the keying drifts, the commit runs, the AI
// bills, and the review flip silently never appears (ADR-0046 slice 2/3 review).
const patch = (body: string | null, fields: EntryPatch["fields"] = {}): EntryPatch => ({
  body,
  fields,
});

describe("entryBrainstorm cross-pane store", () => {
  beforeEach(() => {
    for (const id of ["a", "b", "missing"]) entryBrainstorm.clear(id);
  });

  it("round-trips a patch by entry id", () => {
    expect(entryBrainstorm.proposalFor("a")).toBeNull();
    const p = patch("revised body", { bio: "new bio" });
    entryBrainstorm.propose("a", p);
    expect(entryBrainstorm.proposalFor("a")).toEqual(p);
  });

  it("keys proposals per entry with no cross-talk", () => {
    entryBrainstorm.propose("a", patch("body A"));
    expect(entryBrainstorm.proposalFor("b")).toBeNull();
    entryBrainstorm.propose("b", patch("body B"));
    expect(entryBrainstorm.proposalFor("a")?.body).toBe("body A");
    expect(entryBrainstorm.proposalFor("b")?.body).toBe("body B");
  });

  it("a second proposal supersedes the first (re-finalise before review)", () => {
    entryBrainstorm.propose("a", patch("first"));
    entryBrainstorm.propose("a", patch("second"));
    expect(entryBrainstorm.proposalFor("a")?.body).toBe("second");
  });

  it("carries a fields-only patch (no body change)", () => {
    entryBrainstorm.propose("a", patch(null, { bio: "just the field" }));
    expect(entryBrainstorm.proposalFor("a")?.body).toBeNull();
    expect(entryBrainstorm.proposalFor("a")?.fields).toEqual({ bio: "just the field" });
  });

  it("clear drops the proposal so the review closes", () => {
    entryBrainstorm.propose("a", patch("body"));
    entryBrainstorm.clear("a");
    expect(entryBrainstorm.proposalFor("a")).toBeNull();
  });

  it("clear on an entry with no proposal is a safe no-op", () => {
    expect(() => entryBrainstorm.clear("missing")).not.toThrow();
    expect(entryBrainstorm.proposalFor("missing")).toBeNull();
  });

  it("hasProposalFor is the hand-off dot's truth — true iff a proposal is pending (#710)", () => {
    expect(entryBrainstorm.hasProposalFor("a")).toBe(false);
    entryBrainstorm.propose("a", patch("body"));
    expect(entryBrainstorm.hasProposalFor("a")).toBe(true);
    expect(entryBrainstorm.hasProposalFor("b")).toBe(false); // no cross-talk
    entryBrainstorm.clear("a");
    expect(entryBrainstorm.hasProposalFor("a")).toBe(false); // clears with the review
  });

  it("hasProposalFor stays true for a fields-only patch (structured-only review)", () => {
    // A structured-only commit still needs the dot — the review is on the rail.
    entryBrainstorm.propose("a", patch(null, { bio: "field only" }));
    expect(entryBrainstorm.hasProposalFor("a")).toBe(true);
  });
});
