// Story time on the board (ADR-0097 §5, §8) — pure helpers over the projection.
// A card's `story_order` is its index in the order things happen, over every
// projected card; `story_movable` marks the ones the open layer owns (the only ones
// the backend will move, or accept as an anchor). The Story time view, the card menu
// and the late-cause flag all read through here so none re-derives the order.

import type { StoryAnchor } from "@/lib/api/plot";
import type { PlotBoardCard } from "@/lib/types";

/** Every card in story time, earliest first. */
export function inStoryOrder(cards: readonly PlotBoardCard[]): PlotBoardCard[] {
  return [...cards].sort((a, b) => a.story_order - b.story_order);
}

/** What "Earlier" and "Later in story time" would do for a card, given the cards
 *  already `inStoryOrder`: swap with the
 *  neighbour (earlier = before the card just ahead, later = after the one just behind).
 *  null when the card sits at that end — or its neighbour is an inherited card the
 *  backend refuses as an anchor — so the menu hides the item. */
export function storySwapAnchors(
  ordered: readonly PlotBoardCard[],
  id: string,
): { earlier: StoryAnchor | null; later: StoryAnchor | null } {
  const index = ordered.findIndex((c) => c.id === id);
  if (index < 0 || !ordered[index].story_movable) return { earlier: null, later: null };
  const prev = ordered[index - 1];
  const next = ordered[index + 1];
  return {
    earlier: prev?.story_movable ? { before_id: prev.id } : null,
    later: next?.story_movable ? { after_id: next.id } : null,
  };
}

/** The anchor that undoes a move of `id`: back after the card just before it, or — if
 *  it was first — back before the card just after it. null when it is alone, or its
 *  neighbour is not a card the backend takes as an anchor. */
export function storyRestoreAnchor(cards: readonly PlotBoardCard[], id: string): StoryAnchor | null {
  const ordered = inStoryOrder(cards);
  const index = ordered.findIndex((c) => c.id === id);
  if (index < 0) return null;
  const prev = ordered[index - 1];
  if (prev) return { after_id: prev.id };
  const next = ordered[index + 1];
  return next ? { before_id: next.id } : null;
}

/** Whether moving `id` to `anchor` would leave it where it is. */
export function isStoryNoOp(cards: readonly PlotBoardCard[], id: string, anchor: StoryAnchor): boolean {
  const ordered = inStoryOrder(cards);
  const index = ordered.findIndex((c) => c.id === id);
  if (index < 0) return false;
  if ("after_id" in anchor) return anchor.after_id === ordered[index - 1]?.id;
  return anchor.before_id === ordered[index + 1]?.id;
}

/** The late-cause flag (ADR-0097 §8): effect card id -> the titles of the cards that
 *  lead to it yet come LATER in story time. Computed once per projection; a cause
 *  after its effect is almost always a mistake, while telling it late is craft. */
export function lateCausesByEffect(cards: readonly PlotBoardCard[]): Map<string, string[]> {
  const byId = new Map(cards.map((c) => [c.id, c]));
  const out = new Map<string, string[]>();
  for (const cause of cards) {
    for (const effectId of cause.causal_links) {
      const effect = byId.get(effectId);
      if (!effect || effect.id === cause.id || cause.story_order <= effect.story_order) continue;
      const titles = out.get(effect.id);
      if (titles) titles.push(cause.title);
      else out.set(effect.id, [cause.title]);
    }
  }
  return out;
}

/** The tooltip on a "Cause is later" pill, naming the cause card(s). */
export function lateCauseTitle(causes: readonly string[]): string {
  const names = causes.map((t) => `“${t || "Untitled card"}”`).join(", ");
  return `Caused by ${names}, which happens later`;
}

const VIEW_KEY = "plotBoard.view";

export type PlotBoardView = "board" | "story";

type PrefStorage = Pick<Storage, "getItem" | "setItem">;

function defaultStorage(): PrefStorage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null; // storage access can throw (privacy modes) — treat as absent.
  }
}

/** Which view the writer last chose — a viewing mode, so localStorage like the edge
 *  layers, defaulting to the board. */
export function loadBoardView(storage: PrefStorage | null = defaultStorage()): PlotBoardView {
  try {
    return storage?.getItem(VIEW_KEY) === "story" ? "story" : "board";
  } catch {
    return "board";
  }
}

export function saveBoardView(view: PlotBoardView, storage: PrefStorage | null = defaultStorage()): void {
  try {
    storage?.setItem(VIEW_KEY, view);
  } catch {
    // Storage disabled / quota — the pref just won't persist; not fatal.
  }
}
