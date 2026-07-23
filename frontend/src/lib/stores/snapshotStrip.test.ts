/**
 * The strip controller's two axes and the concurrency between them (#409).
 *
 * `park` fetches; `setView` re-renders what `park` fetched. They run against the
 * same state and the author drives both at once by design — left hand on the
 * letters, right hand on the arrows (ADR-0044 §I) — so the interesting cases are
 * the ones where a keypress lands while a fetch is still in flight.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { SnapshotDiff } from "@/lib/types";

const diffSnapshot = vi.fn();
const listSnapshots = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    diffSnapshot: (...args: unknown[]) => diffSnapshot(...args),
    listSnapshots: (...args: unknown[]) => listSnapshots(...args),
  },
}));

const { SnapshotStripController } = await import("./snapshotStrip.svelte");

const SNAPSHOT = {
  id: "snap_1",
  snapshot_of: "scene_1",
  captured_at: "2026-07-22T10:00:00.000000+00:00",
  retention: "kept" as const,
  schema_version: 5,
};

function diff(): SnapshotDiff {
  return {
    snapshot: SNAPSHOT,
    runs: [
      { kind: "equal", text: "The tide went out " },
      { kind: "was", text: "further" },
      { kind: "now", text: "much further" },
      { kind: "equal", text: " than she had seen." },
    ],
    fields: { status: { was: "draft", now: "revised" } },
    title_was: "The Tide",
    title_now: "The Tide",
  };
}

/** A controller with one snapshot loaded and the diff call resolved by `resolve`. */
async function parked(resolve: () => Promise<SnapshotDiff>) {
  listSnapshots.mockResolvedValue({ snapshots: [SNAPSHOT] });
  diffSnapshot.mockImplementation(resolve);
  const strip = new SnapshotStripController();
  strip.load("scene_1");
  await vi.waitFor(() => expect(strip.snapshots.length).toBe(1));
  return strip;
}

beforeEach(() => {
  diffSnapshot.mockReset();
  listSnapshots.mockReset();
});

describe("parking", () => {
  it("keeps the runs and the field pairs from the one call", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    expect(strip.runs.length).toBe(4);
    expect(strip.fields.status).toEqual({ was: "draft", now: "revised" });
    expect(strip.bodyHtml).toContain("r-was");
    expect(strip.bodyHtml).toContain("r-now");
  });

  it("a failed read returns to Live rather than showing a blank snapshot", async () => {
    const strip = await parked(async () => {
      throw new Error("gone");
    });
    await strip.park("snap_1");
    expect(strip.parked).toBe(null);
    expect(strip.bodyHtml).toBe("");
  });
});

describe("flipping", () => {
  it("filters the same payload instead of refetching", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    const calls = diffSnapshot.mock.calls.length;

    strip.setView("was");
    await vi.waitFor(() => expect(strip.bodyHtml).not.toContain("r-now"));
    expect(strip.bodyHtml).toContain("r-was");

    strip.setView("now");
    await vi.waitFor(() => expect(strip.bodyHtml).not.toContain("r-was"));
    expect(strip.bodyHtml).toContain("r-now");

    // One payload serves all three states (§G).
    expect(diffSnapshot.mock.calls.length).toBe(calls);
  });

  it("A and S toggle against Both; B returns from either", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    strip.toggleView("now");
    expect(strip.view).toBe("now");
    strip.toggleView("now");
    expect(strip.view).toBe("both");
    strip.toggleView("was");
    expect(strip.view).toBe("was");
    strip.setView("both");
    expect(strip.view).toBe("both");
  });

  it("the compare state survives stepping between notches", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    strip.setView("was");
    await strip.park(null);
    expect(strip.view).toBe("was");
  });
});

describe("a keypress landing while the diff is still in flight", () => {
  // The regression this file exists for. `park` and `setView` both guard
  // against a stale result, and sharing one token made `setView` cancel the
  // fetch it was waiting on: the author parked, pressed a key before the
  // response came back, and was left on a notch with an empty overlay and no
  // runs to flip — recoverable only by parking again.
  it("does not discard the payload the flip is about to render", async () => {
    let release: (value: SnapshotDiff) => void = () => {};
    const strip = await parked(
      () => new Promise<SnapshotDiff>((resolve) => (release = resolve)),
    );

    const parking = strip.park("snap_1");
    strip.setView("was"); // the author is quicker than the network
    release(diff());
    await parking;

    expect(strip.runs.length, "the runs were thrown away").toBe(4);
    expect(strip.fields.status, "the field pairs were thrown away").toBeTruthy();
    await vi.waitFor(() => expect(strip.bodyHtml).not.toBe(""));
    // And it renders the view the author asked for, not the one they left.
    expect(strip.bodyHtml).toContain("r-was");
    expect(strip.bodyHtml).not.toContain("r-now");
  });

  it("returning to Live cancels the diff that was still on its way", async () => {
    // The Live path was the one notch the freshness guard did not cover: it
    // cleared the fields and returned WITHOUT bumping the token, so the
    // response landed afterwards and put everything back while parked was
    // null. The next notch then rendered this snapshot's body and field pairs
    // under its own timestamp until its own fetch returned.
    let release: (value: SnapshotDiff) => void = () => {};
    const strip = await parked(
      () => new Promise<SnapshotDiff>((resolve) => (release = resolve)),
    );

    const parking = strip.park("snap_1");
    await strip.park(null); // Esc, before the POST comes back
    release(diff());
    await parking;

    expect(strip.parked).toBe(null);
    expect(strip.runs, "the abandoned diff was applied anyway").toEqual([]);
    expect(strip.fields).toEqual({});
    expect(strip.titleWas).toBe("");
    expect(strip.bodyHtml).toBe("");
  });

  it("returning to Live cancels a render that was still on its way", async () => {
    // The same hole on the other axis: `setView` starts an unawaited render,
    // and clearing without bumping let it paint the snapshot's body at Live.
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    strip.setView("was"); // render starts, unawaited
    await strip.park(null);
    // Let any pending render resolve.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(strip.bodyHtml, "a stale render painted the body at Live").toBe("");
  });

  it("a slow read for a notch already left cannot overwrite the current one", async () => {
    const releases: ((value: SnapshotDiff) => void)[] = [];
    const strip = await parked(
      () => new Promise<SnapshotDiff>((resolve) => releases.push(resolve)),
    );

    const first = strip.park("snap_1");
    const second = strip.park("snap_1");
    // The first read comes back last, and must lose.
    releases[1]({ ...diff(), title_now: "second" });
    releases[0]({ ...diff(), title_now: "first", runs: [{ kind: "equal", text: "STALE" }] });
    await Promise.all([first, second]);

    expect(strip.bodyHtml).not.toContain("STALE");
  });
});
