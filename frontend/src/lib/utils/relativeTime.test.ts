// The bucketing is the design decision (ADR-0044 §K), so it is what is tested —
// not `Intl.RelativeTimeFormat`, which is the platform's job. Each case pins a
// rung boundary; the wording inside a rung comes from `Intl` and is asserted
// loosely enough to survive its phrasing.
import { describe, expect, it } from "vitest";

import { relativeTime } from "@/lib/utils/relativeTime";

// A Thursday, mid-afternoon — far enough from midnight that "3 hours ago" stays
// inside the same day, which is the rung the day-boundary logic exists for.
const NOW = new Date(2026, 6, 23, 15, 0, 0);
const ago = (ms: number) => new Date(NOW.getTime() - ms);
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe("relativeTime", () => {
  it("calls anything under a minute 'just now' — seconds are noise", () => {
    expect(relativeTime(ago(0), NOW)).toBe("just now");
    expect(relativeTime(ago(59_000), NOW)).toBe("just now");
  });

  it("counts minutes up to the hour", () => {
    expect(relativeTime(ago(5 * MINUTE), NOW)).toMatch(/5 minutes ago/);
    expect(relativeTime(ago(59 * MINUTE), NOW)).toMatch(/59 minutes ago/);
  });

  it("counts hours while it is still the same day", () => {
    expect(relativeTime(ago(3 * HOUR), NOW)).toMatch(/3 hours ago/);
  });

  it("switches to 'yesterday' on the day boundary, not at 24 elapsed hours", () => {
    // 16 hours before 15:00 is 23:00 the previous day: fewer than 24 hours
    // elapsed, but a different day, and "yesterday" is what the author calls it.
    expect(relativeTime(ago(16 * HOUR), NOW)).toBe("yesterday");
    // And the converse: 23 hours before is 16:00 yesterday — still yesterday.
    expect(relativeTime(ago(23 * HOUR), NOW)).toBe("yesterday");
  });

  it("names the weekday for the rest of the week", () => {
    // Three days before a Thursday is a Monday.
    expect(relativeTime(ago(3 * DAY), NOW)).toBe("Monday");
    expect(relativeTime(ago(6 * DAY), NOW)).toBe("Friday");
  });

  it("adds the ordinal date once the weekday alone would be ambiguous", () => {
    // Seven days back is the same weekday again — "Thursday" would now read as
    // this week's, so the date joins it.
    expect(relativeTime(ago(7 * DAY), NOW)).toBe("Thursday 16th");
    expect(relativeTime(new Date(2026, 6, 2, 9, 0), NOW)).toBe("Thursday 2nd");
    expect(relativeTime(new Date(2026, 6, 3, 9, 0), NOW)).toBe("Friday 3rd");
    expect(relativeTime(new Date(2026, 6, 1, 9, 0), NOW)).toBe("Wednesday 1st");
    // 11th–13th are "th" whatever their last digit says.
    expect(relativeTime(new Date(2026, 6, 11, 9, 0), NOW)).toBe("Saturday 11th");
  });

  it("falls back to an absolute date past a year, where the year is the point", () => {
    const formatted = relativeTime(new Date(2024, 2, 12, 9, 0), NOW);
    expect(formatted).toMatch(/2024/);
    expect(formatted).toMatch(/12/);
  });

  it("reads a backend ISO timestamp directly", () => {
    expect(relativeTime(ago(5 * MINUTE).toISOString(), NOW)).toMatch(/5 minutes ago/);
  });

  it("answers a future stamp as 'just now' rather than inventing a countdown", () => {
    // Clock skew, or a hand-edited file. A snapshot has already happened, so
    // "in 3 minutes" would be a lie about the past.
    expect(relativeTime(new Date(NOW.getTime() + 3 * MINUTE), NOW)).toBe("just now");
  });

  it("returns nothing for an unparseable stamp instead of 'Invalid Date'", () => {
    expect(relativeTime("not a date", NOW)).toBe("");
  });
});
