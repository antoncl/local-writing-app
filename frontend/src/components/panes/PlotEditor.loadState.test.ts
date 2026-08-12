// @vitest-environment happy-dom
// PlotEditor load/error/loading state machine (#756). The SvelteFlow canvas is not
// headless-testable ([[reference_svelteflow_headless_limits]]) — but it renders ONLY
// in the projection-present branch, so the null-branch states (loading vs. a failed
// load with Retry) mount cleanly in happy-dom and are exactly the new logic here.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
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
});
