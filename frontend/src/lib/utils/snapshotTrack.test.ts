// The strip's geometry invariants (ADR-0044 §D–§E). These are the assertions
// the ADR's test surface names, minus the ones that need a rendered DOM: notch
// order matches capture order, positions are monotonic in age under the
// minimum-gap adjustment, and nothing leaves the track.
import { describe, expect, it } from "vitest";

import {
  MIN_GAP,
  TRACK_LEFT,
  TRACK_RIGHT,
  ageMinutes,
  notchPositions,
} from "@/lib/utils/snapshotTrack";

const HOUR = 60;
const DAY = 24 * HOUR;

describe("notchPositions", () => {
  it("lays snapshots out oldest-left, newest-right", () => {
    const positions = notchPositions([7 * DAY, DAY, 2 * HOUR, 5]);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    expect(positions[0]).toBeCloseTo(TRACK_LEFT, 5);
    expect(positions[positions.length - 1]).toBeLessThanOrEqual(TRACK_RIGHT + 1e-9);
  });

  it("keeps every notch inside the track, however they bunch", () => {
    // Ten captures inside one afternoon: the log scale piles them at the right
    // and the minimum gap pushes them left, which is exactly the case that can
    // overflow if the squeeze pass is missing.
    const positions = notchPositions([180, 170, 160, 150, 140, 130, 120, 110, 100, 90]);
    for (const position of positions) {
      expect(position).toBeGreaterThanOrEqual(TRACK_LEFT - 1e-9);
      expect(position).toBeLessThanOrEqual(TRACK_RIGHT + 1e-9);
    }
  });

  it("never lets two notches touch", () => {
    // Five snapshots seconds apart would collapse onto one point on a pure log
    // scale.
    const positions = notchPositions([5.4, 5.3, 5.2, 5.1, 5]);
    for (let i = 1; i < positions.length; i++) {
      // The squeeze pass scales gaps down proportionally, so assert they are
      // separated rather than that each is exactly MIN_GAP.
      expect(positions[i] - positions[i - 1]).toBeGreaterThan(0);
    }
    expect(positions[positions.length - 1] - positions[0]).toBeGreaterThan(MIN_GAP);
  });

  it("spreads the recent and compresses the deep — the reason it is not linear", () => {
    // One from last week plus three from this morning. Under a linear scale the
    // three recent ones would sit within a few percent of each other at the
    // right edge; the log scale has to give them real room.
    const [week, morning1, morning2, morning3] = notchPositions([7 * DAY, 4 * HOUR, 2 * HOUR, HOUR]);
    expect(morning3 - morning1).toBeGreaterThan((morning1 - week) / 4);
  });

  it("handles the degenerate cases without producing NaN", () => {
    expect(notchPositions([])).toEqual([]);
    const single = notchPositions([0]);
    expect(single).toHaveLength(1);
    expect(Number.isFinite(single[0])).toBe(true);
    for (const position of notchPositions([0, 0, 0])) {
      expect(Number.isFinite(position)).toBe(true);
    }
  });
});

describe("ageMinutes", () => {
  const now = new Date("2026-07-22T15:00:00.000000+00:00");

  it("reads the backend's captured_at", () => {
    expect(ageMinutes("2026-07-22T14:30:00.000000+00:00", now)).toBeCloseTo(30, 6);
  });

  it("clamps a future stamp to zero rather than putting a notch right of Live", () => {
    expect(ageMinutes("2026-07-22T15:30:00.000000+00:00", now)).toBe(0);
  });

  it("treats an unreadable stamp as now instead of NaN", () => {
    expect(ageMinutes("", now)).toBe(0);
  });
});
