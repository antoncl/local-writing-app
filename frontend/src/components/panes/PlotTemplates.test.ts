// @vitest-environment happy-dom
// PlotTemplates pane RENDER guard (#724). The regression that shipped in S4c and
// its fix are both view-layer, so this pins them where they actually bite — the
// rendered shelf — not just the pure evaluateView algebra. The pane's roster is
// `defaultView("plot")` → `descendants_of: plot:base`, so the concrete plot types
// MUST hang off an abstract plot:base or the shelf renders nothing (exactly why
// the pane came up empty). Mounting the real pane catches that; an API/menu check
// or an evaluateView-only test does not.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen } from "@/lib/test/component";
import PlotTemplates from "./PlotTemplates.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PlotTemplateSummary } from "@/lib/types";

// `withBase` toggles the #724 fix: rooted (plot:base parents the concrete types)
// vs. the pre-fix shape (parentless siblings). Same knob as the evaluateView test,
// exercised here through the actual component.
const schema = (withBase: boolean) =>
  ({
    entry_types: {
      ...(withBase ? { "plot:base": { name: "Plot", kind: "plot", abstract: true, fields: [] } } : {}),
      "plot:template": { name: "Plot template", kind: "plot", ...(withBase ? { parent: "plot:base" } : {}), fields: [] },
    },
    fields: {},
  }) as unknown as MetadataSchema;

function libraryTemplate(id: string, title: string): PlotTemplateSummary {
  return {
    id,
    title,
    body: "",
    entry_type: "plot:template",
    template: { slug: id, display_name: title },
    source_layer_id: "layer_library",
    source_layer_label: "Library",
    is_library: true,
  };
}

const noop = () => {};

function renderPane() {
  return render(PlotTemplates, {
    props: {
      entries: [libraryTemplate("t-three-act", "Three-Act Story Arc"), libraryTemplate("t-kisho", "Kishotenketsu")],
      onOpenEntry: noop,
      onCloneEntry: noop,
    },
  });
}

beforeEach(() => {
  localStorage.clear();
  openProjectHidden("test-project");
  metadataSchemaStore.set(schema(true));
});
afterEach(() => {
  openProjectHidden(null);
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("PlotTemplates pane render (#724)", () => {
  it("renders a row per shipped template, with the Library clone affordance", async () => {
    renderPane();
    await tick();
    expect(screen.getByText("Three-Act Story Arc")).toBeInTheDocument();
    expect(screen.getByText("Kishotenketsu")).toBeInTheDocument();
    // is_library rows carry the clone-to-own action.
    expect(screen.getByLabelText("Clone Three-Act Story Arc into this project")).toBeInTheDocument();
  });

  it("renders NOTHING when plot has no abstract base — the #724 regression", async () => {
    // Parentless siblings: the roster `descendants_of: plot:base` has no base to
    // expand, so every template is filtered out and the shelf is empty. This is
    // the assertion an evaluateView-only test proxied and an API check missed.
    metadataSchemaStore.set(schema(false));
    renderPane();
    await tick();
    expect(screen.queryByText("Three-Act Story Arc")).toBeNull();
    expect(screen.getByText("No plot templates match this view.")).toBeInTheDocument();
  });
});
