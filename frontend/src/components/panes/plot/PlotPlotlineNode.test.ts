// @vitest-environment happy-dom
// PlotPlotlineNode RENDER guard (ADR-0053 §3). A plotline is a first-class board node
// that must DISPLAY its beat roster, so — like PlotCardNode — a mount test asserts the
// content renders ([[reference_component_test_harness]]). The node imports nothing from
// @xyflow/svelte, so it mounts here on its own (the SvelteFlow canvas is not headless).
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import PlotPlotlineNode from "./PlotPlotlineNode.svelte";
import type { PlotPlotlineData } from "@/lib/plot/plotBoardLayout";

const data = (over: Partial<PlotPlotlineData> = {}): PlotPlotlineData => ({
  title: "Main plot",
  color: null,
  beats: [
    { beat_id: "b1", title: "Setup" },
    { beat_id: "b2", title: "Confrontation" },
    { beat_id: "b3", title: "Resolution" },
  ],
  ...over,
});

describe("PlotPlotlineNode", () => {
  it("renders the plotline title and its whole beat roster in order", () => {
    render(PlotPlotlineNode, { props: { data: data() } });
    expect(screen.getByText("Main plot")).toBeTruthy();
    const beats = screen.getAllByRole("listitem").map((li) => li.textContent?.trim());
    expect(beats).toEqual(["Setup", "Confrontation", "Resolution"]);
  });

  it("shows the beat count", () => {
    render(PlotPlotlineNode, { props: { data: data() } });
    expect(screen.getByTitle("Beats").textContent).toBe("3");
  });

  it("shows an empty hint and no list when the plotline has no beats (ad-hoc)", () => {
    render(PlotPlotlineNode, { props: { data: data({ beats: [] }) } });
    expect(screen.getByText("No beats yet")).toBeTruthy();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByTitle("Beats").textContent).toBe("0");
  });

  it("renders without a colour (a colourless plotline is neutral, not broken)", () => {
    render(PlotPlotlineNode, { props: { data: data({ color: null }) } });
    expect(screen.getByText("Main plot")).toBeTruthy();
  });
});
