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

function libraryTemplate(id: string, title: string, family?: string): PlotTemplateSummary {
  return {
    id,
    title,
    body: "",
    entry_type: "plot:template",
    template: { slug: id, display_name: title, ...(family ? { family } : {}) },
    source_layer_id: "layer_library",
    source_layer_label: "Library",
    is_library: true,
  };
}

const noop = () => {};

function renderPane(entries?: PlotTemplateSummary[]) {
  return render(PlotTemplates, {
    props: {
      entries: entries ?? [libraryTemplate("t-three-act", "Three-Act Story Arc"), libraryTemplate("t-kisho", "Kishotenketsu")],
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

  // ADR-0080 slice 2 gave arcs their own section; the plotline half splits again into
  // "Story structures" and "Genre patterns" (shared with the spawn palette via
  // groupPlotTemplates). All splits are plain array partitions (family isn't a schema
  // field), not a view group_by, so every section rides the same view spec.
  it("sections story structures, genre patterns, and character arcs apart", async () => {
    renderPane([
      libraryTemplate("t-three-act", "Three-Act Story Arc"),
      libraryTemplate("t-mystery", "Mystery / Fair-Play Investigation", "puzzle"),
      libraryTemplate("t-arc", "Positive Change Arc", "character_arc"),
    ]);
    await tick();
    const structuresHeader = screen.getByText("Story structures");
    const genreHeader = screen.getByText("Genre patterns");
    const arcsHeader = screen.getByText("Character arcs");
    expect(structuresHeader).toBeInTheDocument();
    expect(genreHeader).toBeInTheDocument();
    expect(arcsHeader).toBeInTheDocument();
    expect(screen.getByText("Three-Act Story Arc")).toBeInTheDocument();
    expect(screen.getByText("Mystery / Fair-Play Investigation")).toBeInTheDocument();
    expect(screen.getByText("Positive Change Arc")).toBeInTheDocument();
    expect(screen.queryByText("Plotlines")).toBeNull();
    // Story structures, then genre patterns, then character arcs.
    expect(structuresHeader.compareDocumentPosition(genreHeader) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(genreHeader.compareDocumentPosition(arcsHeader) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("hides the Character arcs section when no arc template exists", async () => {
    renderPane([libraryTemplate("t-three-act", "Three-Act Story Arc")]);
    await tick();
    expect(screen.queryByText("Character arcs")).toBeNull();
    expect(screen.getByText("Story structures")).toBeInTheDocument();
  });

  it("shows the seedling glyph on the Character arcs header", async () => {
    const { container } = renderPane([libraryTemplate("t-arc", "Positive Change Arc", "character_arc")]);
    await tick();
    expect(container.querySelector(".ti-seedling")).toBeTruthy();
  });
});
