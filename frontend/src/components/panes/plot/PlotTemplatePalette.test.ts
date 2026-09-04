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
    // here. It is NOT "your template"; provenance rides the ◆ glyph alone.
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

  it("carries no template-management chrome — that lives on the Plot Templates pane (#916)", async () => {
    // The palette is a spawn source: no clone/hide (Library rows) or edit/delete (owned
    // rows) buttons, and no "Library" provenance pill crowding the narrow rail.
    mount();
    await tick();
    for (const name of [/Clone /i, /Hide /i, /Edit /i, /Delete /i, /again/i]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByText("Library")).toBeNull();
  });

  it("drops a template hidden on the pane from the spawn list", async () => {
    // Hiding is the pane's job; the palette just respects it (no un-hide affordance).
    const { hideLibraryEntry } = await import("@/lib/stores/hiddenLibrary");
    mount();
    await tick();
    expect(screen.getByText("Three-Act")).toBeTruthy();
    hideLibraryEntry("tpl_1");
    await tick();
    expect(screen.queryByText("Three-Act")).toBeNull();
    expect(screen.getByText("Heist beats")).toBeTruthy();
  });

  it("shows an empty hint but keeps the Empty tile when there are no templates", async () => {
    mount({ entries: [] });
    await tick();
    expect(screen.getByText("No plot templates.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Empty plotline/i })).toBeTruthy();
  });

  // ADR-0080 slice 2 gave arc templates their own section; the plotline half is split
  // again into "Story structures" and "Genre patterns" so a newcomer meets a few labelled
  // buckets, not a flat wall. All splits are plain array partitions (family isn't a schema
  // field), not a view group_by, so every section still rides the same `plot` view spec.
  it("sections character-arc templates apart from story structures", async () => {
    mount({
      entries: [
        tpl({ id: "p1", title: "Three-Act" }),
        tpl({ id: "a1", title: "Positive Change Arc", template: { slug: "positive-change-arc", display_name: "Positive Change Arc", family: "character_arc" } }),
      ],
    });
    await tick();
    const structuresHeader = screen.getByText("Story structures");
    const arcsHeader = screen.getByText("Character arcs");
    expect(structuresHeader).toBeTruthy();
    expect(arcsHeader).toBeTruthy();
    expect(screen.getByText("Three-Act")).toBeTruthy();
    expect(screen.getByText("Positive Change Arc")).toBeTruthy();
    // Story structures first.
    const position = structuresHeader.compareDocumentPosition(arcsHeader);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  // A genre-shaped spine (puzzle/genre/relationship family) buckets under "Genre patterns",
  // between story structures and character arcs.
  it("sections a genre-family template into Genre patterns", async () => {
    mount({
      entries: [
        tpl({ id: "p1", title: "Three-Act" }),
        tpl({ id: "g1", title: "Thriller Escalation", template: { slug: "thriller-escalation-arc", display_name: "Thriller Escalation", family: "genre" } }),
      ],
    });
    await tick();
    const structuresHeader = screen.getByText("Story structures");
    const genreHeader = screen.getByText("Genre patterns");
    expect(genreHeader).toBeTruthy();
    expect(screen.getByText("Thriller Escalation")).toBeTruthy();
    // Three-Act stays under Story structures, not Genre patterns.
    expect(screen.queryByText("Plotlines")).toBeNull();
    // Story structures precede Genre patterns.
    const position = structuresHeader.compareDocumentPosition(genreHeader);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("hides the Character arcs section when no arc template exists", async () => {
    mount({ entries: [tpl({ id: "p1", title: "Three-Act" })] });
    await tick();
    expect(screen.queryByText("Character arcs")).toBeNull();
    expect(screen.getByText("Story structures")).toBeTruthy();
  });

  it("shows the seedling glyph on the Character arcs header", async () => {
    const { container } = render(PlotTemplatePalette, {
      props: {
        entries: [tpl({ id: "a1", title: "Positive Change Arc", template: { slug: "positive-change-arc", display_name: "Positive Change Arc", family: "character_arc" } })],
        onInstantiate: vi.fn(),
        onEmpty: vi.fn(),
      },
    });
    await tick();
    expect(container.querySelector(".ti-seedling")).toBeTruthy();
  });
});
