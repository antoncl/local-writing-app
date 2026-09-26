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
    "lore:character": { name: "Character", kind: "lore", fields: ["alias", "cost", "tags", "kin", "bio", "hue", "home"] },
    "lore:location": { name: "Location", kind: "lore", fields: [] },
    "tag:theme": { name: "Theme", kind: "tag" },
  },
  fields: {
    alias: { name: "Alias", type: "text", options: [] },
    home: { name: "Home", type: "entity_ref", options: [], picker_config: { sources: [{ kind: "lore" }] } },
    cost: { name: "Cost", type: "computed", options: [], computed: { fn: "cost" } },
    kin: { name: "Kin", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } },
    bio: { name: "Bio", type: "long_text", options: [] },
    hue: { name: "Hue", type: "color", options: [] },
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
    sectionsInBody: false,
    listsInBody: false,
    scrubbed: false,
    stopEditable: () => false,
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
    goToSection: vi.fn(),
    goToList: vi.fn(),
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

  it("a single reference rests as one line with the target's name, and opens through the callbacks (#2058)", async () => {
    const resolveRef = (id: string) => (id === "lore_thr" ? { id, kind: "lore", title: "The Painted Threshold", entry_type: "lore:location" } : null);
    const model = buildRailRowModel(baseCtx({ metadata: { home: "lore_thr" } }), "home");
    expect(model.scalar).toBe(true);
    expect(model.singleRef).toBe(true);
    expect(model.closesOnPick).toBe(true);
    const on = baseCallbacks();
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps({ resolveRef }), on } });
    expect(container.querySelector(".field-row.scalar")).not.toBeNull();
    expect(screen.getByTestId("rail-ref-name").textContent).toBe("The Painted Threshold");
    // No picker at rest: the pill + trigger that stacked to two lines are gone.
    expect(container.querySelector(".reference-picker")).toBeNull();
    const hit = screen.getByRole("button", { name: "Edit Home: The Painted Threshold" });
    await fireEvent.click(hit);
    expect(on.open).toHaveBeenCalledWith("home", expect.any(HTMLElement));
  });

  it("a single reference shows its stored id at rest when nothing resolves it, and the picker while open (#2058)", () => {
    const rest = buildRailRowModel(baseCtx({ metadata: { home: "lore_gone" } }), "home");
    const first = render(RailFieldRow, { props: { model: rest, deps: baseDeps(), on: baseCallbacks() } });
    expect(screen.getByTestId("rail-ref-name").textContent).toBe("lore_gone");
    first.unmount();
    const open = buildRailRowModel(baseCtx({ metadata: { home: "lore_gone" }, openFieldId: "home" }), "home");
    const { container } = render(RailFieldRow, { props: { model: open, deps: baseDeps(), on: baseCallbacks() } });
    expect(container.querySelector(".field-row.editing")).not.toBeNull();
    expect(container.querySelector(".reference-picker")).not.toBeNull();
  });

  it("a read-only single reference stays the plain read-only picker (#2058)", () => {
    const model = buildRailRowModel(baseCtx({ metadata: { home: "lore_thr" }, readOnly: true }), "home");
    expect(model.scalar).toBe(false);
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps({ readOnly: true }), on: baseCallbacks() } });
    expect(container.querySelector(".reference-picker")).not.toBeNull();
    expect(container.querySelector('[data-testid="rail-ref-name"]')).toBeNull();
  });

  it("a tags row is wide, empty or filled, so the line keeps one shape (#2059)", () => {
    expect(buildRailRowModel(baseCtx(), "tags").wide).toBe(true);
    expect(buildRailRowModel(baseCtx({ metadata: { tags: ["tag_a"] } }), "tags").wide).toBe(true);
    const { container } = render(RailFieldRow, {
      props: { model: buildRailRowModel(baseCtx({ metadata: { tags: ["tag_a"] } }), "tags"), deps: baseDeps(), on: baseCallbacks() },
    });
    expect(container.querySelector(".field-row.wide")).not.toBeNull();
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

  it("a populated reference-list model renders wide with pills and the fold caret; an empty one is compact with no caret", () => {
    const full = buildRailRowModel(baseCtx({ metadata: { kin: ["lore_1"] } }), "kin");
    const a = render(RailFieldRow, { props: { model: full, deps: baseDeps(), on: baseCallbacks() } });
    const fullRow = a.container.querySelector(".field-row") as HTMLElement;
    expect(fullRow.classList.contains("wide")).toBe(true);
    expect(a.container.querySelector(".ref-pill")).not.toBeNull();
    expect(a.container.querySelector(".fr-disc-toggle")).not.toBeNull();
    a.unmount();
    const empty = buildRailRowModel(baseCtx(), "kin");
    const b = render(RailFieldRow, { props: { model: empty, deps: baseDeps(), on: baseCallbacks() } });
    const emptyRow = b.container.querySelector(".field-row") as HTMLElement;
    expect(emptyRow.classList.contains("wide")).toBe(false);
    expect(emptyRow.classList.contains("empty")).toBe(true);
    expect(b.container.querySelector(".fr-disc-toggle")).toBeNull();
  });

  it("a long_text model (sectionsInBody: false) renders wide and always live (no rest hit)", () => {
    const model = buildRailRowModel(baseCtx({ sectionsInBody: false, metadata: { bio: "Born on the river." } }), "bio");
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on: baseCallbacks() } });
    const row = container.querySelector(".field-row") as HTMLElement;
    expect(row.classList.contains("wide")).toBe(true);
    expect(row.classList.contains("scalar")).toBe(false);
    expect(container.querySelector(".fr-rest-hit")).toBeNull();
  });

  it("a long_text model (sectionsInBody: true) renders as a non-wide 'Go to …' index row", async () => {
    const model = buildRailRowModel(baseCtx({ sectionsInBody: true, metadata: { bio: "one two three four" } }), "bio");
    const on = baseCallbacks();
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on } });
    const row = container.querySelector(".field-row") as HTMLElement;
    expect(row.classList.contains("wide")).toBe(false);
    const hit = screen.getByRole("button", { name: "Go to Bio" });
    expect(hit.textContent).toBe("4 words");
    await fireEvent.click(hit);
    expect(on.goToSection).toHaveBeenCalledWith("bio");
  });

  it("an empty long_text index row (sectionsInBody: true) reads 'empty' and folds like any empty row", () => {
    const model = buildRailRowModel(baseCtx({ sectionsInBody: true, metadata: {} }), "bio");
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on: baseCallbacks() } });
    const row = container.querySelector(".field-row") as HTMLElement;
    expect(row.classList.contains("empty")).toBe(true);
    expect(screen.getByRole("button", { name: "Go to Bio" }).textContent).toBe("empty");
  });

  it("an unset color model renders the color row with the inherited note and never reads empty", () => {
    const model = buildRailRowModel(baseCtx(), "hue");
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on: baseCallbacks() } });
    const row = container.querySelector(".field-row") as HTMLElement;
    expect(row.classList.contains("color-row")).toBe(true);
    expect(row.classList.contains("empty")).toBe(false);
    expect(screen.getByText("inherited")).toBeTruthy();
  });

  it("a listsInBody reference-list model renders as a non-wide 'Open …' index row", async () => {
    const model = buildRailRowModel(
      baseCtx({ listsInBody: true, metadata: { kin: ["lore_1"] }, resolveListMemberType: () => "lore:character" }),
      "kin",
    );
    const on = baseCallbacks();
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on } });
    const row = container.querySelector(".field-row") as HTMLElement;
    expect(row.classList.contains("wide")).toBe(false);
    const hit = screen.getByRole("button", { name: "Open Kin" });
    expect(hit.textContent).toBe("1 Character");
    await fireEvent.click(hit);
    expect(on.goToList).toHaveBeenCalledWith("kin");
  });

  it("clicking the name fires on.open with the row element", async () => {
    const model = buildRailRowModel(baseCtx({ metadata: { alias: "The Painted" } }), "alias");
    const on = baseCallbacks();
    const { container } = render(RailFieldRow, { props: { model, deps: baseDeps(), on } });
    await fireEvent.click(screen.getByText("Alias"));
    expect(on.open).toHaveBeenCalledWith("alias", container.querySelector(".field-row"));
  });
});
