// The board's drag gestures against a fake host (ADR-0097 §8, §9): SvelteFlow isn't
// headless-testable, so the controller talks to the canvas through a narrow host and this
// drives it the way the three drag callbacks would.
import { describe, expect, it, vi } from "vitest";
import { BoardDragController, type BoardDragHost } from "./boardDragController";
import { buildBoardNodes, type PlotBoardNode } from "./plotBoardLayout";
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
  containers: [{ id: "ch", title: "Chapter 1", parent: null }],
  decks: [{ id: "d", title: "Deck", synopsis: "", parent: null, movable: true }],
  cards: [
    card("w", { container: "ch", scene: "s1", sequence: 0, story_order: 0 }),
    card("u1", { deck: "d", story_order: 1 }),
    card("u2", { deck: "d", story_order: 2 }),
    card("free", { story_order: 3 }),
  ],
  diagnostics: [],
};

function harness() {
  const state = { nodes: buildBoardNodes(proj) as PlotBoardNode[] };
  const recorded: Array<{ undo: () => void; redo: () => void }> = [];
  const log: string[] = [];
  const bars: Array<unknown> = [];
  const host: BoardDragHost = {
    get nodes() {
      return state.nodes;
    },
    set nodes(next) {
      state.nodes = next;
    },
    port: {
      getNodes: () => state.nodes,
      setNodes: (n) => (state.nodes = n),
      getEdges: () => [],
      setEdges: () => {},
    },
    undo: {
      dragStart: vi.fn(),
      dragStop: vi.fn(),
      record: (c) => recorded.push(c as { undo: () => void; redo: () => void }),
    },
    setDropBar: (bar) => bars.push(bar),
    setDragging: (on) => log.push(`dragging:${on}`),
    pinPosition: (id) => log.push(`pin:${id}`),
    rebuild: () => {
      log.push("rebuild");
      state.nodes = buildBoardNodes(proj);
    },
    focusBoard: () => log.push("focus"),
    toFlow: (screen) => screen, // 1:1
    placeCard: vi.fn(async () => {}),
    moveScene: vi.fn(async () => {}),
    say: vi.fn(),
    fail: vi.fn(),
  };
  const controller = new BoardDragController(host);
  const node = (id: string) => state.nodes.find((n) => n.id === id)!;
  const at = (x: number, y: number) => ({ clientX: x, clientY: y }) as MouseEvent;
  return { controller, host, state, recorded, log, bars, node, at };
}

const centreOf = (n: PlotBoardNode) => ({ x: n.position.x + (n.width ?? 0) / 2, y: n.position.y + (n.height ?? 0) / 2 });

describe("card drag", () => {
  it("shows the bar as an overlay only where a drop would act, never touching the node array", () => {
    const h = harness();
    const before = h.state.nodes;
    h.controller.onStart({ nodes: [h.node("u1")] });
    expect(h.state.nodes).toBe(before);

    // Over the deck's other card: a drop would place it, so the bar shows.
    const c = centreOf(h.node("u2"));
    h.controller.onDrag({ event: h.at(c.x, c.y), nodes: [h.node("u1")] });
    expect(h.bars.at(-1)).toMatchObject({ w: expect.any(Number) });
    // Another frame over the same slot sets nothing new.
    const count = h.bars.length;
    h.controller.onDrag({ event: h.at(c.x, c.y), nodes: [h.node("u1")] });
    expect(h.bars).toHaveLength(count);
    // Over nowhere: nothing would happen, so no bar.
    h.controller.onDrag({ event: h.at(-5000, -5000), nodes: [h.node("u1")] });
    expect(h.bars.at(-1)).toBeNull();
    // The bound array is the SAME array through every frame.
    expect(h.state.nodes).toBe(before);
  });

  it("drops into a deck as ONE recorded place call, then snaps back into the flow", async () => {
    const h = harness();
    h.controller.onStart({ nodes: [h.node("free")] });
    const u2 = h.node("u2");
    // Right of u2's centre: after u2, in the deck.
    h.controller.onDrag({ event: h.at(u2.position.x + (u2.width ?? 0) - 5, u2.position.y + 10), nodes: [h.node("free")] });
    h.controller.onStop({ nodes: [h.node("free")] });
    expect(h.host.placeCard).toHaveBeenCalledTimes(1);
    expect(h.host.placeCard).toHaveBeenCalledWith("free", { to: { deck: "d" }, story: { after_id: "u2" } });
    expect(h.log).toContain("rebuild");
    expect(h.bars.at(-1)).toBeNull();
    expect(h.host.undo.dragStop).not.toHaveBeenCalled(); // a card drag never records a position
  });

  it("refuses a written card with a notice and calls nothing", () => {
    const h = harness();
    h.controller.onStart({ nodes: [h.node("w")] });
    const u1 = h.node("u1");
    h.controller.onDrag({ event: h.at(u1.position.x + 5, u1.position.y + 5), nodes: [h.node("w")] });
    h.controller.onStop({ nodes: [h.node("w")] });
    expect(h.host.say).toHaveBeenCalledWith("This card shows by its scene; detach it first.");
    expect(h.host.placeCard).not.toHaveBeenCalled();
    expect(h.log).toContain("rebuild");
  });

  it("plans an unwritten card dropped on a chapter, after the written card before the slot", () => {
    const h = harness();
    h.controller.onStart({ nodes: [h.node("u1")] });
    const w = h.node("w");
    // Right of the written card's centre: after it, in the chapter.
    h.controller.onDrag({ event: h.at(w.position.x + (w.width ?? 0) - 5, w.position.y + 10), nodes: [h.node("u1")] });
    expect(h.bars.at(-1)).not.toBeNull(); // a chapter is a drop target
    h.controller.onStop({ nodes: [h.node("u1")] });
    expect(h.host.placeCard).toHaveBeenCalledWith("u1", { to: { planned_in: "ch", planned_after: "s1" } });
    expect(h.host.moveScene).not.toHaveBeenCalled();
  });

  it("moves a written card's scene when it is dropped on a chapter", () => {
    const h = harness();
    h.controller.onStart({ nodes: [h.node("w")] });
    const chapter = h.node("container:ch");
    h.controller.onDrag({ event: h.at(chapter.position.x + 5, chapter.position.y + 5), nodes: [h.node("w")] });
    h.controller.onStop({ nodes: [h.node("w")] });
    expect(h.host.moveScene).toHaveBeenCalledWith("s1", "ch", null);
    expect(h.host.placeCard).not.toHaveBeenCalled();
    expect(h.log).toContain("rebuild");
  });

  it("does nothing when released over nowhere", () => {
    const h = harness();
    h.controller.onStart({ nodes: [h.node("u1")] });
    h.controller.onDrag({ event: h.at(-5000, -5000), nodes: [h.node("u1")] });
    h.controller.onStop({ nodes: [h.node("u1")] });
    expect(h.host.placeCard).not.toHaveBeenCalled();
    expect(h.host.say).not.toHaveBeenCalled();
  });

  it("reports a failed place through the host", async () => {
    const h = harness();
    vi.mocked(h.host.placeCard).mockRejectedValueOnce(new Error("409"));
    h.controller.onStart({ nodes: [h.node("free")] });
    const u2 = h.node("u2");
    h.controller.onDrag({ event: h.at(u2.position.x + 5, u2.position.y + 5), nodes: [h.node("free")] });
    h.controller.onStop({ nodes: [h.node("free")] });
    await Promise.resolve();
    await Promise.resolve();
    expect(h.host.fail).toHaveBeenCalled();
  });
});

describe("box drag", () => {
  it("carries the contents live, then pins ONLY the box as one undo step", () => {
    const h = harness();
    const deck = h.node("deck:d");
    const startCard = { ...h.node("u1").position };
    h.controller.onStart({ nodes: [deck] });
    const dragged = { ...deck, position: { x: deck.position.x + 200, y: deck.position.y + 50 } };
    h.state.nodes = h.state.nodes.map((n) => (n.id === deck.id ? dragged : n));
    h.controller.onDrag({ event: h.at(0, 0), nodes: [dragged] });
    expect(h.node("u1").position).toEqual({ x: startCard.x + 200, y: startCard.y + 50 });

    h.controller.onStop({ nodes: [dragged] });
    expect(h.log.filter((l) => l.startsWith("pin:"))).toEqual(["pin:deck:d"]);
    expect(h.recorded).toHaveLength(1);
    expect(h.log.at(-1)).toBe("rebuild");
  });

  it("records nothing for a drag that went nowhere", () => {
    const h = harness();
    const deck = h.node("deck:d");
    h.controller.onStart({ nodes: [deck] });
    h.controller.onStop({ nodes: [deck] });
    expect(h.recorded).toEqual([]);
    expect(h.log.filter((l) => l.startsWith("pin:"))).toEqual([]);
  });

  it("undo and redo re-derive the contents around the restored position", () => {
    const h = harness();
    const deck = h.node("deck:d");
    h.controller.onStart({ nodes: [deck] });
    const dragged = { ...deck, position: { x: 400, y: 400 } };
    h.state.nodes = h.state.nodes.map((n) => (n.id === deck.id ? dragged : n));
    h.controller.onStop({ nodes: [dragged] });
    h.log.length = 0;
    h.recorded[0].undo();
    h.recorded[0].redo();
    expect(h.log.filter((l) => l === "rebuild")).toHaveLength(2);
  });
});

describe("plotline and arc drags", () => {
  it("use the plain position drag and pin the node", () => {
    const h = harness();
    const line = { id: "plot_p", type: "plotPlotline", position: { x: 1, y: 2 }, data: {} } as PlotBoardNode;
    h.controller.onStart({ nodes: [line] });
    expect(h.host.undo.dragStart).toHaveBeenCalledWith([line]);
    h.controller.onStop({ nodes: [line] });
    expect(h.host.undo.dragStop).toHaveBeenCalledWith([line]);
    expect(h.log).toContain("pin:plot_p");
  });
});
