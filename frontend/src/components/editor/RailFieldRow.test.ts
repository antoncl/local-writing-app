// @vitest-environment happy-dom
// #2022 split — RailFieldRow renders one metadata rail row from a fully-built
// RailRowModel; MetadataPanel's own mount tests already cover the panel-level
// wiring (sections, fold, outside-click), so these pin the row itself: which
// branch a model selects, and that a write-back reaches the panel only
// through the `on` callbacks, never panel state directly.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import RailFieldRow, { type RailRowCallbacks, type RailRowDeps } from "./RailFieldRow.svelte";
import { buildRailRowModel, type RailRowContext } from "@/lib/rail/fieldRowModel";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { tagNodesStore, clearTagNodes } from "@/lib/stores/tagNodes";
import type { MetadataSchema, TagEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["alias", "cost", "tags"] },
    "tag:theme": { name: "Theme", kind: "tag" },
  },
  fields: {
    alias: { name: "Alias", type: "text", options: [] },
    cost: { name: "Cost", type: "computed", options: [], computed: { fn: "cost" } },
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "tag", expr: { type: "tag:theme" } }] },
    },
  },
} as unknown as MetadataSchema;

const TAGS: TagEntry[] = [{ id: "tag_a", title: "Alpha", entry_type: "tag:theme", metadata: {} }];

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

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
    ...overrides,
  };
}

function baseDeps(overrides: Partial<RailRowDeps> = {}): RailRowDeps {
  return { readOnly: false, ...overrides };
}

function baseCallbacks(): RailRowCallbacks {
  return {
    open: vi.fn(),
    close: vi.fn(),
    clear: vi.fn(),
    write: vi.fn(),
    toggleExpanded: vi.fn(),
    statusChange: vi.fn(),
    resetField: vi.fn(),
    navigate: vi.fn(),
    toggleFlip: vi.fn(),
  };
}

describe("RailFieldRow", () => {
  it("a scalar model renders .field-row.scalar with the label and the RailScalarCell hit", () => {
    const model = buildRailRowModel(baseCtx({ metadata: { alias: "The Painted" } }), "alias");
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on: baseCallbacks() } });
    const row = container.querySelector(".field-row") as HTMLElement;
    expect(row.classList.contains("scalar")).toBe(true);
    expect(screen.getByText("Alias")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Edit Alias/ })).toBeTruthy();
  });

  it("a computed model renders .fr-computed and the lock glyph", () => {
    const model = buildRailRowModel(baseCtx({ computedFieldString: () => "42" }), "cost");
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on: baseCallbacks() } });
    expect(container.querySelector(".fr-computed")).not.toBeNull();
    expect(container.querySelector(".fr-computed .ti-lock")).not.toBeNull();
  });

  it("a tag-list model renders the rail tag line", () => {
    tagNodesStore.set(TAGS);
    const model = buildRailRowModel(baseCtx({ metadata: { tags: ["tag_a"] } }), "tags");
    render(RailFieldRow, { props: { model, deps: baseDeps(), on: baseCallbacks() } });
    expect(screen.getByTestId("rail-tag-line")).toBeTruthy();
    clearTagNodes();
  });

  it("clicking the name fires on.open with the row element", async () => {
    const model = buildRailRowModel(baseCtx({ metadata: { alias: "The Painted" } }), "alias");
    const on = baseCallbacks();
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on } });
    await fireEvent.click(screen.getByText("Alias"));
    expect(on.open).toHaveBeenCalledWith("alias", container.querySelector(".field-row"));
  });
});
