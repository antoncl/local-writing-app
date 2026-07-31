// @vitest-environment happy-dom
// PlotLaneNode RENDER guard (ADR-0048 S7b). A lane header is display-only content
// on the board, so it gets the same mount check as the card
// ([[reference_component_test_harness]]). No @xyflow/svelte import → mountable here.
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import PlotLaneNode from "./PlotLaneNode.svelte";
import type { PlotLaneData } from "@/lib/plot/plotBoardLayout";

const data = (over: Partial<PlotLaneData> = {}): PlotLaneData => ({
  title: "Main romance",
  color: null,
  count: 3,
  ...over,
});

describe("PlotLaneNode", () => {
  it("renders the plotline name and its card count", () => {
    render(PlotLaneNode, { props: { data: data() } });
    expect(screen.getByText("Main romance")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders the Unassigned lane header", () => {
    render(PlotLaneNode, { props: { data: data({ title: "Unassigned", color: null, count: 1 }) } });
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
  });
});
