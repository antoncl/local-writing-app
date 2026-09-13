// @vitest-environment happy-dom
// PlotEditor load/error/loading state machine (#756). The SvelteFlow canvas is not
// headless-testable ([[reference_svelteflow_headless_limits]]) — but it renders ONLY
// in the projection-present branch, so the null-branch states (loading vs. a failed
// load with Retry) mount cleanly in happy-dom and are exactly the new logic here.
import { describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { fireEvent, render, screen } from "@/lib/test/component";
import { plotBoardReveal } from "@/lib/stores/plotlines";
import PlotEditor from "./PlotEditor.svelte";

describe("PlotEditor load state (#756)", () => {
  it("shows the loading blank while the projection is null and there is no error", () => {
    render(PlotEditor, { props: { projection: null, error: null } });
    expect(screen.getByText("Loading the board…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("shows a retryable error state — not a permanent Loading — when the load failed", () => {
    render(PlotEditor, { props: { projection: null, error: "Network down", onRetry: () => {} } });
    expect(screen.queryByText("Loading the board…")).toBeNull();
    expect(screen.getByText("Couldn't load the board.")).toBeInTheDocument();
    expect(screen.getByText("Network down")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("Retry invokes onRetry", async () => {
    const onRetry = vi.fn();
    render(PlotEditor, { props: { projection: null, error: "boom", onRetry } });
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("drops a pending reveal on a failed load (review of #1922)", () => {
    // Backend down → click a plot hit (sets the reveal) → the pane shows its
    // inline error. Without clearing here, a Retry minutes later would light a
    // node from a click the writer has forgotten.
    plotBoardReveal.set({ id: "card_1", entryType: "plot:card" });
    render(PlotEditor, { props: { projection: null, error: "boom", onRetry: () => {} } });
    expect(get(plotBoardReveal)).toBeNull();
  });

  it("keeps a pending reveal while the load is still in flight (no error yet)", () => {
    // A still-loading board (null projection, null error) must not drop the
    // reveal — only a load that actually FAILED should.
    plotBoardReveal.set({ id: "card_1", entryType: "plot:card" });
    render(PlotEditor, { props: { projection: null, error: null, onRetry: () => {} } });
    expect(get(plotBoardReveal)).toEqual({ id: "card_1", entryType: "plot:card" });
    plotBoardReveal.set(null);
  });
});
