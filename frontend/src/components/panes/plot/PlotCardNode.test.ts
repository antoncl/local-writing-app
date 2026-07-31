// @vitest-environment happy-dom
// PlotCardNode RENDER guard (ADR-0048 S7b). The plot board's job is to DISPLAY
// cards, and a display surface needs a mount test that asserts the content renders
// ([[reference_component_test_harness]] — the #724 lesson, twice). The board's
// SvelteFlow canvas is not headless-mountable, so this card is written WITHOUT any
// @xyflow/svelte import precisely so it can be mounted here on its own.
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import PlotCardNode from "./PlotCardNode.svelte";
import type { PlotCardData } from "@/lib/plot/plotBoardLayout";

const data = (over: Partial<PlotCardData> = {}): PlotCardData => ({
  title: "She leaves home",
  synopsis: "The heroine packs a bag and walks out.",
  attached: false,
  color: null,
  ...over,
});

describe("PlotCardNode", () => {
  it("renders the card title and synopsis", () => {
    render(PlotCardNode, { props: { data: data() } });
    expect(screen.getByText("She leaves home")).toBeInTheDocument();
    expect(screen.getByText("The heroine packs a bag and walks out.")).toBeInTheDocument();
  });

  it("shows scene attachment state", () => {
    render(PlotCardNode, { props: { data: data({ attached: true }) } });
    expect(screen.getByText("Scene attached")).toBeInTheDocument();
  });

  it("shows an unattached card as having no scene", () => {
    render(PlotCardNode, { props: { data: data({ attached: false }) } });
    expect(screen.getByText("No scene")).toBeInTheDocument();
  });

  it("falls back to a placeholder title for an untitled card", () => {
    render(PlotCardNode, { props: { data: data({ title: "" }) } });
    expect(screen.getByText("Untitled card")).toBeInTheDocument();
  });
});
