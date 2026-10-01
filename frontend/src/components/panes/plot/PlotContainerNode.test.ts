// @vitest-environment happy-dom
// PlotContainerNode RENDER guard (ADR-0048 S7 Slice 4). A container box is
// display-only structure on the board, so it gets the same mount check as the card
// ([[reference_component_test_harness]]). No @xyflow/svelte import → mountable here.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import PlotContainerNode from "./PlotContainerNode.svelte";
import { PLOT_DECK_ACTIONS, type PlotDeckActions } from "./plotDeckActions";
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
    expect(screen.getByText("Drag a card here to take it out of its deck or chapter")).toBeInTheDocument();
    unmount();
    render(PlotContainerNode, { props: { data: data({ ...loose, count: 2 }) } });
    expect(screen.queryByText("Drag a card here to take it out of its deck or chapter")).toBeNull();
  });

  describe("a container a deck is realized as (ADR-0097 §7)", () => {
    const acts = (over: Partial<PlotDeckActions> = {}): PlotDeckActions => ({
      editingId: null,
      startRename: vi.fn(),
      finishRename: vi.fn(),
      onNewCard: vi.fn(),
      onNewDeckInside: vi.fn(),
      onRealize: vi.fn(),
      onDetach: vi.fn(),
      onOpen: vi.fn(),
      onDelete: vi.fn(),
      ...over,
    });
    const mount = (over: Partial<PlotContainerData>, actions?: PlotDeckActions) =>
      render(PlotContainerNode, {
        props: { data: data(over) },
        context: actions ? new Map([[PLOT_DECK_ACTIONS, actions]]) : undefined,
      });

    it("shows the deck menu only for a realized deck", () => {
      mount({ deckId: "plot_d1" }, acts());
      expect(screen.getByRole("button", { name: "Deck actions" })).toBeInTheDocument();
    });

    it("has no menu for an ordinary container, or without the board's actions", () => {
      mount({}, acts());
      expect(screen.queryByRole("button", { name: "Deck actions" })).toBeNull();
    });

    it("has no menu without the actions context even when a deck is realized", () => {
      mount({ deckId: "plot_d1" });
      expect(screen.queryByRole("button", { name: "Deck actions" })).toBeNull();
    });

    it("offers the deck's items and routes each with the DECK's id", async () => {
      const a = acts();
      mount({ deckId: "plot_d1" }, a);
      await fireEvent.click(screen.getByRole("button", { name: "Deck actions" }));
      expect(screen.getAllByRole("menuitem").map((el) => el.textContent?.trim())).toEqual([
        "New card",
        "New deck inside",
        "Rename",
        "Open deck",
        "Detach from deck",
        "Delete deck",
      ]);
      await fireEvent.click(screen.getByRole("menuitem", { name: "Detach from deck" }));
      expect(a.onDetach).toHaveBeenCalledWith("plot_d1");
    });

    it("renames through the deck when the board starts the edit", async () => {
      const a = acts({ editingId: "plot_d1" });
      mount({ deckId: "plot_d1" }, a);
      const input = screen.getByLabelText("Name") as HTMLInputElement;
      await fireEvent.input(input, { target: { value: "Chapter One" } });
      await fireEvent.blur(input);
      expect(a.finishRename).toHaveBeenCalledWith("plot_d1", "Chapter One");
    });
  });

  it("renders a nested (chapter) box", () => {
    render(PlotContainerNode, { props: { data: data({ title: "Chapter 3", level: 1, count: 2 }) } });
    expect(screen.getByText("Chapter 3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
