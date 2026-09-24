// Pure unit tests for the metadata rail's row model (#2022 split of
// MetadataPanel). No Svelte mount needed — `buildRailRowModel` is a plain
// function over a `RailRowContext`.
import { describe, expect, it } from "vitest";
import { buildRailRowModel, type RailRowContext } from "./fieldRowModel";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["alias", "allies", "tags", "status", "bio", "beats", "follow_ups"] },
    "tag:tag": { name: "Tag", kind: "tag" },
  },
  fields: {
    alias: { name: "Alias", type: "text", options: [] },
    bio: { name: "Bio", type: "long_text", options: [] },
    // #2043: a list whose items carry prose (a repeating body section) and one
    // whose items are scalars (a fact list that stays in the rail).
    beats: {
      name: "Beats",
      type: "list",
      options: [],
      item_group: "plot_beat",
      item_scalar: false,
      item_members: [
        { key: "title", name: "Title", type: "text" },
        { key: "function", name: "Function", type: "long_text" },
      ],
    },
    follow_ups: {
      name: "Follow-ups",
      type: "list",
      options: [],
      item_type: "text",
      item_scalar: true,
      item_members: [{ key: "value", name: "Value", type: "text" }],
    },
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
    // ADR-0089 §3/§6: a reference-keyed list's effective value folds to items
    // (member maps), not ids — and #2072 widens isListIndex to admit a
    // group-shaped `list` keyed by its one `entity_ref` member, same as an
    // entity_ref_list.
    relationships: {
      name: "Relationships",
      type: "list",
      options: [],
      item_scalar: false,
      item_members: [
        { key: "who", name: "Who", type: "entity_ref" },
        { key: "role", name: "Role", type: "select" },
      ],
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
    listsInBody: false,
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

  it("a reference-keyed list flip names each target and appends member detail (#2168)", () => {
    const ctx = baseCtx({
      metadata: { relationships: [{ who: "lore_1", role: "ally" }] },
      compare: {
        fields: {
          relationships: {
            was: [{ who: "lore_1", role: "rival" }],
            now: [{ who: "lore_1", role: "ally" }],
          },
        },
        side: "was",
        resolve: { adopted: () => false, onToggle: () => {} },
      },
      resolveListMemberTitle: (id) => (id === "lore_1" ? "Mara" : null),
    });
    // The "Current:" hint shows the `now` (current) side, target named, not a raw record.
    expect(buildRailRowModel(ctx, "relationships").flipCurrentHint).toBe("Mara · ally");
  });

  it("a keyed-list flip falls back to the id, then '(orphaned)', when a target can't be named (#2168)", () => {
    const ctx = baseCtx({
      compare: {
        fields: {
          relationships: {
            was: [],
            now: [{ who: "lore_x", role: "ally" }, { role: "foe" }],
          },
        },
        side: "was",
        resolve: { adopted: () => false, onToggle: () => {} },
      },
      resolveListMemberTitle: () => null,
    });
    // Unresolvable id → the id itself; a blank-key (orphaned) item → "(orphaned)".
    expect(buildRailRowModel(ctx, "relationships").flipCurrentHint).toBe("lore_x · ally, (orphaned) · foe");
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
    expect(model.sectionSummary).toBeNull();
  });

  describe("list sections (#2043)", () => {
    it("with sectionsInBody, a list whose items carry prose is a non-wide index row reading the item count", () => {
      const model = buildRailRowModel(
        baseCtx({ sectionsInBody: true, metadata: { beats: [{ title: "One" }, { title: "Two" }, {}] } }),
        "beats",
      );
      expect(model.sectionIndex).toBe(true);
      expect(model.wide).toBe(false);
      expect(model.sectionSummary).toBe("3 items");
      expect(model.wordCount).toBe(0);
    });

    it("one item reads singular; an empty list reads empty through the same branch", () => {
      expect(buildRailRowModel(baseCtx({ sectionsInBody: true, metadata: { beats: [{}] } }), "beats").sectionSummary).toBe("1 item");
      const empty = buildRailRowModel(baseCtx({ sectionsInBody: true, metadata: {} }), "beats");
      expect(empty.sectionIndex).toBe(true);
      expect(empty.empty).toBe(true);
      expect(empty.sectionSummary).toBe("");
    });

    it("without sectionsInBody, the list is the plain wide rail row it always was", () => {
      const model = buildRailRowModel(baseCtx({ metadata: { beats: [{}] } }), "beats");
      expect(model.sectionIndex).toBe(false);
      expect(model.wide).toBe(true);
      expect(model.sectionSummary).toBeNull();
    });

    it("a list of scalar items is a fact list: wide in the rail even with sectionsInBody", () => {
      const model = buildRailRowModel(baseCtx({ sectionsInBody: true, metadata: { follow_ups: ["a"] } }), "follow_ups");
      expect(model.sectionIndex).toBe(false);
      expect(model.wide).toBe(true);
    });
  });

  describe("listsInBody (#2010)", () => {
    it("without listsInBody, a populated entity_ref_list is unchanged (wide + foldable, no index)", () => {
      const model = buildRailRowModel(baseCtx({ metadata: { allies: ["lore_1"] } }), "allies");
      expect(model.listIndex).toBe(false);
      expect(model.wide).toBe(true);
      expect(model.foldableList).toBe(true);
    });

    it("with listsInBody, a populated entity_ref_list becomes a non-wide, non-foldable index row with a per-type summary", () => {
      const model = buildRailRowModel(
        baseCtx({
          listsInBody: true,
          metadata: { allies: ["lore_1", "lore_2", "lore_3"] },
          resolveListMemberType: (id) => (id === "lore_2" ? "tag:tag" : "lore:character"),
        }),
        "allies",
      );
      expect(model.listIndex).toBe(true);
      expect(model.wide).toBe(false);
      expect(model.foldableList).toBe(false);
      expect(model.listSummary).toBe("3 · 2 Character, 1 Tag");
    });

    it("an unresolvable list member counts as 'missing' in the summary", () => {
      const model = buildRailRowModel(
        baseCtx({ listsInBody: true, metadata: { allies: ["lore_1"] } }),
        "allies",
      );
      expect(model.listSummary).toBe("1 missing");
    });

    it("an empty entity_ref_list with listsInBody still reads empty (folds under #2006)", () => {
      const model = buildRailRowModel(baseCtx({ listsInBody: true, metadata: {} }), "allies");
      expect(model.listIndex).toBe(true);
      expect(model.empty).toBe(true);
      expect(model.listSummary).toBe("");
    });

    it("a tag-vocabulary field is never a list index, even with listsInBody", () => {
      const model = buildRailRowModel(baseCtx({ listsInBody: true, metadata: { tags: ["tag_1"] } }), "tags");
      expect(model.listIndex).toBe(false);
      expect(model.isTagList).toBe(true);
    });

    it("a folded relationship item (ADR-0089 §3) summarizes by its entity_ref key member, never '[object Object]'", () => {
      const model = buildRailRowModel(
        baseCtx({
          listsInBody: true,
          metadata: {},
          effectiveOverrides: { relationships: [{ who: "lore_a", role: "squire" }] },
          resolveListMemberType: (id) => (id === "lore_a" ? "lore:character" : null),
        }),
        "relationships",
      );
      expect(model.listSummary).not.toContain("[object Object]");
      expect(model.listSummary).toBe("1 Character");
    });

    it("#2072: a reference-keyed list (a group-shaped `list`, not entity_ref_list) is a list index too, and isWide short-circuits through it", () => {
      const model = buildRailRowModel(
        baseCtx({ listsInBody: true, metadata: { relationships: [{ who: "lore_a", role: "squire" }] } }),
        "relationships",
      );
      expect(model.listIndex).toBe(true);
      expect(model.wide).toBe(false);
    });

    it("#2072: without listsInBody, a reference-keyed list stays the plain wide rail row", () => {
      const model = buildRailRowModel(baseCtx({ metadata: { relationships: [{ who: "lore_a", role: "squire" }] } }), "relationships");
      expect(model.listIndex).toBe(false);
      expect(model.wide).toBe(true);
    });
  });
});
