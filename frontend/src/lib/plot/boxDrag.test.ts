// Pure-logic test for the box drag (ADR-0097 §8; #877): a top-level box carries its contents.
import { describe, expect, it } from "vitest";
import { followBoxDrag, startBoxDrag } from "./boxDrag";
import { buildBoardNodes, movableNodePositions } from "./plotBoardLayout";
import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";

const card = (id: string, over: Partial<PlotBoardCard> = {}): PlotBoardCard => ({
  id,
  title: id,
  synopsis: "",
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
  story_order: 0,
  story_movable: true,
  ...over,
});
const proj: PlotBoardProjection = {
  board_id: "b",
  board_revision: "r",
  layout: {},
  plotlines: [],
  arcs: [],
  containers: [],
  decks: [
    { id: "outer", title: "Outer", synopsis: "", parent: null, movable: true },
    { id: "inner", title: "Inner", synopsis: "", parent: "outer", movable: true },
    { id: "other", title: "Other", synopsis: "", parent: null, movable: true },
  ],
  cards: [card("a", { deck: "outer" }), card("b", { deck: "inner" }), card("c", { deck: "other" })],
  diagnostics: [],
};

describe("box drag", () => {
  it("translates the dragged box's nested boxes and cards by its delta, and nothing else", () => {
    const nodes = buildBoardNodes(proj);
    const outer = nodes.find((n) => n.id === "deck:outer")!;
    const drag = startBoxDrag(nodes, outer);
    const dragged = { ...outer, position: { x: outer.position.x + 100, y: outer.position.y + 40 } };
    const after = followBoxDrag(nodes, drag, dragged);
    const moved = (id: string) => {
      const before = nodes.find((n) => n.id === id)!.position;
      const now = after.find((n) => n.id === id)!.position;
      return { x: now.x - before.x, y: now.y - before.y };
    };
    expect(moved("deck:inner")).toEqual({ x: 100, y: 40 });
    expect(moved("a")).toEqual({ x: 100, y: 40 });
    expect(moved("b")).toEqual({ x: 100, y: 40 });
    // A neighbouring box and its card stay; the dragged node keeps SvelteFlow's own position.
    expect(moved("deck:other")).toEqual({ x: 0, y: 0 });
    expect(moved("c")).toEqual({ x: 0, y: 0 });
    expect(after.find((n) => n.id === "deck:outer")!.position).toEqual(outer.position);
  });

  it("is absolute, not incremental: repeated frames cannot drift", () => {
    const nodes = buildBoardNodes(proj);
    const outer = nodes.find((n) => n.id === "deck:outer")!;
    const drag = startBoxDrag(nodes, outer);
    const frame = (dx: number) => followBoxDrag(nodes, drag, { ...outer, position: { x: outer.position.x + dx, y: outer.position.y } });
    const final = followBoxDrag(frame(30), drag, { ...outer, position: { x: outer.position.x + 50, y: outer.position.y } });
    expect(final.find((n) => n.id === "a")!.position.x).toBe(nodes.find((n) => n.id === "a")!.position.x + 50);
  });

  it("stores only the box: the move persists as one position, the contents re-derive from it", () => {
    const nodes = buildBoardNodes(proj);
    const outer = nodes.find((n) => n.id === "deck:outer")!;
    const moved = nodes.map((n) => (n.id === outer.id ? { ...n, position: { x: 700, y: 300 } } : n));
    expect(movableNodePositions(moved)["deck:outer"]).toEqual({ x: 700, y: 300 });
    const rebuilt = buildBoardNodes(proj, { "deck:outer": { x: 700, y: 300 } });
    const a = rebuilt.find((n) => n.id === "a")!.position;
    expect(a.x).toBeGreaterThan(700);
    expect(a.y).toBeGreaterThan(300);
  });
});

describe("the loose box (the drop target for a card dragged out of a deck)", () => {
  it("is already in the layout when the board has a deck, even with no loose cards", () => {
    const nodes = buildBoardNodes({ ...proj, cards: proj.cards.filter((c) => c.deck) });
    const loose = nodes.find((n) => n.id === "loose")!;
    expect(loose).toBeDefined();
    expect((loose.data as { cardIds: string[]; count: number }).cardIds).toEqual([]);
    const bottom = Math.max(...nodes.filter((n) => n.type === "plotDeck").map((n) => n.position.y + n.height!));
    expect(loose.position.y).toBeGreaterThan(bottom);
  });

  it("is not drawn without loose cards or decks", () => {
    expect(buildBoardNodes({ ...proj, decks: [], cards: [] }).some((n) => n.id === "loose")).toBe(false);
  });
});
