import { describe, expect, it } from "vitest";
import type { ReferenceCandidate } from "@/lib/types";
import { candidatesToBacklinks } from "./backlinks";

function candidate(over: Partial<ReferenceCandidate>): ReferenceCandidate {
  return { id: "x", title: "X", kind: "lore", entry_type: "lore:character", summary: "", found: true, ...over };
}

describe("candidatesToBacklinks (#194 Phase 2c)", () => {
  it("maps candidates to any-field rows (empty field attribution)", () => {
    const [row] = candidatesToBacklinks([candidate({ id: "bob", title: "Bob", entry_type: "lore:character" })]);
    expect(row).toEqual({
      id: "bob",
      title: "Bob",
      kind: "lore",
      entry_type: "lore:character",
      field_id: "",
      field_name: "",
    });
  });

  it("sorts by kind then title (case-insensitive), like the retired endpoint", () => {
    const rows = candidatesToBacklinks([
      candidate({ id: "s1", title: "zed", kind: "scene" }),
      candidate({ id: "l2", title: "bob", kind: "lore" }),
      candidate({ id: "l1", title: "Alice", kind: "lore" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["l1", "l2", "s1"]);
  });

  it("returns an empty list for no candidates", () => {
    expect(candidatesToBacklinks([])).toEqual([]);
  });

  // #203: match the retired list_backlinks exclusions.
  it("drops the anchor's self-reference (a node is not its own backlink)", () => {
    const rows = candidatesToBacklinks(
      [candidate({ id: "self", title: "Me" }), candidate({ id: "bob", title: "Bob" })],
      "self",
    );
    expect(rows.map((r) => r.id)).toEqual(["bob"]);
  });

  it("drops found:false referrers (deleted during the stale-index window)", () => {
    const rows = candidatesToBacklinks([
      candidate({ id: "gone", title: "Ghost", found: false }),
      candidate({ id: "bob", title: "Bob" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["bob"]);
  });

  it("still includes the anchor's referrers when no anchorId is passed", () => {
    const rows = candidatesToBacklinks([candidate({ id: "bob", title: "Bob" })]);
    expect(rows.map((r) => r.id)).toEqual(["bob"]);
  });
});
