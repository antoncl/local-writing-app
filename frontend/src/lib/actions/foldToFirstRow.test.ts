// Pure geometry, no DOM — locks `firstRowFit`'s contract (#1884 slice 2): fold
// a wrapping pill row to its first line, minus whatever trailing pills a `+N`
// chip needs room to sit beside them.
import { describe, expect, it } from "vitest";
import { firstRowFit, type PillBox } from "./foldToFirstRow";

function box(left: number, right: number, top: number): PillBox {
  return { left, right, top };
}

describe("firstRowFit", () => {
  it("no pills → 0", () => {
    expect(firstRowFit([], 300, 40, 6)).toBe(0);
  });

  it("all pills on one line → every pill visible, no chip needed, regardless of chipWidth", () => {
    const pills = [box(0, 60, 0), box(60, 120, 0), box(120, 180, 0)];
    expect(firstRowFit(pills, 300, 40, 6)).toBe(3);
    expect(firstRowFit(pills, 300, 9999, 6)).toBe(3);
  });

  it("5 pills, first 3 on line 1 — the chip needs room, so the 3rd drops (right 280)", () => {
    const pills = [box(0, 80, 0), box(80, 180, 0), box(180, 280, 0), box(0, 60, 24), box(60, 120, 24)];
    expect(firstRowFit(pills, 300, 40, 6)).toBe(2);
  });

  it("same shape but the 3rd pill ends sooner (right 250) — the chip fits after it", () => {
    const pills = [box(0, 80, 0), box(80, 180, 0), box(180, 250, 0), box(0, 60, 24), box(60, 120, 24)];
    expect(firstRowFit(pills, 300, 40, 6)).toBe(3);
  });

  it("even the first pill alone leaves no room for the chip → 0 (chip alone)", () => {
    const pills = [box(0, 290, 0), box(290, 350, 24)];
    expect(firstRowFit(pills, 300, 40, 6)).toBe(0);
  });

  it("an exact fit keeps the pill: right + gap + chip landing ON the edge is not an overflow", () => {
    // 254 + 6 + 40 === 300 — the chip ends flush with the container; one pixel
    // more (255) and the pill has to go. Pins the `>` (not `>=`) boundary.
    expect(firstRowFit([box(0, 120, 0), box(126, 254, 0), box(0, 60, 24)], 300, 40, 6)).toBe(2);
    expect(firstRowFit([box(0, 120, 0), box(126, 255, 0), box(0, 60, 24)], 300, 40, 6)).toBe(1);
  });

  it("stops at the first pill whose top differs, even if a later pill's top matches again", () => {
    // tops 0,0,24,0 — only the leading run (indices 0,1) counts, never index 3.
    const pills = [box(0, 80, 0), box(80, 160, 0), box(0, 60, 24), box(0, 60, 0)];
    expect(firstRowFit(pills, 300, 40, 6)).toBe(2);
  });
});
