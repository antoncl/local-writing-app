import { describe, expect, it } from "vitest";
import type { MetadataSchema } from "@/lib/types";
import { kindEntryTypeFqns, kindEntryTypeOptions } from "@/lib/utils/schemaTypeHelpers";

// The entry_type roster shared by the view designer (ViewFlowNode pickers) and the
// runtime param strip (viewParams). `type` / `field → entry_type` want concrete
// types only; `descendants_of` wants abstract family roots too (#293/#295).
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true },
    "lore:character": { name: "Character", kind: "lore" },
    "lore:place": { name: "Place", kind: "lore" },
    "scene:scene": { name: "Scene", kind: "scene" },
  },
  fields: {},
} as unknown as MetadataSchema;

describe("kindEntryTypeOptions", () => {
  it("excludes abstract types by default and filters to the kind", () => {
    expect(kindEntryTypeOptions(SCHEMA, "lore")).toEqual([
      { fqn: "lore:character", name: "Character" },
      { fqn: "lore:place", name: "Place" },
    ]);
  });

  it("includes abstract family roots when asked (descendants_of)", () => {
    expect(kindEntryTypeOptions(SCHEMA, "lore", true)).toEqual([
      { fqn: "lore:base", name: "Lore" },
      { fqn: "lore:character", name: "Character" },
      { fqn: "lore:place", name: "Place" },
    ]);
  });

  it("is empty for an absent schema or a kind with no types", () => {
    expect(kindEntryTypeOptions(null, "lore")).toEqual([]);
    expect(kindEntryTypeOptions(SCHEMA, "prompt")).toEqual([]);
  });
});

describe("kindEntryTypeFqns (delegates to the concrete roster)", () => {
  it("returns concrete FQNs only", () => {
    expect(kindEntryTypeFqns(SCHEMA, "lore")).toEqual(["lore:character", "lore:place"]);
  });
});
