import { describe, it, expect } from "vitest";
import { placeSelectionToolbar, verticalDropFit, type EdgeRect } from "./selectionToolbar";

// #1227: dropdowns must open toward the room and never clip. verticalDropFit is
// the pure decision behind that — direction + a height cap the CSS applies.
describe("verticalDropFit", () => {
  const VP = 800;

  it("opens DOWN for a trigger high on screen (the toolbar-above-selection case)", () => {
    // Trigger near the top: lots of room below, almost none above.
    const fit = verticalDropFit(20, 54, VP);
    expect(fit.up).toBe(false);
    expect(fit.maxHeight).toBe(VP - 54 - 10); // room below, less the margin
  });

  it("flips UP only when down lacks room and up has more", () => {
    // Trigger near the bottom: little room below, plenty above.
    const fit = verticalDropFit(760, 790, VP);
    expect(fit.up).toBe(true);
    expect(fit.maxHeight).toBe(760 - 10);
  });

  it("prefers DOWN in the middle even though both sides fit", () => {
    const fit = verticalDropFit(380, 414, VP);
    expect(fit.up).toBe(false);
  });

  it("never returns a clipping (too-small/negative) height — it floors so the menu scrolls", () => {
    // A cramped viewport where neither side has real room.
    const fit = verticalDropFit(150, 170, 180);
    expect(fit.maxHeight).toBeGreaterThanOrEqual(120);
  });

  it("respects a custom `typical` menu height when deciding to flip", () => {
    // Below has 200px; with typical=150 that's enough → stay down.
    const shallow = verticalDropFit(500, 600, VP, { typical: 150 });
    expect(shallow.up).toBe(false);
    // With typical=300 the same 200px below is too little and above wins → up.
    const tall = verticalDropFit(500, 600, VP, { typical: 300 });
    expect(tall.up).toBe(true);
  });
});

// #1884 slice 1: placeSelectionToolbar is the pure placement math the body has
// used since #1223 (updateSelectionMenu), moved out so the rail's long_text
// fields can position the same floating toolbar. Pure — no DOM.
describe("placeSelectionToolbar", () => {
  const FRAME: EdgeRect = { top: 0, bottom: 800, left: 0, right: 1000 };
  const VIEWPORT = { width: 1000, height: 800 };

  it("opens ABOVE the anchor when there is room, centered on the anchor", () => {
    const anchor: EdgeRect = { top: 300, bottom: 320, left: 400, right: 500 };
    const placed = placeSelectionToolbar(anchor, FRAME, 1000, VIEWPORT);
    expect(placed.placement).toBe("above");
    expect(placed.y).toBe(anchor.top - 10);
    expect(placed.x).toBe((anchor.left + anchor.right) / 2);
  });

  it("falls to BELOW when the anchor is near the frame top (no room above)", () => {
    const anchor: EdgeRect = { top: 15, bottom: 35, left: 400, right: 500 };
    const placed = placeSelectionToolbar(anchor, FRAME, 1000, VIEWPORT);
    expect(placed.placement).toBe("below");
    expect(placed.y).toBe(anchor.bottom + 10);
  });

  it("clamps x so the toolbar never runs off the left edge of the frame", () => {
    const halfWidth = Math.min(360, Math.max(140, 1000 / 2 - 10));
    const anchor: EdgeRect = { top: 300, bottom: 320, left: -200, right: -100 };
    const placed = placeSelectionToolbar(anchor, FRAME, 1000, VIEWPORT);
    expect(placed.x).toBeGreaterThanOrEqual(FRAME.left + halfWidth);
    expect(placed.x).toBe(FRAME.left + halfWidth);
  });

  it("clamps x symmetrically off the right edge of the frame", () => {
    const halfWidth = Math.min(360, Math.max(140, 1000 / 2 - 10));
    const anchor: EdgeRect = { top: 300, bottom: 320, left: 1350, right: 1450 };
    const placed = placeSelectionToolbar(anchor, FRAME, 1000, VIEWPORT);
    const maxX = Math.min(FRAME.right, VIEWPORT.width) - halfWidth;
    expect(placed.x).toBeLessThanOrEqual(maxX);
    expect(placed.x).toBe(maxX);
  });

  it("falls to the frame's visible centre when a narrow frame makes minX > maxX", () => {
    const narrowFrame: EdgeRect = { top: 0, bottom: 800, left: 100, right: 300 };
    const anchor: EdgeRect = { top: 300, bottom: 320, left: 150, right: 180 };
    const placed = placeSelectionToolbar(anchor, narrowFrame, 200, VIEWPORT);
    expect(placed.x).toBe((narrowFrame.left + Math.min(narrowFrame.right, VIEWPORT.width)) / 2);
  });

  it("clamps y to the visible band when the anchor sits below the viewport bottom", () => {
    const tallFrame: EdgeRect = { top: 0, bottom: 2000, left: 0, right: 1000 };
    const anchor: EdgeRect = { top: 1900, bottom: 1920, left: 400, right: 500 };
    const placed = placeSelectionToolbar(anchor, tallFrame, 1000, VIEWPORT);
    const visibleBottom = Math.min(tallFrame.bottom, VIEWPORT.height) - 10;
    expect(placed.y).toBeLessThanOrEqual(visibleBottom);
    expect(placed.y).toBe(visibleBottom);
  });
});
