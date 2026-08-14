// @vitest-environment happy-dom
// PlotTemplatePalette RENDER + wiring guard (ADR-0053 §2). The board's rail is now the
// SOURCE you spawn plotlines from — a pane that must DISPLAY its roster + wire its
// actions needs a mount test ([[reference_component_test_harness]]). Composes
// ViewNodeList + NodeRow (no @xyflow import), so it mounts in happy-dom — but the roster
// is `defaultView("plot")` → `descendants_of: plot:base`, so the schema MUST root the
// concrete plot types under an abstract plot:base or the shelf renders nothing (the #724
// trap). Same schema-seeding as PlotTemplates.test.ts.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotTemplatePalette from "./PlotTemplatePalette.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PlotTemplateSummary } from "@/lib/types";

const schema = () =>
  ({
    entry_types: {
      "plot:base": { name: "Plot", kind: "plot", abstract: true, fields: [] },
      "plot:template": { name: "Plot template", kind: "plot", parent: "plot:base", fields: [] },
    },
    fields: {},
  }) as unknown as MetadataSchema;

const tpl = (over: Partial<PlotTemplateSummary> = {}): PlotTemplateSummary => {
  // `editable` defaults to the realistic pairing: a Library template is read-only,
  // an owned clone is editable. A test can still override it explicitly (e.g. an
  // ancestor-inherited non-Library template: is_library:false, editable:false).
  const is_library = over.is_library ?? true;
  return {
    id: "tpl_1",
    title: "Three-Act",
    body: "",
    entry_type: "plot:template",
    template: { slug: "three-act", display_name: "Three-Act" },
    is_library,
    editable: !is_library,
    ...over,
  };
};

function mount(over: Partial<Record<string, unknown>> = {}) {
  const handlers = {
    onInstantiate: vi.fn(),
    onEmpty: vi.fn(),
    onClone: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
  };
  render(PlotTemplatePalette, {
    props: {
      entries: [tpl(), tpl({ id: "tpl_2", title: "Heist beats", is_library: false })],
      ...handlers,
      ...over,
    },
  });
  return handlers;
}

beforeEach(() => {
  localStorage.clear();
  openProjectHidden("test-project");
  metadataSchemaStore.set(schema());
});
afterEach(() => {
  openProjectHidden(null);
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("PlotTemplatePalette", () => {
  it("renders an Empty tile that spawns an ad-hoc plotline", async () => {
    const h = mount();
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: /Empty plotline/i }));
    expect(h.onEmpty).toHaveBeenCalledTimes(1);
  });

  it("lists the templates (Library + own)", async () => {
    mount();
    await tick();
    expect(screen.getByText("Three-Act")).toBeTruthy();
    expect(screen.getByText("Heist beats")).toBeTruthy();
  });

  it("shows each template's beat count, glyph, and owned-provenance prefix", async () => {
    mount({
      entries: [
        tpl({ beat_count: 7 }),
        tpl({ id: "tpl_2", title: "Heist beats", is_library: false, beat_count: 6 }),
        tpl({ id: "tpl_3", title: "One-beater", is_library: false, beat_count: 1 }),
      ],
    });
    await tick();
    // Library row: bare count. Owned rows: "Your template · N beats", singular-aware.
    expect(screen.getByText("7 beats")).toBeTruthy();
    expect(screen.getByText("Your template · 6 beats")).toBeTruthy();
    expect(screen.getByText("Your template · 1 beat")).toBeTruthy();
    // Kind glyphs: ◆ built-in, ✎ owned.
    expect(screen.getByText("◆")).toBeTruthy();
    expect(screen.getAllByText("✎")).toHaveLength(2);
  });

  it("does not claim ownership of an ancestor-inherited (non-owned) template", async () => {
    // is_library:false but editable:false — owned by an ancestor project, inherited
    // here. It is NOT "your template"; provenance rides the ◆ glyph + the layer pill.
    mount({ entries: [tpl({ id: "tpl_x", title: "Series arc", is_library: false, editable: false, beat_count: 5 })] });
    await tick();
    expect(screen.getByText("5 beats")).toBeTruthy();
    expect(screen.queryByText(/Your template/)).toBeNull();
    expect(screen.getByText("◆")).toBeTruthy();
  });

  it("clicking a template instantiates it", async () => {
    const h = mount();
    await tick();
    await fireEvent.click(screen.getByText("Three-Act"));
    expect(h.onInstantiate).toHaveBeenCalledWith("tpl_1");
  });

  it("a Library row offers Clone; an owned row offers Edit + Delete", async () => {
    const h = mount();
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: "Clone Three-Act into this project" }));
    expect(h.onClone).toHaveBeenCalledWith("tpl_1");

    await fireEvent.click(screen.getByRole("button", { name: "Edit Heist beats" }));
    expect(h.onEdit).toHaveBeenCalledWith("tpl_2");

    await fireEvent.click(screen.getByRole("button", { name: "Delete Heist beats" }));
    expect(h.onDelete).toHaveBeenCalledWith("tpl_2");
  });

  it("shows an empty hint but keeps the Empty tile when there are no templates", async () => {
    mount({ entries: [] });
    await tick();
    expect(screen.getByText("No plot templates.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Empty plotline/i })).toBeTruthy();
  });
});
