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
  containerId: "node_act",
  // What every box node carries (ADR-0097 §8); the presentational node ignores them.
  boxKind: "container",
  depth: 0,
  topLevel: true,
  headerH: 32,
  cardIds: [],
  memberIds: [],
  ...over,
});

describe("PlotContainerNode", () => {
  it("renders the container title and its card count", () => {
    render(PlotContainerNode, { props: { data: data() } });
    expect(screen.getByText("Act I")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("renders the Loose cards box under its own title", () => {
    render(PlotContainerNode, { props: { data: data({ title: "Loose cards", boxKind: "loose", containerId: "", count: 3 }) } });
    expect(screen.getByText("Loose cards")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("hints at what the empty Loose cards box is for, and only while it is empty", () => {
    const loose = { title: "Loose cards", boxKind: "loose" as const, containerId: "" };
    const { unmount } = render(PlotContainerNode, { props: { data: data({ ...loose, count: 0 }) } });
    expect(screen.getByText("Drag a card here to take it out of its deck")).toBeInTheDocument();
    unmount();
    render(PlotContainerNode, { props: { data: data({ ...loose, count: 2 }) } });
    expect(screen.queryByText("Drag a card here to take it out of its deck")).toBeNull();
  });

  it("renders a nested (chapter) box", () => {
    render(PlotContainerNode, { props: { data: data({ title: "Chapter 3", level: 1, count: 2 }) } });
    expect(screen.getByText("Chapter 3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
