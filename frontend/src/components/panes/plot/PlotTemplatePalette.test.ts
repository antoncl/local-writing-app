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

const tpl = (over: Partial<PlotTemplateSummary> = {}): PlotTemplateSummary => ({
  id: "tpl_1",
  title: "Three-Act",
  body: "",
  entry_type: "plot:template",
  template: { slug: "three-act", display_name: "Three-Act" },
  is_library: true,
  ...over,
});

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
