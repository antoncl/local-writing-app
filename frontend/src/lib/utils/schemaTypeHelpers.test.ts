import { describe, expect, it } from "vitest";
import type { MetadataSchema } from "@/lib/types";
import {
  isMetadataValuePresent,
  kindEntryTypeFqns,
  kindEntryTypeOptions,
  nestingLocalPrefix,
} from "@/lib/utils/schemaTypeHelpers";

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

describe("nestingLocalPrefix (#600 — roll a sub-type id nested under its parent)", () => {
  const PROMPT_SCHEMA = {
    version: 1,
    entry_types: {
      "prompt:base": { name: "Prompt", kind: "prompt", abstract: true },
      "prompt:revise": { name: "Revise", kind: "prompt", parent: "prompt:base", abstract: true },
      "prompt:revise:scene": { name: "Revise Scene", kind: "prompt", parent: "prompt:revise" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  it("nests under a concrete parent's local key", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "prompt:revise")).toBe("revise");
  });

  it("keeps the parent's full nested local path for a grandchild", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "prompt:revise:scene")).toBe("revise:scene");
  });

  it("stays flat under the kind's abstract root or no parent", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "prompt:base")).toBe("");
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", null)).toBe("");
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "")).toBe("");
  });

  it("does not nest under a parent of a different kind", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "lore:character")).toBe("");
  });
});

describe("kindEntryTypeFqns (delegates to the concrete roster)", () => {
  it("returns concrete FQNs only", () => {
    expect(kindEntryTypeFqns(SCHEMA, "lore")).toEqual(["lore:character", "lore:place"]);
  });
});

describe("isMetadataValuePresent", () => {
  it("treats undefined / null / empty string / empty list as unset", () => {
    expect(isMetadataValuePresent(undefined)).toBe(false);
    expect(isMetadataValuePresent(null)).toBe(false);
    expect(isMetadataValuePresent("")).toBe(false);
    expect(isMetadataValuePresent([])).toBe(false);
  });

  it("treats false and 0 as present — the sharp boolean case (#522)", () => {
    // A boolean field set to false is SET, not unset; a two-state toggle would
    // otherwise render it identically to an untouched (absent) field.
    expect(isMetadataValuePresent(false)).toBe(true);
    expect(isMetadataValuePresent(0)).toBe(true);
  });

  it("treats non-empty scalars and lists as present", () => {
    expect(isMetadataValuePresent(true)).toBe(true);
    expect(isMetadataValuePresent("first")).toBe(true);
    expect(isMetadataValuePresent(42)).toBe(true);
    expect(isMetadataValuePresent(["a"])).toBe(true);
  });
});
