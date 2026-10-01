// Dropping a card on the board (ADR-0097 §8) — pure. While a card is dragged, the board
// asks two questions of where the pointer is: which box is it over (the DEEPEST one — a
// deck inside a deck beats the outer deck), and where among that box's cards would the
// card land. The answer drives the insertion bar; on release it becomes the `place` call.
// SvelteFlow is not headless-testable, so the geometry is here and the canvas only feeds
// it the pointer in flow coordinates.

import type { StoryAnchor, PlaceRequest } from "@/lib/api/plot";
import type { BoardXY } from "@/lib/types";
import { CARD_GAP_X, CARD_HEIGHT, CARD_WIDTH, CONTAINER_PAD, type Box } from "./boardGeometry";
import { isBoxNode, type PlotBoardNode, type PlotBoxData, type PlotContainerData, type PlotDeckData } from "./plotBoardLayout";
import type { BoxKind } from "./boxLayout";

export type DropCard = { id: string; rect: Box; storyMovable: boolean };
export type DropBox = {
  id: string;
  kind: BoxKind;
  ref: string;
  depth: number;
  headerH: number;
  rect: Box;
  cards: DropCard[];
};

/** Where the dragged card would land: the box, the slot among the box's cards (the dragged
 *  card itself excluded), the cards either side of the slot, and the insertion bar in flow
 *  coordinates. */
export type DropTarget = {
  box: DropBox;
  index: number;
  beforeId: string | null;
  afterId: string | null;
  bar: Box;
};

const BAR_WIDTH = 4;

const contains = (r: Box, p: BoardXY): boolean => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
const centre = (r: Box): BoardXY => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });

/** The boxes on the board as drop targets, read off the live nodes (a card's rect is its
 *  node's current spot, so a flowed card is where it is drawn). The dragged card is left
 *  out of every box, so the slot is among the cards that REMAIN. */
export function dropBoxesFrom(nodes: readonly PlotBoardNode[], draggedId: string): DropBox[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const boxes: DropBox[] = [];
  for (const node of nodes) {
    if (!isBoxNode(node)) continue;
    const data = node.data as PlotBoxData;
    const ref = node.type === "plotDeck" ? (node.data as PlotDeckData).deckId : (node.data as PlotContainerData).containerId;
    const cards: DropCard[] = [];
    for (const cardId of data.cardIds) {
      const card = byId.get(cardId);
      if (!card || card.id === draggedId) continue;
      cards.push({
        id: card.id,
        rect: { x: card.position.x, y: card.position.y, w: card.width ?? CARD_WIDTH, h: card.height ?? CARD_HEIGHT },
        storyMovable: (card.data as { storyMovable?: boolean }).storyMovable === true,
      });
    }
    boxes.push({
      id: node.id,
      kind: data.boxKind,
      ref,
      depth: data.depth,
      headerH: data.headerH,
      rect: { x: node.position.x, y: node.position.y, w: node.width ?? 0, h: node.height ?? 0 },
      cards,
    });
  }
  return boxes;
}

/** The target under `point`: the deepest box containing it (the smaller one on a tie),
 *  and the slot among its cards — the card whose centre is nearest, the card landing
 *  before it when the pointer is left of that centre, after it otherwise (reading order).
 *  Null when the pointer is over no box. */
export function hitTestDrop(boxes: readonly DropBox[], point: BoardXY): DropTarget | null {
  const over = boxes
    .filter((b) => contains(b.rect, point))
    .sort((a, b) => b.depth - a.depth || a.rect.w * a.rect.h - b.rect.w * b.rect.h)[0];
  if (!over) return null;
  const { cards } = over;
  if (cards.length === 0) {
    const bar = { x: over.rect.x + CONTAINER_PAD - BAR_WIDTH, y: over.rect.y + over.headerH + CONTAINER_PAD, w: BAR_WIDTH, h: CARD_HEIGHT };
    return { box: over, index: 0, beforeId: null, afterId: null, bar };
  }
  let nearest = 0;
  let best = Infinity;
  cards.forEach((card, i) => {
    const c = centre(card.rect);
    const d = Math.hypot(c.x - point.x, c.y - point.y);
    if (d < best) {
      best = d;
      nearest = i;
    }
  });
  const ref = cards[nearest].rect;
  const before = point.x < centre(ref).x;
  const index = before ? nearest : nearest + 1;
  const bar = { x: (before ? ref.x - CARD_GAP_X / 2 : ref.x + ref.w + CARD_GAP_X / 2) - BAR_WIDTH / 2, y: ref.y, w: BAR_WIDTH, h: ref.h };
  return { box: over, index, beforeId: cards[index]?.id ?? null, afterId: cards[index - 1]?.id ?? null, bar };
}

/** The story-time neighbour a card dropped at `index` takes: right after the card before
 *  the slot, else right before the one after it. Only a card the open layer owns can be an
 *  anchor (the backend refuses an inherited one), so the nearest movable card wins; null
 *  when the box holds none — an empty box places by membership alone. */
function storyAnchorAt(cards: readonly DropCard[], index: number): StoryAnchor | null {
  const prev = cards[index - 1];
  const next = cards[index];
  if (prev?.storyMovable) return { after_id: prev.id };
  if (next?.storyMovable) return { before_id: next.id };
  for (let i = index - 2; i >= 0; i--) if (cards[i].storyMovable) return { after_id: cards[i].id };
  for (let i = index + 1; i < cards.length; i++) if (cards[i].storyMovable) return { before_id: cards[i].id };
  return null;
}

export const WRITTEN_CARD_NOTICE = "This card shows by its scene; detach it first.";

export type DropPlan =
  | { kind: "none" }
  | { kind: "refuse"; message: string }
  | { kind: "place"; place: PlaceRequest };

/** What releasing the card there does. Into a deck or the loose area, an unwritten card
 *  takes that home and its slot in story time; a written card shows by its scene, so it is
 *  refused with a line saying so. Onto a manuscript container, or nowhere, nothing —
 *  planning a card in a chapter is a later slice. */
export function planDrop(target: DropTarget | null, card: { written: boolean }): DropPlan {
  if (!target || target.box.kind === "container") return { kind: "none" };
  if (card.written) return { kind: "refuse", message: WRITTEN_CARD_NOTICE };
  const to = target.box.kind === "deck" ? { deck: target.box.ref } : { loose: true as const };
  const story = storyAnchorAt(target.box.cards, target.index);
  return { kind: "place", place: story ? { to, story } : { to } };
}

