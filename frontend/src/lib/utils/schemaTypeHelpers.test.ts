import { describe, expect, it } from "vitest";
import type { MetadataSchema } from "@/lib/types";
import {
  coerceStringList,
  isMetadataValuePresent,
  kindEntryTypeFqns,
  kindEntryTypeOptions,
  nestingLocalPrefix,
  normalizeListFieldValue,
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

describe("coerceStringList", () => {
  it("splits a comma string into trimmed, non-empty tokens (no de-dupe)", () => {
    expect(coerceStringList(" a , b ,, A ")).toEqual(["a", "b", "A"]);
  });

  it("coerces an array of items to trimmed strings, dropping empties", () => {
    expect(coerceStringList([" x ", "", 3, "  "])).toEqual(["x", "3"]);
  });

  it("returns an empty list for null / undefined / empty string", () => {
    expect(coerceStringList(null)).toEqual([]);
    expect(coerceStringList(undefined)).toEqual([]);
    expect(coerceStringList("")).toEqual([]);
  });
});

describe("normalizeListFieldValue", () => {
  // #704: the tags SAVE path — not just the render — must de-dupe, so a case
  // duplicate from an importer / hand-edited YAML can't be persisted.
  it("de-dupes a tags value case-insensitively (first spelling wins)", () => {
    expect(normalizeListFieldValue("tags", "Alpha, alpha, beta, BETA")).toEqual(["Alpha", "beta"]);
  });

  it("de-dupes tags whether the value arrives as a string or an array", () => {
    expect(normalizeListFieldValue("tags", ["a", "A", "b"])).toEqual(["a", "b"]);
  });

  // #725: multi_select is a controlled vocabulary — de-dupe CASE-INSENSITIVELY,
  // matching the toggle's case-insensitive option compare, so a case dup can't be
  // persisted while the toggle treats the two as one.
  it("de-dupes multi_select case-insensitively (first spelling wins)", () => {
    expect(normalizeListFieldValue("multi_select", "Draft, draft, Final")).toEqual(["Draft", "Final"]);
    expect(normalizeListFieldValue("multi_select", ["a", "a", "A", "b"])).toEqual(["a", "b"]);
  });

  // #725: entity_ref_list items are identifiers — de-dupe CASE-SENSITIVELY, so
  // exact dups collapse but `Alpha`/`alpha` stay distinct refs.
  it("de-dupes entity_ref_list case-sensitively (exact dups only)", () => {
    expect(normalizeListFieldValue("entity_ref_list", ["x", "x", "y"])).toEqual(["x", "y"]);
    expect(normalizeListFieldValue("entity_ref_list", "Alpha, alpha, Alpha")).toEqual(["Alpha", "alpha"]);
  });

  // A non-set field type is not list-shaped and passes through untouched.
  it("passes an unknown field type through without de-duping", () => {
    expect(normalizeListFieldValue("text", "a, a, b")).toEqual(["a", "a", "b"]);
  });
});

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
