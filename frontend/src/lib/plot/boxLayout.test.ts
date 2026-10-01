// Pure-logic test for the box tree + layout (ADR-0097 §8, §9): what nests in what, each box's
// cards in its own order, the loose box, and the geometry the boxes get. Node-env, no DOM.
import { describe, expect, it } from "vitest";
import { CARDS_PER_ROW, CARD_HEIGHT, CARD_WIDTH, CONTAINER_HEADER, CONTAINER_PAD, DECK_SYNOPSIS_LINE_H } from "./boardGeometry";
import { LOOSE_NODE_ID, boardBoxes, deckSynopsisLines, layoutBoxes, type BoxSpec } from "./boxLayout";
import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";

function projection(over: Partial<PlotBoardProjection> = {}): PlotBoardProjection {
  return {
    board_id: "b",
    board_revision: "r",
    layout: {},
    plotlines: [],
    arcs: [],
    containers: [],
    decks: [],
    cards: [],
    diagnostics: [],
    ...over,
  };
}
const container = (id: string, parent: string | null = null) => ({ id, title: id, parent });
const deck = (id: string, parent: string | null = null, synopsis = "") => ({
  id,
  title: id,
  synopsis,
  parent,
  movable: true,
});
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
const ids = (spec: BoxSpec) => spec.cards.map((c) => c.id);
const byNode = (roots: BoxSpec[], nodeId: string): BoxSpec => {
  const find = (specs: BoxSpec[]): BoxSpec | undefined => {
    for (const s of specs) {
      if (s.nodeId === nodeId) return s;
      const inner = find(s.children);
      if (inner) return inner;
    }
    return undefined;
  };
  return find(roots)!;
};

describe("boardBoxes: the box tree", () => {
  it("draws a box for every container, empty ones included, and every deck", () => {
    const roots = boardBoxes(projection({ containers: [container("act"), container("ch", "act")], decks: [deck("d")] }));
    expect(roots.map((r) => r.nodeId)).toEqual(["container:act", "deck:d", LOOSE_NODE_ID]);
    expect(roots[0].children.map((c) => c.nodeId)).toEqual(["container:ch"]);
    expect(ids(roots[0])).toEqual([]);
  });

  it("stacks top-level boxes: containers in manuscript order, then decks, then the loose box", () => {
    const roots = boardBoxes(
      projection({
        containers: [container("a1"), container("a2")],
        decks: [deck("d1"), deck("d2")],
        cards: [card("x")],
      }),
    );
    expect(roots.map((r) => r.nodeId)).toEqual(["container:a1", "container:a2", "deck:d1", "deck:d2", LOOSE_NODE_ID]);
  });

  it("nests a deck inside its parent deck's box, children before the box's own cards", () => {
    const roots = boardBoxes(
      projection({
        decks: [deck("parent"), deck("child", "parent")],
        cards: [card("in-parent", { deck: "parent" }), card("in-child", { deck: "child" })],
      }),
    );
    expect(roots.map((r) => r.nodeId)).toEqual(["deck:parent", LOOSE_NODE_ID]);
    expect(roots[0].children.map((c) => c.nodeId)).toEqual(["deck:child"]);
    expect(ids(roots[0])).toEqual(["in-parent"]);
    expect(ids(roots[0].children[0])).toEqual(["in-child"]);
  });

  describe("a deck realized as a container (ADR-0097 §7)", () => {
    const realized = (id: string, container: string, parent: string | null = null) => ({
      ...deck(id, parent),
      realized_container: container,
    });

    it("draws no box of its own: its container's box stands for it", () => {
      const roots = boardBoxes(projection({ containers: [container("ch")], decks: [realized("d", "ch")] }));
      expect(roots.map((r) => r.nodeId)).toEqual(["container:ch", LOOSE_NODE_ID]);
    });

    it("nests its child decks inside the container box, after the container's child containers", () => {
      const roots = boardBoxes(
        projection({
          containers: [container("ch"), container("sub", "ch")],
          decks: [realized("d", "ch"), deck("child", "d")],
          cards: [card("in-child", { deck: "child" })],
        }),
      );
      expect(roots.map((r) => r.nodeId)).toEqual(["container:ch", LOOSE_NODE_ID]);
      expect(roots[0].children.map((c) => c.nodeId)).toEqual(["container:sub", "deck:child"]);
      expect(ids(roots[0].children[1])).toEqual(["in-child"]);
    });

    it("keeps its cards in the container, where they are planned", () => {
      const roots = boardBoxes(
        projection({
          containers: [container("ch")],
          decks: [realized("d", "ch")],
          cards: [card("planned", { deck: "d", container: "ch", planned_in: "ch", container_order: -0.5 })],
        }),
      );
      expect(ids(roots[0])).toEqual(["planned"]);
    });

    it("never loses a card still homed in it without a plan: it falls to the loose box", () => {
      const roots = boardBoxes(
        projection({ containers: [container("ch")], decks: [realized("d", "ch")], cards: [card("stray", { deck: "d" })] }),
      );
      expect(ids(byNode(roots, LOOSE_NODE_ID))).toEqual(["stray"]);
    });

    it("a realized deck whose container is gone is an ordinary deck box", () => {
      const roots = boardBoxes(projection({ decks: [realized("d", "gone")] }));
      expect(roots.map((r) => r.nodeId)).toEqual(["deck:d", LOOSE_NODE_ID]);
    });

    it("a deck nested in a realized deck of an unrealized parent still lands in the container box", () => {
      const roots = boardBoxes(
        projection({
          containers: [container("ch")],
          decks: [deck("top"), realized("mid", "ch", "top"), deck("leaf", "mid")],
        }),
      );
      expect(roots.map((r) => r.nodeId)).toEqual(["container:ch", "deck:top", LOOSE_NODE_ID]);
      expect(roots[0].children.map((c) => c.nodeId)).toEqual(["deck:leaf"]);
    });
  });

  it("treats a deck whose parent is not projected as top level", () => {
    const roots = boardBoxes(projection({ decks: [deck("orphan", "gone")] }));
    expect(roots.map((r) => r.nodeId)).toEqual(["deck:orphan", LOOSE_NODE_ID]);
  });

  it("orders a container's cards by container order, ties by story time", () => {
    const roots = boardBoxes(
      projection({
        containers: [container("ch")],
        cards: [
          card("late", { container: "ch", scene: "s3", container_order: 2, story_order: 0 }),
          card("tie-b", { container: "ch", scene: "s2", container_order: 1, story_order: 5 }),
          card("tie-a", { container: "ch", scene: "s1", container_order: 1, story_order: 3 }),
        ],
      }),
    );
    expect(ids(byNode(roots, "container:ch"))).toEqual(["tie-a", "tie-b", "late"]);
  });

  it("sets a planned card among the written ones by its container order (ADR-0097 §6)", () => {
    const roots = boardBoxes(
      projection({
        containers: [container("ch")],
        cards: [
          card("s2", { container: "ch", scene: "scene2", container_order: 1, story_order: 0 }),
          card("s1", { container: "ch", scene: "scene1", container_order: 0, story_order: 1 }),
          // Planned after scene 1 (half a step on), two of them ordered by story time.
          card("p2", { container: "ch", planned_in: "ch", planned_after: "scene1", container_order: 0.5, story_order: 9 }),
          card("p1", { container: "ch", planned_in: "ch", planned_after: "scene1", container_order: 0.5, story_order: 4 }),
          // Planned before the chapter's first scene.
          card("p0", { container: "ch", planned_in: "ch", container_order: -0.5, story_order: 7 }),
        ],
      }),
    );
    expect(ids(byNode(roots, "container:ch"))).toEqual(["p0", "s1", "p1", "p2", "s2"]);
  });

  it("shows a planned card in the chapter it is planned in, not its home deck", () => {
    const roots = boardBoxes(
      projection({
        containers: [container("ch")],
        decks: [deck("d")],
        cards: [card("p", { container: "ch", deck: "d", planned_in: "ch", container_order: 0.5 })],
      }),
    );
    expect(ids(byNode(roots, "container:ch"))).toEqual(["p"]);
    expect(ids(byNode(roots, "deck:d"))).toEqual([]);
  });

  it("orders a deck's and the loose box's cards by story time", () => {
    const roots = boardBoxes(
      projection({
        decks: [deck("d")],
        cards: [
          card("d2", { deck: "d", story_order: 4 }),
          card("d1", { deck: "d", story_order: 1 }),
          card("l2", { story_order: 3 }),
          card("l1", { story_order: 2 }),
        ],
      }),
    );
    expect(ids(byNode(roots, "deck:d"))).toEqual(["d1", "d2"]);
    expect(ids(byNode(roots, LOOSE_NODE_ID))).toEqual(["l1", "l2"]);
  });

  it("puts a written card in its scene's container, never its deck; a written card at the root goes loose", () => {
    const roots = boardBoxes(
      projection({
        containers: [container("ch")],
        decks: [deck("d")],
        cards: [
          card("w", { container: "ch", scene: "s1", deck: "d" }),
          card("root", { scene: "s2", deck: "d", container: null }),
          card("u", { deck: "d" }),
        ],
      }),
    );
    expect(ids(byNode(roots, "container:ch"))).toEqual(["w"]);
    expect(ids(byNode(roots, "deck:d"))).toEqual(["u"]);
    expect(ids(byNode(roots, LOOSE_NODE_ID))).toEqual(["root"]);
  });

  it("draws the loose box when it holds cards or a deck exists (somewhere to drag a card out to)", () => {
    expect(boardBoxes(projection({ decks: [deck("d")] })).map((r) => r.nodeId)).toEqual(["deck:d", LOOSE_NODE_ID]);
    expect(boardBoxes(projection({ containers: [container("a")] })).map((r) => r.nodeId)).toEqual(["container:a"]);
    // An unwritten card whose deck was deleted (a dangling home) is loose too.
    expect(boardBoxes(projection({ cards: [card("c", { deck: "gone" })] })).map((r) => r.nodeId)).toEqual([LOOSE_NODE_ID]);
  });

  // #2399: with no deck, a card planned in a chapter still needs somewhere to be dragged out
  // to — the empty loose box must already be on the board.
  it("draws the empty loose box for a planned card even when no deck exists", () => {
    const planned = projection({
      containers: [container("ch")],
      cards: [card("p", { container: "ch", planned_in: "ch", container_order: 0.5 })],
    });
    const roots = boardBoxes(planned);
    expect(roots.map((r) => r.nodeId)).toEqual(["container:ch", LOOSE_NODE_ID]);
    expect(ids(byNode(roots, LOOSE_NODE_ID))).toEqual([]);
    // Only written cards: nothing can be dropped there, so no box.
    const written = projection({
      containers: [container("ch")],
      cards: [card("w", { container: "ch", scene: "s1", container_order: 0 })],
    });
    expect(boardBoxes(written).map((r) => r.nodeId)).toEqual(["container:ch"]);
  });

  it("reserves a header line per synopsis line a deck shows, at most two", () => {
    expect(deckSynopsisLines("one\n\n  two  \nthree")).toEqual(["one", "two"]);
    const [plain, wordy] = boardBoxes(projection({ decks: [deck("a"), deck("b", null, "x\ny\nz")] }));
    expect(plain.header).toBe(CONTAINER_HEADER);
    expect(wordy.header).toBe(CONTAINER_HEADER + 2 * DECK_SYNOPSIS_LINE_H);
  });
});

describe("layoutBoxes: geometry", () => {
  const specOf = (cards: string[], children: BoxSpec[] = [], nodeId = "deck:x"): BoxSpec => ({
    nodeId,
    kind: "deck",
    ref: "x",
    header: CONTAINER_HEADER,
    cards: cards.map((id) => ({ id, height: CARD_HEIGHT })),
    children,
  });

  it("sizes a box to its contents and leaves room for one card when empty", () => {
    const { boxes } = layoutBoxes([specOf([])]);
    expect(boxes[0].rect.w).toBe(CARD_WIDTH + 2 * CONTAINER_PAD);
    expect(boxes[0].rect.h).toBe(CONTAINER_HEADER + CARD_HEIGHT + 2 * CONTAINER_PAD);
  });

  it("grows a box in both directions as its cards wrap into rows", () => {
    const one = layoutBoxes([specOf(["a"])]).boxes[0].rect;
    const row = layoutBoxes([specOf(Array.from({ length: CARDS_PER_ROW }, (_, i) => `c${i}`))]).boxes[0].rect;
    const wrapped = layoutBoxes([specOf(Array.from({ length: CARDS_PER_ROW + 1 }, (_, i) => `c${i}`))]).boxes[0].rect;
    expect(row.w).toBeGreaterThan(one.w);
    expect(row.h).toBe(one.h);
    expect(wrapped.w).toBe(row.w);
    expect(wrapped.h).toBeGreaterThan(row.h);
  });

  it("places the cards inside the box, below its header, and reports members and counts", () => {
    const outer = specOf(["own"], [specOf(["inner"], [], "deck:inner")], "deck:outer");
    const { boxes, cardAt } = layoutBoxes([outer]);
    const [parent, child] = boxes;
    expect(parent.depth).toBe(0);
    expect(child.depth).toBe(1);
    expect(parent.topLevel).toBe(true);
    expect(child.topLevel).toBe(false);
    expect(parent.memberIds).toEqual(["deck:inner", "inner", "own"]);
    expect(parent.count).toBe(2);
    // The child box sits inside the parent, the parent's own card below the child box.
    expect(child.rect.y).toBeGreaterThanOrEqual(parent.rect.y + CONTAINER_HEADER + CONTAINER_PAD);
    expect(cardAt.get("own")!.y).toBeGreaterThanOrEqual(child.rect.y + child.rect.h);
    expect(cardAt.get("own")!.y + CARD_HEIGHT).toBeLessThanOrEqual(parent.rect.y + parent.rect.h - CONTAINER_PAD);
  });

  it("honours a stored top-level position, and the rest stack around it", () => {
    const a = specOf([], [], "deck:a");
    const b = specOf([], [], "deck:b");
    const c = specOf([], [], "deck:c");
    const { boxes, stackBottom } = layoutBoxes([a, b, c], { "deck:b": { x: 900, y: 700 } });
    const at = (id: string) => boxes.find((x) => x.spec.nodeId === id)!.rect;
    expect(at("deck:b")).toMatchObject({ x: 900, y: 700 });
    // c closes ranks right below a — b left no hole in the stack.
    expect(at("deck:c").y).toBe(at("deck:a").y + at("deck:a").h + 24);
    expect(stackBottom).toBe(at("deck:c").y + at("deck:c").h + 24);
  });

  it("ignores a stored position for a nested box (it nests; only top-level boxes are placed)", () => {
    const { boxes } = layoutBoxes([specOf([], [specOf([], [], "deck:inner")], "deck:outer")], {
      "deck:inner": { x: 5000, y: 5000 },
    });
    expect(boxes[1].rect.x).toBeLessThan(1000);
  });
});
