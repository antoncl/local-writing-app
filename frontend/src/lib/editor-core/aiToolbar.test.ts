import { describe, it, expect } from "vitest";
import { placeAiToolbar } from "./aiToolbar";

// #2582: the AI toolbar ("Generating… / Cancel") anchors at a selection's first
// line. On a selection longer than the viewport that line is scrolled out of
// view, so the toolbar must pin to the visible edge instead of following it.
describe("placeAiToolbar", () => {
  const frame = { height: 600, scrollTop: 2000 };
  const inView = (y: number) => y >= frame.scrollTop && y <= frame.scrollTop + frame.height;

  it("sits above an anchor line that is in view", () => {
    expect(placeAiToolbar({ top: 300, bottom: 320 }, frame)).toEqual({ y: 2300, placement: "above" });
  });

  it("flips below an in-view anchor too near the top to fit above", () => {
    expect(placeAiToolbar({ top: 10, bottom: 30 }, frame)).toEqual({ y: 2030, placement: "below" });
  });

  it("pins to the visible top when the anchor is scrolled above the view", () => {
    // The selection began 1500px above the visible top.
    const placed = placeAiToolbar({ top: -1500, bottom: -1480 }, frame);
    expect(placed).toEqual({ y: 2000, placement: "below" });
    expect(inView(placed.y)).toBe(true);
  });

  it("pins to the visible bottom when the anchor is below the view", () => {
    const placed = placeAiToolbar({ top: 1400, bottom: 1420 }, frame);
    expect(placed).toEqual({ y: 2600, placement: "above" });
    expect(inView(placed.y)).toBe(true);
  });
});
