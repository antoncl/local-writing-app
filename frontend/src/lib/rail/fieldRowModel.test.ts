// Pure unit tests for the metadata rail's row model (#2022 split of
// MetadataPanel). No Svelte mount needed — `buildRailRowModel` is a plain
// function over a `RailRowContext`.
import { describe, expect, it } from "vitest";
import { buildRailRowModel, type RailRowContext } from "./fieldRowModel";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["alias", "allies", "tags", "status", "bio"] },
    "tag:tag": { name: "Tag", kind: "tag" },
  },
  fields: {
    alias: { name: "Alias", type: "text", options: [] },
    bio: { name: "Bio", type: "long_text", options: [] },
    allies: {
      name: "Allies",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: { create_missing: true, sources: [{ kind: "tag", expr: { type: "tag:tag" } }] },
    },
    status: {
      name: "Status",
      type: "select",
      options: [{ value: "draft", label: "Draft" }],
    },
  },
} as unknown as MetadataSchema;

function baseCtx(overrides: Partial<RailRowContext> = {}): RailRowContext {
  return {
    schema: SCHEMA,
    entryType: "lore:character",
    documentKind: "lore",
    metadata: {},
    status: "",
    hasOwnFields: false,
    ownFieldSet: new Set(),
    effectiveOverrides: null,
    overriddenFields: [],
    compare: null,
    resolvedCascade: null,
    structure: null,
    sourceLayerLabel: null,
    inheritedFromLabel: null,
    canClearOwn: false,
    canResetOverride: false,
    readOnly: false,
    temperatureUnsupported: false,
    temperatureClearedForModel: null,
    computedFieldString: () => "",
    tagTitleById: new Map(),
    openFieldId: null,
    fieldExpanded: () => false,
    sectionsInBody: false,
    ...overrides,
  };
}

describe("buildRailRowModel", () => {
  it("a scalar field with a value is scalar and not empty", () => {
    const model = buildRailRowModel(baseCtx({ metadata: { alias: "The Painted" } }), "alias");
    expect(model.scalar).toBe(true);
    expect(model.empty).toBe(false);
  });

  it("an empty entity_ref_list is neither wide nor foldable", () => {
    const model = buildRailRowModel(baseCtx({ metadata: { allies: [] } }), "allies");
    expect(model.wide).toBe(false);
    expect(model.foldableList).toBe(false);
  });

  it("a populated entity_ref_list is both wide and foldable", () => {
    const model = buildRailRowModel(baseCtx({ metadata: { allies: ["lore_1"] } }), "allies");
    expect(model.wide).toBe(true);
    expect(model.foldableList).toBe(true);
  });

  it("a tag-vocabulary field is a tag list and never foldable, even populated", () => {
    const model = buildRailRowModel(baseCtx({ metadata: { tags: ["tag_1"] } }), "tags");
    expect(model.isTagList).toBe(true);
    expect(model.foldableList).toBe(false);
  });

  it("a flipped field reads flipped, with value the proposed (`was`) side", () => {
    const ctx = baseCtx({
      metadata: { alias: "Current" },
      compare: { fields: { alias: { was: "Proposed", now: "Current" } }, side: "was" },
    });
    const model = buildRailRowModel(ctx, "alias");
    expect(model.flipped).toBe(true);
    expect(model.value).toBe("Proposed");
  });

  it("openFieldId === fieldId reads editing", () => {
    const editing = buildRailRowModel(baseCtx({ metadata: { alias: "x" }, openFieldId: "alias" }), "alias");
    expect(editing.editing).toBe(true);
    const resting = buildRailRowModel(baseCtx({ metadata: { alias: "x" }, openFieldId: "other" }), "alias");
    expect(resting.editing).toBe(false);
  });

  it("status reads the status prop, not the metadata bag", () => {
    const model = buildRailRowModel(baseCtx({ status: "draft", metadata: { status: "ignored" } }), "status");
    expect(model.statusValue).toBe("draft");
  });

  it("without sectionsInBody, long_text is a plain wide rail row (unchanged)", () => {
    const model = buildRailRowModel(baseCtx({ metadata: { bio: "one two three" } }), "bio");
    expect(model.sectionIndex).toBe(false);
    expect(model.wide).toBe(true);
    expect(model.wordCount).toBe(0);
  });

  it("with sectionsInBody, long_text becomes a non-wide index row with a word count", () => {
    const model = buildRailRowModel(baseCtx({ sectionsInBody: true, metadata: { bio: "one two three" } }), "bio");
    expect(model.sectionIndex).toBe(true);
    expect(model.wide).toBe(false);
    expect(model.wordCount).toBe(3);
  });

  it("an empty long_text index row has a zero word count and still reads empty", () => {
    const model = buildRailRowModel(baseCtx({ sectionsInBody: true, metadata: {} }), "bio");
    expect(model.sectionIndex).toBe(true);
    expect(model.wordCount).toBe(0);
    expect(model.empty).toBe(true);
  });
});
