// @vitest-environment happy-dom
// PlotDeckNode RENDER guard (ADR-0097 §8). A deck's box shows its title, the first two lines
// of its synopsis and a menu; an inherited deck offers Open alone. No @xyflow/svelte import →
// mountable here ([[reference_component_test_harness]]).
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import PlotDeckNode from "./PlotDeckNode.svelte";
import { PLOT_DECK_ACTIONS, type PlotDeckActions } from "./plotDeckActions";
import type { PlotDeckData } from "@/lib/plot/plotBoardLayout";

const data = (over: Partial<PlotDeckData> = {}): PlotDeckData => ({
  title: "Mara's backstory",
  synopsis: "Seven years under the guild.\nThe fire.\nThe flight.",
  deckId: "plot_d1",
  movable: true,
  boxKind: "deck",
  depth: 0,
  topLevel: true,
  headerH: 68,
  cardIds: [],
  memberIds: [],
  count: 3,
  ...over,
});

function actions(over: Partial<PlotDeckActions> = {}): PlotDeckActions {
  return {
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
  };
}

const mount = (d: PlotDeckData, acts?: PlotDeckActions) =>
  render(PlotDeckNode, { props: { id: `deck:${d.deckId}`, data: d }, context: acts ? new Map([[PLOT_DECK_ACTIONS, acts]]) : undefined });

describe("PlotDeckNode", () => {
  it("shows the title, the first two synopsis lines and the card count", () => {
    mount(data());
    expect(screen.getByText("Mara's backstory")).toBeInTheDocument();
    expect(screen.getByText("Seven years under the guild.")).toBeInTheDocument();
    expect(screen.getByText("The fire.")).toBeInTheDocument();
    expect(screen.queryByText("The flight.")).toBeNull();
    expect(screen.getByText(/3/)).toBeInTheDocument();
  });

  it("has no menu without the actions context (read-only box)", () => {
    mount(data());
    expect(screen.queryByRole("button", { name: "Deck actions" })).toBeNull();
  });

  it("offers New card, New deck inside, Rename, Open and Delete on an owned deck", async () => {
    const acts = actions();
    mount(data(), acts);
    await fireEvent.click(screen.getByRole("button", { name: "Deck actions" }));
    const items = screen.getAllByRole("menuitem").map((el) => el.textContent?.trim());
    expect(items).toEqual(["New card", "New deck inside", "Rename", "Open", "Delete"]);
    await fireEvent.click(screen.getByRole("menuitem", { name: /New card/ }));
    expect(acts.onNewCard).toHaveBeenCalledWith("plot_d1");
  });

  it("routes each item to its action with the deck id", async () => {
    const acts = actions();
    mount(data(), acts);
    for (const [label, spy] of [
      ["New deck inside", acts.onNewDeckInside],
      ["Rename", acts.startRename],
      ["Open", acts.onOpen],
      ["Delete", acts.onDelete],
    ] as const) {
      await fireEvent.click(screen.getByRole("button", { name: "Deck actions" }));
      await fireEvent.click(screen.getByRole("menuitem", { name: new RegExp(label) }));
      expect(spy).toHaveBeenCalledWith("plot_d1");
    }
  });

  it("offers Realize as <level name> only when the level list allows one, and routes it", async () => {
    const acts = actions();
    const { unmount } = mount(data({ realizeLevel: "Chapter" }), acts);
    await fireEvent.click(screen.getByRole("button", { name: "Deck actions" }));
    expect(screen.getAllByRole("menuitem").map((el) => el.textContent?.trim())).toEqual([
      "New card",
      "New deck inside",
      "Rename",
      "Realize as Chapter",
      "Open",
      "Delete",
    ]);
    await fireEvent.click(screen.getByRole("menuitem", { name: "Realize as Chapter" }));
    expect(acts.onRealize).toHaveBeenCalledWith("plot_d1");
    unmount();
    mount(data({ realizeLevel: null }), actions());
    await fireEvent.click(screen.getByRole("button", { name: "Deck actions" }));
    expect(screen.queryByRole("menuitem", { name: /Realize/ })).toBeNull();
  });

  it("never offers Realize on an inherited deck", async () => {
    mount(data({ movable: false, realizeLevel: "Chapter" }), actions());
    await fireEvent.click(screen.getByRole("button", { name: "Deck actions" }));
    expect(screen.queryByRole("menuitem", { name: /Realize/ })).toBeNull();
  });

  it("hides every edit on an inherited deck: Open alone", async () => {
    mount(data({ movable: false }), actions());
    await fireEvent.click(screen.getByRole("button", { name: "Deck actions" }));
    expect(screen.getAllByRole("menuitem").map((el) => el.textContent?.trim())).toEqual(["Open"]);
  });

  it("edits the title inline when the board says so, committing a changed name", async () => {
    const acts = actions({ editingId: "plot_d1" });
    mount(data(), acts);
    const input = screen.getByLabelText("Deck name") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "Mara's past" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await fireEvent.blur(input);
    expect(acts.finishRename).toHaveBeenCalledWith("plot_d1", "Mara's past");
  });

  it("abandons the edit on Escape and on an unchanged title", async () => {
    const acts = actions({ editingId: "plot_d1" });
    mount(data(), acts);
    const input = screen.getByLabelText("Deck name");
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(acts.finishRename).toHaveBeenCalledWith("plot_d1", null);
  });

  it("does not edit an inherited deck even if asked", () => {
    mount(data({ movable: false }), actions({ editingId: "plot_d1" }));
    expect(screen.queryByLabelText("Deck name")).toBeNull();
  });
});
