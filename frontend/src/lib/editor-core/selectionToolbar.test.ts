import { describe, it, expect } from "vitest";
import { verticalDropFit } from "./selectionToolbar";

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
