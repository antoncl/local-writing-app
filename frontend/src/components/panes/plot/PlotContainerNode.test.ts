// @vitest-environment happy-dom
// PlotContainerNode RENDER guard (ADR-0048 S7 Slice 4). A container box is
// display-only structure on the board, so it gets the same mount check as the card
// ([[reference_component_test_harness]]). No @xyflow/svelte import → mountable here.
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import PlotContainerNode from "./PlotContainerNode.svelte";
import type { PlotContainerData } from "@/lib/plot/plotBoardLayout";

const data = (over: Partial<PlotContainerData> = {}): PlotContainerData => ({
  title: "Act I",
  count: 4,
  level: 0,
  // Carried by the plotContainer node type for the resize handle on the flow wrapper
  // (#878); the presentational node under test ignores them.
  containerId: "node_act",
  minWidth: 250,
  minHeight: 170,
  ...over,
});

describe("PlotContainerNode", () => {
  it("renders the container title and its card count", () => {
    render(PlotContainerNode, { props: { data: data() } });
    expect(screen.getByText("Act I")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("renders a nested (chapter) box", () => {
    render(PlotContainerNode, { props: { data: data({ title: "Chapter 3", level: 1, count: 2 }) } });
    expect(screen.getByText("Chapter 3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
