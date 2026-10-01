// Plot-board box layout (ADR-0097 §8, §9) — pure. The board draws BOXES (one per manuscript
// container, one per deck, and a "Loose cards" box) with the cards FLOWING inside them:
// a card never has a position of its own, a box's size is whatever its contents need,
// and only the TOP-LEVEL boxes are placed by hand. `boardBoxes` reads the projection into
// the box tree (what nests in what, and each box's cards in its own order); `layoutBoxes`
// turns that tree into rectangles and card slots. `buildBoardNodes` is the only consumer
// that knows about SvelteFlow; the drop hit-test (`boardDrop.ts`) and the box drag
// (`boxDrag.ts`) read what this produces off the nodes.

import type { BoardXY, PlotBoardCard, PlotBoardProjection } from "@/lib/types";
import {
  CARD_HEIGHT,
  CARD_WIDTH,
  CONTAINER_GAP,
  CONTAINER_HEADER,
  CONTAINER_PAD,
  DECK_SYNOPSIS_LINE_H,
  DECK_SYNOPSIS_MAX_LINES,
  CARD_STEP_X,
  CARDS_PER_ROW,
  estCardHeight,
  layoutGrid,
  type Box,
} from "./boardGeometry";

export type BoxKind = "container" | "deck" | "loose";

// Flow node ids. Prefixed so a box can never collide with a card (`plot_…`) or a plotline.
export const containerNodeId = (id: string) => `container:${id}`;
export const deckNodeId = (id: string) => `deck:${id}`;
export const LOOSE_NODE_ID = "loose";

export type BoxCard = { id: string; height: number };

// One box in the tree: `ref` is the raw container / deck id (empty for the loose box),
// `children` the boxes nested directly inside, `cards` the box's OWN cards in its own order.
export type BoxSpec = {
  nodeId: string;
  kind: BoxKind;
  ref: string;
  // The title band's height: the title row, plus a deck's synopsis lines under it.
  header: number;
  cards: BoxCard[];
  children: BoxSpec[];
};

const push = <T>(map: Map<string, T[]>, key: string, value: T): void => {
  (map.get(key) ?? map.set(key, []).get(key)!).push(value);
};

/** The first lines of a deck's synopsis its box shows under the title (blank lines skipped). */
export function deckSynopsisLines(synopsis: string): string[] {
  return synopsis
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, DECK_SYNOPSIS_MAX_LINES);
}

const cardHeight = (card: PlotBoardCard): number => estCardHeight(card.title, card.synopsis, card.beats.length);

// Manuscript order, a card with no scene position last; ties by story time.
const byManuscript = (a: PlotBoardCard, b: PlotBoardCard): number =>
  (a.sequence ?? Infinity) - (b.sequence ?? Infinity) || a.story_order - b.story_order;
const byStory = (a: PlotBoardCard, b: PlotBoardCard): number => a.story_order - b.story_order;

/** The box tree for a projection, top-level boxes in stacking order: containers in
 *  manuscript order, then top-level decks by title, then the loose box (only when it has
 *  cards). A box's children come first (containers in manuscript order, then decks by
 *  title), then its own cards: manuscript order in a container, story time in a deck or
 *  the loose box. A written card belongs to its scene's container, or — its scene at the
 *  root — the loose box; an unwritten card to its home deck, else the loose box. */
export function boardBoxes(projection: PlotBoardProjection): BoxSpec[] {
  const containerById = new Map(projection.containers.map((c) => [c.id, c]));
  const deckById = new Map(projection.decks.map((d) => [d.id, d]));

  const inContainer = new Map<string, PlotBoardCard[]>();
  const inDeck = new Map<string, PlotBoardCard[]>();
  const loose: PlotBoardCard[] = [];
  for (const card of projection.cards) {
    if (card.container != null && containerById.has(card.container)) push(inContainer, card.container, card);
    else if (card.scene == null && card.deck != null && deckById.has(card.deck)) push(inDeck, card.deck, card);
    else loose.push(card);
  }
  const boxCards = (cards: PlotBoardCard[] | undefined, order: typeof byStory): BoxCard[] =>
    [...(cards ?? [])].sort(order).map((c) => ({ id: c.id, height: cardHeight(c) }));

  const childContainers = new Map<string, string[]>();
  const topContainers: string[] = [];
  for (const c of projection.containers) {
    if (c.parent == null || !containerById.has(c.parent)) topContainers.push(c.id);
    else push(childContainers, c.parent, c.id);
  }
  const childDecks = new Map<string, string[]>();
  const topDecks: string[] = [];
  for (const d of projection.decks) {
    if (d.parent == null || !deckById.has(d.parent)) topDecks.push(d.id);
    else push(childDecks, d.parent, d.id);
  }

  const deckBox = (id: string): BoxSpec => ({
    nodeId: deckNodeId(id),
    kind: "deck",
    ref: id,
    header: CONTAINER_HEADER + deckSynopsisLines(deckById.get(id)!.synopsis).length * DECK_SYNOPSIS_LINE_H,
    cards: boxCards(inDeck.get(id), byStory),
    children: (childDecks.get(id) ?? []).map(deckBox),
  });
  const containerBox = (id: string): BoxSpec => ({
    nodeId: containerNodeId(id),
    kind: "container",
    ref: id,
    header: CONTAINER_HEADER,
    cards: boxCards(inContainer.get(id), byManuscript),
    children: (childContainers.get(id) ?? []).map(containerBox),
  });

  const roots = [...topContainers.map(containerBox), ...topDecks.map(deckBox)];
  // Drawn when it holds cards, and whenever a deck exists: it is where a card dragged out of
  // a deck goes, so it must already be there when a drag starts (never added mid-gesture).
  if (loose.length > 0 || projection.decks.length > 0) {
    roots.push({ nodeId: LOOSE_NODE_ID, kind: "loose", ref: "", header: CONTAINER_HEADER, cards: boxCards(loose, byStory), children: [] });
  }
  return roots;
}

export type PlacedBox = {
  spec: BoxSpec;
  rect: Box;
  // 0 for a top-level box, one more per nesting level.
  depth: number;
  topLevel: boolean;
  headerH: number;
  // The box's own card ids in order, and every node inside it (nested boxes and cards,
  // transitively) — what a box drag carries along.
  cardIds: string[];
  memberIds: string[];
  // Cards inside, transitively.
  count: number;
};

export type BoxLayout = {
  // Pre-order, so a parent always precedes its children.
  boxes: PlacedBox[];
  // Each card's top-left, absolute.
  cardAt: Map<string, BoardXY>;
  // Where the next unstored top-level box would stack — plotline and arc nodes start below.
  stackBottom: number;
};

// What an empty box still reserves for its cards, so there is somewhere to drop one.
const EMPTY_CONTENT_H = CARD_HEIGHT;
const MIN_CONTENT_W = CARD_WIDTH;

/** Lay the tree out. A top-level box with a stored position goes there; the rest stack
 *  top-to-bottom from the origin (a stored box leaves no hole in the stack). Inside a box:
 *  nested boxes stack first, then the box's own cards wrap into a grid. Sizes follow the
 *  contents — nothing is stored — and a box with no cards or boxes keeps room for one card. */
export function layoutBoxes(roots: BoxSpec[], saved: Record<string, BoardXY> = {}): BoxLayout {
  const boxes: PlacedBox[] = [];
  const cardAt = new Map<string, BoardXY>();

  const place = (spec: BoxSpec, left: number, top: number, depth: number): PlacedBox => {
    const placed: PlacedBox = {
      spec,
      rect: { x: left, y: top, w: 0, h: 0 },
      depth,
      topLevel: depth === 0,
      headerH: spec.header,
      cardIds: spec.cards.map((c) => c.id),
      memberIds: [],
      count: spec.cards.length,
    };
    boxes.push(placed);
    const contentX = left + CONTAINER_PAD;
    let y = top + spec.header + CONTAINER_PAD;
    let contentW = MIN_CONTENT_W;
    for (const child of spec.children) {
      const inner = place(child, contentX, y, depth + 1);
      y = inner.rect.y + inner.rect.h + CONTAINER_GAP;
      contentW = Math.max(contentW, inner.rect.w);
      placed.memberIds.push(child.nodeId, ...inner.memberIds);
      placed.count += inner.count;
    }
    if (spec.cards.length > 0) {
      const grid = layoutGrid(spec.cards.map((c) => c.height));
      spec.cards.forEach((card, i) => cardAt.set(card.id, { x: contentX + grid.offsets[i].x, y: y + grid.offsets[i].y }));
      contentW = Math.max(contentW, Math.min(spec.cards.length, CARDS_PER_ROW) * CARD_STEP_X - (CARD_STEP_X - CARD_WIDTH));
      y += grid.height - CONTAINER_GAP; // the grid's trailing gap is not content
      placed.memberIds.push(...placed.cardIds);
    } else if (spec.children.length > 0) {
      y -= CONTAINER_GAP; // the last child's trailing gap
    } else {
      y += EMPTY_CONTENT_H;
    }
    placed.rect = { x: left, y: top, w: contentW + 2 * CONTAINER_PAD, h: y - top + CONTAINER_PAD };
    return placed;
  };

  let stackY = 0;
  for (const root of roots) {
    const at = saved[root.nodeId];
    if (at) {
      place(root, at.x, at.y, 0);
    } else {
      const placed = place(root, 0, stackY, 0);
      stackY = placed.rect.y + placed.rect.h + CONTAINER_GAP;
    }
  }
  return { boxes, cardAt, stackBottom: stackY };
}
