import { describe, it, expect } from "vitest";
import { packTagLine } from "@/lib/tagPacking";

// Width-aware tag packing (ADR-0066). Pure logic, so the collapse behaviour
// the 0×0 headless browser can't exercise is pinned here instead. Widths are
// synthetic (pixels); gap and +N width are passed explicitly.
describe("packTagLine", () => {
  const GAP = 4;
  const PLUS_N = 30;

  it("shows every pill when the width is unknown (<= 0)", () => {
    // Before first layout / in a no-measurement test we never guess an
    // overflow — all pills show, no +N.
    expect(packTagLine([40, 40, 40], 0, GAP, PLUS_N)).toBe(3);
    expect(packTagLine([40, 40, 40], -5, GAP, PLUS_N)).toBe(3);
  });

  it("returns 0 for no pills", () => {
    expect(packTagLine([], 500, GAP, PLUS_N)).toBe(0);
  });

  it("shows all pills and no +N when they all fit", () => {
    // 40 + 4 + 40 + 4 + 40 = 128 <= 200.
    expect(packTagLine([40, 40, 40], 200, GAP, PLUS_N)).toBe(3);
  });

  it("keeps all pills when they fit exactly (no spurious +N)", () => {
    // 50 + 4 + 50 = 104 exactly.
    expect(packTagLine([50, 50], 104, GAP, PLUS_N)).toBe(2);
  });

  it("collapses the remainder into +N, reserving the chip's width", () => {
    // Line = 130. Naive fit (no reserve): 40+4+40+4+40 = 128 -> all 3 would
    // fit, but the chip must be reserved once we know not-all fit... here all
    // fit, so no collapse — bump a pill to force the remainder.
    // Line = 120: naive 40+4+40 = 84 (2 fit), 3rd would be 84+4+40=128 > 120.
    // Not all fit -> reserve: avail = 120 - 30 - 4 = 86; 40+4+40 = 84 <= 86 -> 2.
    expect(packTagLine([40, 40, 40], 120, GAP, PLUS_N)).toBe(2);
  });

  it("drops a pill to make room for the +N chip when reserving is tight", () => {
    // Line = 100. Naive: 40+4+40 = 84 (2 fit), 3rd 84+4+40 = 128 > 100 -> not
    // all fit. Reserve: avail = 100 - 30 - 4 = 66; 40 (1), +4+40 = 84 > 66 ->
    // only 1 pill fits beside the chip.
    expect(packTagLine([40, 40, 40], 100, GAP, PLUS_N)).toBe(1);
  });

  it("always keeps at least one pill, even when none would fit beside +N", () => {
    // A single very wide pill on a narrow line: never collapses to just "+N".
    expect(packTagLine([500], 40, GAP, PLUS_N)).toBe(1);
    expect(packTagLine([500, 500], 40, GAP, PLUS_N)).toBe(1);
  });

  it("packs more pills as the line widens (the wasted-space fix)", () => {
    const widths = [40, 40, 40, 40, 40];
    // Narrow: only a couple fit.
    expect(packTagLine(widths, 130, GAP, PLUS_N)).toBeLessThan(5);
    // Wide: all five fit, no +N. 5*40 + 4*4 = 216.
    expect(packTagLine(widths, 220, GAP, PLUS_N)).toBe(5);
  });
});
