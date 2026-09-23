// ADR-0091 §2 — the pane's grouping and the diff-driven defaults, pinned
// against the ADR's own examples and exact sentences.
import { describe, expect, it } from "vitest";
import {
  defaultFolded,
  defaultKept,
  groupOf,
  groupedItems,
  nothingChanged,
  proseStartsKept,
  ruleLine,
} from "./candidateGroups";
import type { ChangeCandidate, ChangeCandidateSet } from "@/lib/propagationTypes";

function candidate(
  id: string,
  title: string,
  reasons: ChangeCandidate["reasons"],
  kind = "lore",
): ChangeCandidate {
  return { id, kind, entry_type: `${kind}:base`, title, tier: "mention", reasons };
}

function reason(
  route: ChangeCandidate["reasons"][number]["route"],
  overrides: Partial<ChangeCandidate["reasons"][number]> = {},
): ChangeCandidate["reasons"][number] {
  return { route, field_id: "", marker_id: "", field_changed: false, ...overrides };
}

function set(overrides: Partial<ChangeCandidateSet> = {}): ChangeCandidateSet {
  return {
    source_id: "lore_marek",
    baseline_snapshot_id: "",
    changed_fields: [],
    body_changed: false,
    whole_entry: false,
    items: [],
    ...overrides,
  };
}

describe("groupOf — declared, else markers, else mentions", () => {
  it("a reference route (either direction) is declared, even alongside other reasons", () => {
    const c = candidate("a", "A", [
      reason("mentions_source"),
      reason("mutates_source", { field_id: "rank" }),
      reason("referenced_by_source", { field_id: "posting" }),
    ]);
    expect(groupOf(c)).toBe("declared");
  });

  it("a marker route with no reference route is markers", () => {
    const c = candidate("a", "A", [reason("mentions_source"), reason("mutates_source", { field_id: "rank" })]);
    expect(groupOf(c)).toBe("markers");
  });

  it("only mention routes (either direction) is mentions", () => {
    expect(groupOf(candidate("a", "A", [reason("mentions_source")]))).toBe("mentions");
    expect(groupOf(candidate("a", "A", [reason("mentioned_by_source")]))).toBe("mentions");
  });
});

describe("groupedItems — sort order per group", () => {
  it("declared and mentions sort by title, casefold, then id", () => {
    const s = set({
      items: [
        candidate("z1", "banana", [reason("references_source", { field_id: "f" })]),
        candidate("a1", "Apple", [reason("references_source", { field_id: "f" })]),
        candidate("a2", "apple", [reason("references_source", { field_id: "f" })]),
      ],
    });
    expect(groupedItems(s).declared.map((c) => c.id)).toEqual(["a1", "a2", "z1"]);
  });

  it("a scene with a changed-field marker sorts before untouched-field markers, then by title", () => {
    const s = set({
      items: [
        candidate("untouched-z", "Zeta", [reason("mutates_source", { field_id: "whereabouts", field_changed: false })]),
        candidate("changed", "Alpha scene", [reason("mutates_source", { field_id: "rank", field_changed: true })]),
        candidate("untouched-a", "Alpha", [reason("mutates_source", { field_id: "whereabouts", field_changed: false })]),
      ],
      changed_fields: ["rank"],
    });
    expect(groupedItems(s).markers.map((c) => c.id)).toEqual(["changed", "untouched-a", "untouched-z"]);
  });
});

describe("proseStartsKept / nothingChanged", () => {
  it("body changed, or no baseline, reaches prose", () => {
    expect(proseStartsKept(set({ body_changed: true }))).toBe(true);
    expect(proseStartsKept(set({ whole_entry: true }))).toBe(true);
    expect(proseStartsKept(set({ changed_fields: ["rank"] }))).toBe(false);
  });

  it("a lane created since the baseline (layers[].whole) is a change, not nothing", () => {
    const s = set({ layers: [{ layer_id: "l1", layer_label: "Book", is_override: true, baseline_snapshot_id: "", changed_fields: [], whole: true }] });
    expect(nothingChanged(s)).toBe(false);
  });

  it("nothing changed only when no field, no body, not whole, and no whole lane", () => {
    expect(nothingChanged(set())).toBe(true);
    expect(nothingChanged(set({ changed_fields: ["rank"] }))).toBe(false);
    expect(nothingChanged(set({ body_changed: true }))).toBe(false);
    expect(nothingChanged(set({ whole_entry: true }))).toBe(false);
  });
});

describe("defaultKept / defaultFolded — the three states of §2", () => {
  it("fields changed, body unchanged — declared+markers kept, mentions folded", () => {
    const s = set({ changed_fields: ["rank"] });
    expect(defaultKept(s)).toEqual(["declared", "markers"]);
    expect(defaultFolded(s)).toEqual(["mentions"]);
  });

  it("body changed (with or without fields), or whole entry — everything kept, nothing folded", () => {
    for (const s of [set({ body_changed: true }), set({ body_changed: true, changed_fields: ["rank"] }), set({ whole_entry: true })]) {
      expect(defaultKept(s)).toEqual(["declared", "markers", "mentions"]);
      expect(defaultFolded(s)).toEqual([]);
    }
  });

  it("nothing changed — nothing kept, everything folded", () => {
    const s = set();
    expect(defaultKept(s)).toEqual([]);
    expect(defaultFolded(s)).toEqual(["declared", "markers", "mentions"]);
  });
});

describe("ruleLine — ADR-0091 §2's exact strings", () => {
  it("body only", () => {
    expect(ruleLine(set({ body_changed: true }))).toBe(
      "The body changed: entries it names and that name it start kept, with the declared rows and the markers.",
    );
  });

  it("body + fields, plural and singular", () => {
    expect(ruleLine(set({ body_changed: true, changed_fields: ["rank", "aliases"] }))).toBe(
      "The body and 2 fields changed (rank, aliases): everything listed starts kept.",
    );
    expect(ruleLine(set({ body_changed: true, changed_fields: ["rank"] }))).toBe(
      "The body and 1 field changed (rank): everything listed starts kept.",
    );
  });

  it("fields only, plural and singular", () => {
    expect(ruleLine(set({ changed_fields: ["rank", "aliases"] }))).toBe(
      "Fields changed (rank, aliases): declared rows and markers start kept; mentions are folded.",
    );
    expect(ruleLine(set({ changed_fields: ["rank"] }))).toBe(
      "A field changed (rank): declared rows and markers start kept; mentions are folded.",
    );
  });

  it("whole entry", () => {
    expect(ruleLine(set({ whole_entry: true }))).toBe(
      "No baseline: the whole entry counts as the change; everything listed starts kept.",
    );
  });

  it("nothing changed reads empty — the diff column's own sentence covers it", () => {
    expect(ruleLine(set())).toBe("");
  });

  it("more than three fields reads 'a, b, c and N more'", () => {
    expect(ruleLine(set({ changed_fields: ["a", "b", "c", "d", "e"] }))).toBe(
      "Fields changed (a, b, c and 2 more): declared rows and markers start kept; mentions are folded.",
    );
  });
});
