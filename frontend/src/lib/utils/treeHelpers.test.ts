import { describe, expect, it } from "vitest";
import { entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
import type { MetadataSchema } from "@/lib/types";

// The Lore "New entry" menu is built from entryTypeChoicesByKind: it must offer
// every concrete, non-deprecated lore type. This is the frontend half of the Note
// reinstatement (#963) — the backend un-deprecates lore:note, and this proves the
// menu then lists it (and still hides abstract parents + deprecated types).
const SCHEMA = {
  entry_types: {
    "lore:base": { name: "Entry", kind: "lore", abstract: true, fields: [] },
    "lore:note": { name: "Note", kind: "lore", parent: "lore:base", fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:retired": { name: "Retired", kind: "lore", parent: "lore:base", fields: [], deprecated: true },
    "manuscript:scene": { name: "Scene", kind: "manuscript", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

describe("entryTypeChoicesByKind (#963)", () => {
  it("offers Note among the concrete lore types, sorted by name", () => {
    const choices = entryTypeChoicesByKind(SCHEMA, "lore");
    expect(choices.map((c) => c.name)).toEqual(["Character", "Note"]);
    expect(choices.map((c) => c.id)).toContain("lore:note");
  });

  it("hides abstract parents and deprecated types", () => {
    const ids = entryTypeChoicesByKind(SCHEMA, "lore").map((c) => c.id);
    expect(ids).not.toContain("lore:base"); // abstract
    expect(ids).not.toContain("lore:retired"); // deprecated
  });

  it("filters by kind and tolerates a null schema", () => {
    expect(entryTypeChoicesByKind(SCHEMA, "lore").every((c) => c.id.startsWith("lore:"))).toBe(true);
    expect(entryTypeChoicesByKind(null, "lore")).toEqual([]);
  });
});
