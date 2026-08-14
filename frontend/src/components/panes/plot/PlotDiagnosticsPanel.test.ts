// @vitest-environment happy-dom
// PlotDiagnosticsPanel RENDER + wiring guard (ADR-0048 S7). A display surface that
// lists the board's cross-dimension findings needs a mount test asserting the rows
// render and the click wiring fires ([[reference_component_test_harness]]). Imports
// nothing from @xyflow/svelte, so it mounts in happy-dom on its own.
import { describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotDiagnosticsPanel from "./PlotDiagnosticsPanel.svelte";
import type { PlotDiagnostic } from "@/lib/types";

const causal = (over: Partial<PlotDiagnostic> = {}): PlotDiagnostic => ({
  id: "causal:a:b",
  kind: "causal_inversion",
  message: "“Setup” sets up “Payoff”, but the payoff is revealed first — its setup comes later.",
  cards: [
    { id: "a", title: "Setup" },
    { id: "b", title: "Payoff" },
  ],
  edge: { source: "a", target: "b" },
  plotline_id: null,
  beat_ids: [],
  ...over,
});

const gap = (over: Partial<PlotDiagnostic> = {}): PlotDiagnostic => ({
  id: "beatgap:pl:beat1",
  kind: "beat_gap",
  message: "The “Midpoint” beat of “Romance” has no card, but later beats do.",
  cards: [],
  edge: null,
  plotline_id: "pl",
  beat_ids: ["beat1"],
  ...over,
});

function mount(over: Partial<Record<string, unknown>> = {}) {
  const handlers = { onSelect: vi.fn(), onClose: vi.fn() };
  render(PlotDiagnosticsPanel, {
    props: { diagnostics: [causal(), gap()], selectedId: null, ...handlers, ...over },
  });
  return handlers;
}

describe("PlotDiagnosticsPanel", () => {
  it("lists the findings, grouped by kind, with their messages", async () => {
    mount();
    await tick();
    // The two group headings for the kinds present.
    expect(screen.getByText("Out of sequence")).toBeTruthy();
    expect(screen.getByText("Missing beats")).toBeTruthy();
    // Each finding's message renders in full.
    expect(screen.getByText(/sets up/)).toBeTruthy();
    expect(screen.getByText(/has no card, but later beats do/)).toBeTruthy();
  });

  it("clicking a finding reports its id", async () => {
    const h = mount();
    await tick();
    await fireEvent.click(screen.getByText(/sets up/));
    expect(h.onSelect).toHaveBeenCalledWith("causal:a:b");
  });

  it("marks the selected finding pressed", async () => {
    mount({ selectedId: "causal:a:b" });
    await tick();
    const row = screen.getByText(/sets up/).closest("button");
    expect(row?.getAttribute("aria-pressed")).toBe("true");
  });

  it("the close button reports a close", async () => {
    const h = mount();
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: /Close diagnostics/i }));
    expect(h.onClose).toHaveBeenCalledTimes(1);
  });

  it("shows an all-clear state when the layers agree", async () => {
    mount({ diagnostics: [] });
    await tick();
    expect(screen.getByText(/No problems found/)).toBeTruthy();
  });

  it("omits a group whose kind has no findings", async () => {
    // Only a gap → no "Out of sequence" heading.
    mount({ diagnostics: [gap()] });
    await tick();
    expect(screen.getByText("Missing beats")).toBeTruthy();
    expect(screen.queryByText("Out of sequence")).toBeNull();
  });
});
