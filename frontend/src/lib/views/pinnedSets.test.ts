import { describe, expect, it } from "vitest";
import type { MutationSetEntrySummary } from "@/lib/types";
import { pinnedSetsFor } from "./pinnedSets";

// A mutation-set roster summary. Array order IS the backend list order
// (title-sorted); the tests assert the filter preserves it.
function set(over: Partial<MutationSetEntrySummary>): MutationSetEntrySummary {
  return {
    id: "s",
    title: "Change",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "",
    row_count: 1,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

// Reverse index (targetId → referrer ids), the shape referenceIndexStore holds.
function reverse(pairs: Record<string, string[]>): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  for (const [target, referrers] of Object.entries(pairs)) map.set(target, new Set(referrers));
  return map;
}

describe("pinnedSetsFor (ADR-0055 §3)", () => {
  it("returns the sets pinned to the entity, in roster order", () => {
    const roster = [
      set({ id: "a", title: "Aardvark", target_entity: "mira" }),
      set({ id: "b", title: "Zebra", target_entity: "mira" }),
      set({ id: "reusable", target_entity: "" }),
    ];
    const index = reverse({ mira: ["a", "b"] });
    expect(pinnedSetsFor("mira", index, roster).map((s) => s.id)).toEqual(["a", "b"]);
  });

  it("drops a referrer that is not a mutation set (not in the roster)", () => {
    // A chat's `subject` also points at the entity; only roster members survive.
    const roster = [set({ id: "set-1", target_entity: "mira" })];
    const index = reverse({ mira: ["set-1", "chat-9", "another-entry"] });
    expect(pinnedSetsFor("mira", index, roster).map((s) => s.id)).toEqual(["set-1"]);
  });

  it("returns [] for an entity nothing is pinned to", () => {
    const roster = [set({ id: "set-1", target_entity: "bob" })];
    expect(pinnedSetsFor("mira", reverse({ bob: ["set-1"] }), roster)).toEqual([]);
  });

  it("returns [] for an empty entity id", () => {
    const roster = [set({ id: "set-1", target_entity: "mira" })];
    expect(pinnedSetsFor("", reverse({ "": ["set-1"] }), roster)).toEqual([]);
  });

  it("returns [] when the reverse index is unloaded", () => {
    expect(pinnedSetsFor("mira", null, [set({ id: "set-1", target_entity: "mira" })])).toEqual([]);
  });
});
