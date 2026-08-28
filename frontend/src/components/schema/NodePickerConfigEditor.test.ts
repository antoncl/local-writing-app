// @vitest-environment happy-dom
// #1458: a collapsed context-pick input row's only expand affordance was an
// 18px chevron — the header is wall-to-wall live controls, so the "click
// anywhere on a collapsed row" gesture the generic input rows get had nowhere
// to land. The collapsed summary strip is now a second, big-surface expand
// target. These pin the affordance pair: both controls exist with accessible
// names, and clicking the strip actually opens the config body.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";

// The editor lists saved views on mount (picker sources) — mock the client so
// the network guard stays quiet (#973 pattern, see TagManagerDialog.test.ts).
vi.mock("@/lib/api", () => ({
  api: {
    listViews: vi.fn(async () => ({ entries: [] })),
  },
}));

import NodePickerConfigEditor from "./NodePickerConfigEditor.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema } from "@/lib/types";

function renderCollapsed() {
  // Prompt mode starts collapsed by design (a fresh prompt shouldn't dump
  // the full picker tree). An empty config + empty schema store renders the
  // "Nothing pickable yet" warning inside the strip.
  return render(NodePickerConfigEditor, {
    props: { config: {}, mode: "prompt" as const, label: "Lore", name: "lore" },
  });
}

describe("NodePickerConfigEditor — collapsed expand affordances (#1458)", () => {
  it("offers both the chevron and the summary strip as expand controls", () => {
    const { container } = renderCollapsed();
    const chevron = screen.getByRole("button", { name: "Expand context picker" });
    expect(chevron.getAttribute("aria-expanded")).toBe("false");
    // The strip is a real <button> carrying the summary (the warning here),
    // not an inert div — the biggest click target on the row.
    const strip = container.querySelector(".ctx-collapsed-strip");
    expect(strip?.tagName).toBe("BUTTON");
    expect(strip?.textContent).toContain("Nothing pickable yet");
  });

  it("clicking the summary strip expands the picker config", async () => {
    const { container } = renderCollapsed();
    expect(container.querySelector(".ctx-body")).toBeNull();
    await fireEvent.click(container.querySelector(".ctx-collapsed-strip")!);
    // The config body is open, the strip is gone, and the chevron now
    // offers (and announces) collapse.
    expect(container.querySelector(".ctx-body")).toBeTruthy();
    expect(container.querySelector(".ctx-collapsed-strip")).toBeNull();
    const chevron = screen.getByRole("button", { name: "Collapse context picker" });
    expect(chevron.getAttribute("aria-expanded")).toBe("true");
  });
});

// ADR-0074 slice 6: plot becomes an offerable source. Its non-content types
// (plot:board — a presentation singleton; plot:template — a Library lens) stay
// hidden, so an author sees only plotline + card.
describe("NodePickerConfigEditor — plot source (ADR-0074 slice 6)", () => {
  const PLOT_SCHEMA = {
    entry_types: {
      "plot:base": { name: "All plots", kind: "plot", abstract: true },
      "plot:plotline": { name: "Plotline", kind: "plot", parent: "plot:base" },
      "plot:card": { name: "Card", kind: "plot", parent: "plot:base" },
      "plot:template": { name: "Template", kind: "plot", parent: "plot:base" },
      "plot:board": { name: "Board", kind: "plot", parent: "plot:base" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  afterEach(() => metadataSchemaStore.set(null as unknown as MetadataSchema));

  it("offers plotline + card and hides plot:board / plot:template", () => {
    metadataSchemaStore.set(PLOT_SCHEMA);
    // Field mode renders the tree always-expanded — no collapse gesture needed.
    render(NodePickerConfigEditor, { props: { config: {}, mode: "field" as const } });
    // Plotline + card render only if "plot" was added to the offered kinds.
    expect(screen.getByText("Plotline")).toBeInTheDocument();
    expect(screen.getByText("Card")).toBeInTheDocument();
    // The two non-content types are filtered out of the offered tree.
    expect(screen.queryByText("Board")).toBeNull();
    expect(screen.queryByText("Template")).toBeNull();
  });
});
