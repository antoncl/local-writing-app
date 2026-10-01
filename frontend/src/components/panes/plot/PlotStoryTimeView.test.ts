// @vitest-environment happy-dom
// PlotStoryTimeView RENDER + wiring guard (ADR-0097 §8). The view DISPLAYS cards, so it
// needs a mount test asserting they render in story order; plus the drop wiring (the
// half of the target decides before / after), that an inherited card is neither draggable
// nor a drop target, and the late-cause pill. Plain DOM — no @xyflow/svelte.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotStoryTimeView from "./PlotStoryTimeView.svelte";
import { PLOT_CARD_ACTIONS, type PlotCardActions } from "./plotCardActions";
import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";

const card = (id: string, story_order: number, over: Partial<PlotBoardCard> = {}): PlotBoardCard => ({
  id,
  title: `Title ${id}`,
  synopsis: `Synopsis ${id}`,
  plotline: null,
  scene: null,
  container: null,
  deck: null,
  planned_in: null,
  planned_after: null,
  container_order: null,
  page_status: null,
  beats: [],
  sequence: null,
  causal_links: [],
  story_order,
  story_movable: true,
  ...over,
});

const projection = (cards: PlotBoardCard[]): PlotBoardProjection => ({
  board_id: "b",
  board_revision: "r",
  layout: {},
  plotlines: [],
  arcs: [],
  containers: [],
  decks: [],
  cards,
  diagnostics: [],
});

function actions(): PlotCardActions {
  return {
    onOpen: vi.fn(),
    onStoryMove: vi.fn(),
    storyAnchors: [
      { id: "a", title: "Title a" },
      { id: "b", title: "Title b" },
      { id: "c", title: "Title c" },
    ],
  } as unknown as PlotCardActions;
}

function mount(cards: PlotBoardCard[], acts = actions()) {
  render(PlotStoryTimeView, { props: { projection: projection(cards) }, context: new Map([[PLOT_CARD_ACTIONS, acts]]) });
  return acts;
}

const cardEl = (id: string) => document.querySelector(`[data-card-id="${id}"]`) as HTMLElement;

// happy-dom lays nothing out: give every card a 100px-wide box so the half test is real.
function stubBox(el: HTMLElement) {
  el.getBoundingClientRect = () => ({ left: 0, width: 100, top: 0, height: 50, right: 100, bottom: 50, x: 0, y: 0 }) as DOMRect;
}

// happy-dom's DragEvent drops clientX, so carry it on a plain event.
async function dragAt(el: HTMLElement, type: "dragover" | "drop", clientX: number) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clientX", { value: clientX });
  await fireEvent(el, event);
}

describe("PlotStoryTimeView", () => {
  it("renders every card in story order with its place pill", () => {
    mount([
      card("c", 2),
      card("a", 0, { sequence: 3 }),
      card("b", 1),
    ]);
    expect([...document.querySelectorAll("[data-card-id]")].map((e) => e.getAttribute("data-card-id"))).toEqual([
      "a",
      "b",
      "c",
    ]);
    expect(screen.getByText("Earliest")).toBeInTheDocument();
    expect(screen.getByText("Latest")).toBeInTheDocument();
    expect(screen.getByText("Scene 4")).toBeInTheDocument(); // sequence 3 → the 4th written card
    expect(screen.getAllByText("Unwritten")).toHaveLength(2);
  });

  it("says so when there are no cards", () => {
    mount([]);
    expect(screen.getByText("No cards yet.")).toBeInTheDocument();
  });

  it("opens a card from its title", async () => {
    const acts = mount([card("a", 0)]);
    await fireEvent.click(screen.getByText("Title a"));
    expect(acts.onOpen).toHaveBeenCalledWith("a");
  });

  it("a drop on the left half of a card places before it, the right half after it", async () => {
    const acts = mount([card("a", 0), card("b", 1), card("c", 2)]);
    stubBox(cardEl("b"));
    await fireEvent.dragStart(cardEl("c"));
    await dragAt(cardEl("b"), "dragover", 10);
    expect(cardEl("b").classList.contains("ins-before")).toBe(true);
    await dragAt(cardEl("b"), "drop", 10);
    expect(acts.onStoryMove).toHaveBeenLastCalledWith("c", { before_id: "b" });

    await fireEvent.dragStart(cardEl("a"));
    await dragAt(cardEl("b"), "dragover", 90);
    expect(cardEl("b").classList.contains("ins-after")).toBe(true);
    await dragAt(cardEl("b"), "drop", 90);
    expect(acts.onStoryMove).toHaveBeenLastCalledWith("a", { after_id: "b" });
  });

  it("an inherited card is not draggable and not a drop target", async () => {
    const acts = mount([card("a", 0), card("x", 1, { story_movable: false })]);
    expect(cardEl("x").getAttribute("draggable")).toBe("false");
    expect(cardEl("a").getAttribute("draggable")).toBe("true");
    stubBox(cardEl("x"));
    await fireEvent.dragStart(cardEl("a"));
    await dragAt(cardEl("x"), "dragover", 10);
    await dragAt(cardEl("x"), "drop", 10);
    expect(acts.onStoryMove).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Story time actions for Title x")).toBeNull();
  });

  it("a card dropped on itself moves nothing", async () => {
    const acts = mount([card("a", 0), card("b", 1)]);
    stubBox(cardEl("a"));
    await fireEvent.dragStart(cardEl("a"));
    await dragAt(cardEl("a"), "drop", 10);
    expect(acts.onStoryMove).not.toHaveBeenCalled();
  });

  it("shows the late-cause pill on the effect card, naming the cause", () => {
    mount([card("e", 0), card("late", 1, { causal_links: ["e"], title: "The ledger" })]);
    const pill = screen.getByText("Cause is later");
    expect(pill.getAttribute("title")).toBe("Caused by “The ledger”, which happens later");
    expect(cardEl("e").contains(pill)).toBe(true);
  });

  it("the menu moves a card Earlier / Later, hiding the item at an end", async () => {
    const acts = mount([card("a", 0), card("b", 1), card("c", 2)]);
    await fireEvent.click(screen.getByLabelText("Story time actions for Title a"));
    expect(screen.queryByRole("menuitem", { name: "Earlier in story time" })).toBeNull();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Later in story time" }));
    expect(acts.onStoryMove).toHaveBeenCalledWith("a", { after_id: "b" });
  });

  it("Place after… anchors on the picked card", async () => {
    const acts = mount([card("a", 0), card("b", 1), card("c", 2)]);
    await fireEvent.click(screen.getByLabelText("Story time actions for Title a"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Place after…" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Title c" }));
    expect(acts.onStoryMove).toHaveBeenCalledWith("a", { after_id: "c" });
  });
});
