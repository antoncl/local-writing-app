/**
 * The strip's time model (#458): which stamp a notch is laid out and labelled
 * by, and the order the notches are drawn in.
 *
 * This is the oracle the first version of the fix did not have. The four sites
 * that read a snapshot's time are all in `.svelte` files and there is no
 * component harness, so every one of them could be switched back to
 * `captured_at` with the whole suite green. Each test here therefore uses a
 * snapshot whose two stamps are a fortnight apart: reading the wrong field is
 * not a rounding difference, it is a different answer.
 */
import { describe, expect, it } from "vitest";
import type { Snapshot } from "@/lib/types";
import { inNotchOrder, notchAges, notchTooltip, notchWhen } from "./snapshotTime";

// `relativeTime` formats in the runtime's LOCAL zone (weekday, ordinal, day
// boundaries), so fixtures feeding a formatted assertion are built from local
// wall-clock — a local `NOW` and local (no-`Z`) ISO strings — exactly as
// `relativeTime.test.ts` does. A UTC instant would land on a different calendar
// day east of UTC+12 and turn "Thursday 9th" into "Friday 10th".
const NOW = new Date(2026, 6, 23, 12, 0, 0);

function snapshot(id: string, capturedAt: string, contentWrittenAt: string, retention: "thinned" | "kept" = "thinned"): Snapshot {
  return {
    id,
    snapshot_of: "scene_1",
    captured_at: capturedAt,
    content_written_at: contentWrittenAt,
    retention,
    description: "",
    schema_version: 5,
  };
}

/** The bug in one fixture: an automatic capture, made now, of a fortnight-old
 *  body. Every assertion below is a fortnight away from the wrong answer. */
const AUTOMATIC = snapshot(
  "snap_auto",
  "2026-07-23T11:00:00.000",
  "2026-07-09T11:00:00.000",
);

describe("notchAges", () => {
  it("ages a notch by when its content was written, not when the record was made", () => {
    const [age] = notchAges([AUTOMATIC], NOW);
    // A fortnight, near enough — not the hour since the record was written.
    expect(age).toBeCloseTo(14 * 24 * 60 + 60, 6);
  });

  it("shares one clock across the list", () => {
    const ages = notchAges([AUTOMATIC, snapshot("b", "x", "2026-07-23T11:00:00.000")], NOW);
    expect(ages).toEqual([14 * 24 * 60 + 60, 60]);
  });
});

describe("inNotchOrder", () => {
  it("orders by content time even when the backend's record order disagrees", () => {
    // The reachable case: a restore from backup, a cloud sync or an NTP
    // correction moves an mtime backwards relative to record order. The listing
    // is by `captured_at`, so `newer` arrives second while holding older prose.
    const older = snapshot("older", "2026-07-23T10:00:00.000Z", "2026-07-23T09:00:00.000Z");
    const newer = snapshot("newer", "2026-07-23T11:00:00.000Z", "2026-07-01T09:00:00.000Z");
    expect(inNotchOrder([older, newer]).map((item) => item.id)).toEqual(["newer", "older"]);
  });

  it("holds notchPositions' contract: ages come out ascending-oldest-first", () => {
    const ordered = inNotchOrder([
      snapshot("a", "2026-07-23T10:00:00.000Z", "2026-07-23T09:00:00.000Z"),
      snapshot("b", "2026-07-23T11:00:00.000Z", "2026-07-01T09:00:00.000Z"),
    ]);
    const ages = notchAges(ordered, NOW);
    expect([...ages].sort((x, y) => y - x)).toEqual(ages);
  });

  it("breaks a content-time tie by record time, so repeated captures keep their order", () => {
    // Content time is not monotonic: three captures with no edit between them
    // share one mtime. Record time is what separates them, and it is why the
    // sidecar keeps both fields.
    const unchanged = "2026-07-23T09:00:00.000Z";
    const ordered = inNotchOrder([
      snapshot("third", "2026-07-23T11:00:00.000Z", unchanged),
      snapshot("first", "2026-07-23T09:30:00.000Z", unchanged),
      snapshot("second", "2026-07-23T10:00:00.000Z", unchanged),
    ]);
    expect(ordered.map((item) => item.id)).toEqual(["first", "second", "third"]);
  });

  it("does not mutate the list it was given", () => {
    const list = [
      snapshot("b", "2026-07-23T11:00:00.000Z", "2026-07-01T09:00:00.000Z"),
      snapshot("a", "2026-07-23T10:00:00.000Z", "2026-07-23T09:00:00.000Z"),
    ];
    inNotchOrder(list);
    expect(list.map((item) => item.id)).toEqual(["b", "a"]);
  });
});

describe("what the strip says out loud", () => {
  it("phrases the content's age, not the record's", () => {
    // "Thursday 9th" — a fortnight back. By record time this would read
    // "an hour ago", which is the lie #458 is about.
    expect(notchWhen(AUTOMATIC, NOW)).toBe("Thursday 9th");
  });

  it("says nothing for no snapshot, rather than dating the epoch", () => {
    expect(notchWhen(null, NOW)).toBe("");
  });

  it("marks an explicit snapshot as kept and leaves an automatic one bare", () => {
    expect(notchTooltip(AUTOMATIC, NOW)).toBe("Snapshot · Thursday 9th");
    expect(notchTooltip({ ...AUTOMATIC, retention: "kept" }, NOW)).toBe(
      "Snapshot · Thursday 9th · kept",
    );
  });

  it("appends a description when there is one, and augments the date rather than replacing it", () => {
    // §L: the description is an enrichment on top of the date, never instead of
    // it. The common (empty) case is unchanged — the bare date line above.
    expect(notchTooltip({ ...AUTOMATIC, description: "Before the rewrite" }, NOW)).toBe(
      "Snapshot · Thursday 9th — Before the rewrite",
    );
    expect(
      notchTooltip({ ...AUTOMATIC, retention: "kept", description: "Before the rewrite" }, NOW),
    ).toBe("Snapshot · Thursday 9th · kept — Before the rewrite");
  });
});
