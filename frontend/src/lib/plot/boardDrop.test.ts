// Pure-logic test for the card-drop hit-test (ADR-0097 §8): which box the pointer is over (the
// deepest), which slot among its cards, what the insertion bar and the `place` call are, and
// what a release does for each kind of box and card. Node-env, no DOM.
import { describe, expect, it } from "vitest";
import {
  WRITTEN_CARD_NOTICE,
  dropBoxesFrom,
  hitTestDrop,
  planDrop,
  type DropBox,
  type DropCard,
} from "./boardDrop";
import { buildBoardNodes } from "./plotBoardLayout";
import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";

const rect = (x: number, y: number, w: number, h: number) => ({ x, y, w, h });
const dropCard = (id: string, x: number, movable = true): DropCard => ({ id, rect: rect(x, 100, 100, 80), storyMovable: movable });
const box = (id: string, kind: DropBox["kind"], depth: number, r: DropBox["rect"], cards: DropCard[] = []): DropBox => ({
  id,
  kind,
  ref: id.replace(/^\w+:/, ""),
  depth,
  headerH: 32,
  rect: r,
  cards,
});

describe("hitTestDrop", () => {
  const outer = box("deck:outer", "deck", 0, rect(0, 0, 1000, 400), [dropCard("o1", 20)]);
  const inner = box("deck:inner", "deck", 1, rect(300, 50, 400, 300), [dropCard("i1", 320), dropCard("i2", 450), dropCard("i3", 580)]);

  it("picks the deepest box under the pointer", () => {
    expect(hitTestDrop([outer, inner], { x: 400, y: 120 })!.box.id).toBe("deck:inner");
    expect(hitTestDrop([outer, inner], { x: 50, y: 120 })!.box.id).toBe("deck:outer");
  });

  it("is null over no box", () => {
    expect(hitTestDrop([outer, inner], { x: 2000, y: 2000 })).toBeNull();
  });

  it("finds the slot: before a card when the pointer is left of its centre, after it otherwise", () => {
    // i2 spans x 450..550, centre 500.
    const left = hitTestDrop([inner], { x: 470, y: 140 })!;
    expect([left.index, left.afterId, left.beforeId]).toEqual([1, "i1", "i2"]);
    const right = hitTestDrop([inner], { x: 530, y: 140 })!;
    expect([right.index, right.afterId, right.beforeId]).toEqual([2, "i2", "i3"]);
  });

  it("is at the front before the first card and at the end after the last", () => {
    const front = hitTestDrop([inner], { x: 330, y: 140 })!;
    expect([front.index, front.afterId, front.beforeId]).toEqual([0, null, "i1"]);
    const end = hitTestDrop([inner], { x: 660, y: 140 })!;
    expect([end.index, end.afterId, end.beforeId]).toEqual([3, "i3", null]);
  });

  it("puts the insertion bar in the gap beside the neighbour", () => {
    const hit = hitTestDrop([inner], { x: 470, y: 140 })!;
    // Left of i2 (x 450): the bar sits just left of it, as tall as the card.
    expect(hit.bar.x).toBeLessThan(450);
    expect(hit.bar).toMatchObject({ y: 100, h: 80 });
  });

  it("targets slot 0 of an empty box", () => {
    const empty = box("deck:empty", "deck", 0, rect(0, 500, 400, 300));
    const hit = hitTestDrop([empty], { x: 100, y: 600 })!;
    expect([hit.index, hit.afterId, hit.beforeId]).toEqual([0, null, null]);
    expect(hit.bar.y).toBe(500 + 32 + 20);
  });

  it("returns a container as the target (the plan, not the hit-test, says it does nothing)", () => {
    const chapter = box("container:ch", "container", 0, rect(0, 0, 300, 300));
    expect(hitTestDrop([chapter], { x: 10, y: 10 })!.box.kind).toBe("container");
  });
});

describe("planDrop", () => {
  const deckBox = box("deck:d", "deck", 0, rect(0, 0, 600, 300), [dropCard("a", 20), dropCard("b", 150, false), dropCard("c", 280)]);
  const hit = (b: DropBox, x: number) => hitTestDrop([b], { x, y: 140 });

  it("places an unwritten card into a deck between two cards: the deck and the preceding card", () => {
    // Right of a's centre (70): between a and b.
    expect(planDrop(hit(deckBox, 100), { written: false })).toEqual({
      kind: "place",
      place: { to: { deck: "d" }, story: { after_id: "a" } },
    });
  });

  it("anchors before the first card when dropped at the front", () => {
    expect(planDrop(hit(deckBox, 30), { written: false })).toEqual({
      kind: "place",
      place: { to: { deck: "d" }, story: { before_id: "a" } },
    });
  });

  it("anchors on the nearest card the open layer owns (an inherited card is no anchor)", () => {
    // Slot 2 (between b and c): b is inherited, so the next card c is the anchor.
    expect(planDrop(hit(deckBox, 220), { written: false })).toEqual({
      kind: "place",
      place: { to: { deck: "d" }, story: { before_id: "c" } },
    });
  });

  it("places by membership alone into an empty deck or the loose box", () => {
    const empty = box("deck:e", "deck", 0, rect(0, 0, 400, 300));
    expect(planDrop(hit(empty, 100), { written: false })).toEqual({ kind: "place", place: { to: { deck: "e" } } });
    const loose = box("loose", "loose", 0, rect(0, 0, 400, 300));
    expect(planDrop(hit(loose, 100), { written: false })).toEqual({ kind: "place", place: { to: { loose: true } } });
  });

  it("refuses a written card with the notice", () => {
    expect(planDrop(hit(deckBox, 100), { written: true })).toEqual({ kind: "refuse", message: WRITTEN_CARD_NOTICE });
    expect(WRITTEN_CARD_NOTICE).toBe("This card shows by its scene; detach it first.");
  });

  it("does nothing onto a manuscript container, or nowhere", () => {
    const chapter = box("container:ch", "container", 0, rect(0, 0, 400, 300));
    expect(planDrop(hit(chapter, 100), { written: false })).toEqual({ kind: "none" });
    expect(planDrop(null, { written: false })).toEqual({ kind: "none" });
  });
});

describe("dropBoxesFrom (over real nodes)", () => {
  const card = (id: string, over: Partial<PlotBoardCard> = {}): PlotBoardCard => ({
    id,
    title: id,
    synopsis: "",
    plotline: null,
    scene: null,
    container: null,
    deck: null,
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
    containers: [{ id: "ch", title: "Chapter", parent: null }],
    decks: [{ id: "d", title: "Deck", synopsis: "", parent: null, movable: true }],
    cards: [
      card("w", { container: "ch", scene: "s", sequence: 0, story_order: 0 }),
      card("u1", { deck: "d", story_order: 1 }),
      card("u2", { deck: "d", story_order: 2 }),
    ],
    diagnostics: [],
  };

  it("reads each box's cards off the nodes and leaves the dragged card out", () => {
    const nodes = buildBoardNodes(proj);
    const boxes = dropBoxesFrom(nodes, "u1");
    expect(boxes.map((b) => [b.id, b.kind, b.cards.map((c) => c.id)])).toEqual([
      ["container:ch", "container", ["w"]],
      ["deck:d", "deck", ["u2"]],
      ["loose", "loose", []],
    ]);
    // The pointer over u2's box finds the deck, not the chapter.
    const u2 = nodes.find((n) => n.id === "u2")!;
    const hit = hitTestDrop(boxes, { x: u2.position.x + 5, y: u2.position.y + 5 })!;
    expect(hit.box.id).toBe("deck:d");
  });

});
