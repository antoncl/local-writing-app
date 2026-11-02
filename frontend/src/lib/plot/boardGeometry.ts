// Plot-board geometry (px) — the constants and the pure card-height / grid maths the
// box layout (`boxLayout.ts`) and the node builder (`plotBoardLayout.ts`) share. Split out
// so neither imports the other; `plotBoardLayout` re-exports it all, so callers keep
// importing from there.

import type { BoardXY } from "@/lib/types";

export type Box = { x: number; y: number; w: number; h: number };

// Geometry (px). Exported so the unit test asserts against the same constants the
// layout uses rather than hard-coding magic numbers that could silently drift.
export const CARD_WIDTH = 280;
// A card's height is ESTIMATED from its content (#2354): the synopsis is the card —
// the board exists to read synopses in sequence — so a card grows to show it. Size is
// single-sourced here (never DOM-measured), so the estimate is tuned to slightly
// OVER-estimate: an extra gap is harmless, clipped text is the bug. Beyond
// CARD_SYNOPSIS_MAX_LINES the synopsis scrolls inside the card instead of growing it.
export const CARD_PAD_Y = 20; // top + bottom padding of the card
export const CARD_HEAD_MIN_H = 22; // grip / kebab band, the floor of the head
export const CARD_TITLE_LINE_H = 17; // one wrapped title line (--fs-sm, ~1.3)
export const CARD_TITLE_MAX_LINES = 2;
export const CARD_TITLE_CHARS_PER_LINE = 36;
export const CARD_SYNOPSIS_LINE_H = 20; // one synopsis line (--fs-md, 1.45)
export const CARD_SYNOPSIS_CHARS_PER_LINE = 38;
export const CARD_SYNOPSIS_MAX_LINES = 14;
export const CARD_SECTION_GAP = 6; // between head / synopsis / foot
export const CARD_FOOT_MIN_H = 22; // the foot row: status dots, plus at least one pill row
export const CARD_PILL_ROW_H = 22; // one wrapped row of beat pills
// One pill per row (#2362): an interactive pill (grip + label + number + ×) is ~150px and
// shares the foot with the right-aligned marks, so with a status label showing only one
// fits. Two per row under-sized the card, squeezing the synopsis and clipping lower pills.
export const CARD_PILLS_PER_ROW = 1;
// The line heights and chars-per-line above are at --ui-scale 1. The card's text is sized
// by `--ui-scale` (every --fs-* token multiplies through it), so a scaled line is taller
// and holds fewer characters; the paddings and gaps are plain px and don't scale (#2362).
export function estCardHeight(title: string, synopsis: string, beatCount: number, scale = boardTextScale()): number {
  const lines = (text: string, charsPerLine: number) =>
    Math.max(1, Math.ceil(text.length / Math.max(1, Math.floor(charsPerLine / scale))));
  const titleLines = Math.min(CARD_TITLE_MAX_LINES, lines(title, CARD_TITLE_CHARS_PER_LINE));
  const head = Math.max(CARD_HEAD_MIN_H, titleLines * CARD_TITLE_LINE_H) * scale;
  const synopsisLines = Math.min(
    CARD_SYNOPSIS_MAX_LINES,
    // Trimmed: the projection's synopsis is the raw body, stored with a trailing newline.
    synopsis
      .trim()
      .split("\n")
      .reduce((n, para) => n + lines(para, CARD_SYNOPSIS_CHARS_PER_LINE), 0),
  );
  const pillRows = beatCount > 0 ? Math.ceil(beatCount / CARD_PILLS_PER_ROW) : 0;
  const foot = (pillRows > 0 ? pillRows * CARD_PILL_ROW_H : CARD_FOOT_MIN_H) * scale;
  const synopsisH = synopsisLines * CARD_SYNOPSIS_LINE_H * scale;
  return Math.ceil(CARD_PAD_Y + head + CARD_SECTION_GAP + synopsisH + CARD_SECTION_GAP + foot);
}
// The text scale the card renders at: the `--ui-scale` that applyProsePresentation sets on
// the document root (#127). Read, not measured: it is the same value the card's CSS uses.
// 1 where it isn't set (tests, before machine settings load).
export function boardTextScale(): number {
  if (typeof document === "undefined") return 1;
  const scale = Number.parseFloat(document.documentElement.style.getPropertyValue("--ui-scale"));
  return Number.isFinite(scale) && scale > 0 ? scale : 1;
}
// The minimum / default card height: what an empty, beat-less card measures at scale 1.
export const CARD_HEIGHT = estCardHeight("", "", 0, 1);
export const CARD_GAP_X = 64; // between cards in a row — room for the links between neighbours (#2411)
export const PLOTLINE_WIDTH = 240; // a plotline node is a touch wider than a card
// A plot holder node (plotline or arc) is variable-height — SvelteFlow sizes it to its
// content, and a collapsed beat roster runs one row per beat — so the arc band clears the
// plotline band by ESTIMATING each plotline's height from its beat count (a flat one-row
// nominal overlapped a multi-beat plotline: a 7-beat node measures ~210px, not ~110).
// Header + one row per beat, tuned to slightly OVER-estimate so the bands never collide;
// a small extra gap is harmless, an overlap is not.
export const PLOT_NODE_HEADER_H = 64; // header band above the collapsed beat roster
export const PLOT_NODE_BEAT_ROW_H = 24; // one beat row in that roster
// Like a card, the node's text is sized by --ui-scale (#2362), so the estimate scales with it.
export function estPlotNodeHeight(beatCount: number, scale = boardTextScale()): number {
  return Math.ceil((PLOT_NODE_HEADER_H + beatCount * PLOT_NODE_BEAT_ROW_H) * scale);
}
export const CONTAINER_PAD = 20; // inner padding between a box edge and its content
export const CONTAINER_HEADER = 32; // the title-bar band at the top of a box
export const CONTAINER_GAP = 24; // between sibling boxes / rows / acts
export const DECK_SYNOPSIS_LINE_H = 18; // one line of a deck's synopsis under its title
export const DECK_SYNOPSIS_MAX_LINES = 2; // a deck's box shows the first two lines
// A deck's or the loose box's cards wrap into a grid this many cards wide (#2348) — a single
// unwrapped row put the n-th loose card n card-widths away (card 40 ≈ 9400px). A manuscript
// container's cards run in one row instead (#2411): one row per chapter, read left to right.
export const CARDS_PER_ROW = 5;
export const CARD_STEP_X = CARD_WIDTH + CARD_GAP_X;
// Auto-laid-out cards wrap into rows of `perRow`; a row is as tall as its tallest
// card. Given the cards' heights in order, returns each card's slot relative to the
// grid's top-left plus the grid's total height (including the trailing gap to what
// follows).
export const layoutGrid = (heights: number[], perRow = CARDS_PER_ROW): { offsets: BoardXY[]; height: number } => {
  const offsets: BoardXY[] = [];
  let y = 0;
  for (let start = 0; start < heights.length; start += perRow) {
    const row = heights.slice(start, start + perRow);
    row.forEach((_, j) => offsets.push({ x: j * CARD_STEP_X, y }));
    y += Math.max(...row) + CONTAINER_GAP;
  }
  return { offsets, height: y };
};

