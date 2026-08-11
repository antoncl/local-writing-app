// @vitest-environment happy-dom
// PlotLinkPopover RENDER guard (#820). The shared roomy surface the card's link
// editors live on: a back-to-menu header (chevron + title), a filter input, and a
// body that hosts the picker rows. Mount-tested here ([[reference_component_test_harness]]).
import { describe, expect, it, vi } from "vitest";
import { createRawSnippet } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotLinkPopover from "./PlotLinkPopover.svelte";

const body = createRawSnippet(() => ({ render: () => `<p>PICKER ROWS</p>` }));

function renderPopover(over: { title?: string; onBack?: () => void } = {}) {
  const onBack = over.onBack ?? vi.fn();
  render(PlotLinkPopover, { props: { title: over.title ?? "Beats", onBack, children: body } });
  return { onBack };
}

describe("PlotLinkPopover", () => {
  it("shows the page title in the back button and renders the body", () => {
    renderPopover({ title: "Leads to…" });
    expect(screen.getByRole("button", { name: /Leads to/ })).toBeInTheDocument();
    expect(screen.getByText("PICKER ROWS")).toBeInTheDocument();
  });

  it("offers a filter input labelled for the page", () => {
    renderPopover({ title: "Beats" });
    expect(screen.getByLabelText("Filter Beats")).toBeInTheDocument();
  });

  it("calls onBack when the header is clicked", async () => {
    const { onBack } = renderPopover({ title: "Beats" });
    await fireEvent.click(screen.getByRole("button", { name: /Beats/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
