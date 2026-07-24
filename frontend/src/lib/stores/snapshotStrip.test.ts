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
const pinSnapshot = vi.fn();
const setSnapshotDescription = vi.fn();
const deleteSnapshot = vi.fn();
const restoreSnapshot = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    diffSnapshot: (...args: unknown[]) => diffSnapshot(...args),
    listSnapshots: (...args: unknown[]) => listSnapshots(...args),
    pinSnapshot: (...args: unknown[]) => pinSnapshot(...args),
    setSnapshotDescription: (...args: unknown[]) => setSnapshotDescription(...args),
    deleteSnapshot: (...args: unknown[]) => deleteSnapshot(...args),
    restoreSnapshot: (...args: unknown[]) => restoreSnapshot(...args),
  },
}));

const { SnapshotStripController } = await import("./snapshotStrip.svelte");
const { confirmService } = await import("./confirmService.svelte");

const SNAPSHOT = {
  id: "snap_1",
  snapshot_of: "scene_1",
  captured_at: "2026-07-22T10:00:00.000000+00:00",
  // Deliberately earlier than `captured_at`: this is an automatic capture, so
  // its bytes are the previous sitting's (#458).
  content_written_at: "2026-07-21T18:00:00.000000+00:00",
  retention: "kept" as const,
  description: "",
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
    drift: { available: true, comparable: true, truncated: false, entities: [] },
  };
}

/** A drift report naming one changed entity — the shape ADR-0043 requires:
 *  entity, field, value-then, value-now. */
function driftedDiff(): SnapshotDiff {
  return {
    ...diff(),
    drift: {
      available: true,
      comparable: true,
      truncated: false,
      entities: [
        {
          entity_id: "lore_tom",
          title: "Tom",
          membership: "present",
          sources: ["entity_ref"],
          entry_changed: "yes",
          fields: [
            {
              field_id: "eye_colour",
              label: "Eye colour",
              was: "green",
              now: "blue",
              from_mutation: false,
            },
          ],
          reinterpreted: [],
          layer_was: "",
          layer_now: "",
        },
      ],
    },
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
  pinSnapshot.mockReset();
  setSnapshotDescription.mockReset();
  deleteSnapshot.mockReset();
  restoreSnapshot.mockReset();
  confirmService.dismiss();
});

describe("the order the strip holds", () => {
  // The backend lists by record time; the strip lays out by content time
  // (#458). Where the two disagree — a restore from backup, a cloud sync, an
  // NTP correction — the controller has to hold the layout order, or ← / →
  // walk one sequence while the eye reads another.
  it("re-orders the listing by content time on load", async () => {
    const older = { ...SNAPSHOT, id: "older", captured_at: "2026-07-22T09:00:00.000000+00:00", content_written_at: "2026-07-22T08:00:00.000000+00:00" };
    const newer = { ...SNAPSHOT, id: "newer", captured_at: "2026-07-22T10:00:00.000000+00:00", content_written_at: "2026-07-01T08:00:00.000000+00:00" };
    listSnapshots.mockResolvedValue({ snapshots: [older, newer] });
    const strip = new SnapshotStripController();
    strip.load("scene_1");
    await vi.waitFor(() => expect(strip.snapshots.length).toBe(2));
    expect(strip.snapshots.map((item) => item.id)).toEqual(["newer", "older"]);
  });

  it("steps ← from Live onto the notch nearest Live", async () => {
    // `step` walks the same array the notches are drawn from, so "the newest"
    // has to mean the rightmost one — which is the newest CONTENT.
    const older = { ...SNAPSHOT, id: "older", captured_at: "2026-07-22T09:00:00.000000+00:00", content_written_at: "2026-07-22T08:00:00.000000+00:00" };
    const newer = { ...SNAPSHOT, id: "newer", captured_at: "2026-07-22T10:00:00.000000+00:00", content_written_at: "2026-07-01T08:00:00.000000+00:00" };
    listSnapshots.mockResolvedValue({ snapshots: [older, newer] });
    diffSnapshot.mockImplementation(async () => diff());
    const strip = new SnapshotStripController();
    strip.load("scene_1");
    await vi.waitFor(() => expect(strip.snapshots.length).toBe(2));
    strip.step(-1);
    await vi.waitFor(() => expect(strip.parked).toBe("older"));
  });
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

/**
 * The drift report rides on the diff payload (ADR-0043, #439). These pin the
 * controller's half of that: it carries what the backend said, and it decides
 * whether there is anything to show — never whether a restore may proceed.
 */
describe("drift", () => {
  it("carries the report from the same call as the runs", async () => {
    const strip = await parked(async () => driftedDiff());
    await strip.park("snap_1");
    expect(diffSnapshot.mock.calls.length).toBe(1);
    expect(strip.drift.entities[0].title).toBe("Tom");
    // Ordered, so swapping value-then with value-now turns this red.
    expect(strip.drift.entities[0].fields[0].was).toBe("green");
    expect(strip.drift.entities[0].fields[0].now).toBe("blue");
    expect(strip.hasDriftToReport).toBe(true);
  });

  it("says nothing when nothing changed underneath", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    expect(strip.hasDriftToReport).toBe(false);
  });

  it("says nothing at Live — drift is a claim about a snapshot", async () => {
    const strip = await parked(async () => driftedDiff());
    await strip.park("snap_1");
    await strip.park(null);
    expect(strip.hasDriftToReport).toBe(false);
    expect(strip.drift.entities).toEqual([]);
  });

  it("surfaces an uncomparable witness rather than reading it as unchanged", async () => {
    const strip = await parked(async () => ({
      ...diff(),
      drift: { available: true, comparable: false, truncated: false, entities: [] },
    }));
    await strip.park("snap_1");
    expect(strip.hasDriftToReport).toBe(true);
  });

  it("stays silent for a snapshot taken before witnesses existed", async () => {
    const strip = await parked(async () => ({
      ...diff(),
      drift: { available: false, comparable: true, truncated: false, entities: [] },
    }));
    await strip.park("snap_1");
    expect(strip.hasDriftToReport).toBe(false);
  });

  it("surfaces a truncated report even when it found nothing", async () => {
    // Gating on `entities.length` alone made this state unrenderable, so the
    // author read silence as "nothing else changed" — the one inference a
    // truncated witness must never allow.
    const strip = await parked(async () => ({
      ...diff(),
      drift: { available: true, comparable: true, truncated: true, entities: [] },
    }));
    await strip.park("snap_1");
    expect(strip.hasDriftToReport).toBe(true);
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

describe("entering compare mode", () => {
  // Parking used to set `parked` synchronously, so the pane switched a whole
  // round trip before it had anything to show. The author got an empty title
  // bar and an empty page under a ribbon already naming the snapshot — and
  // stepping notch to notch, the PREVIOUS snapshot's body under the new one's
  // timestamp. The swap now happens once, with the payload in hand.
  it("stays where the author was until the payload is rendered", async () => {
    let release: (value: SnapshotDiff) => void = () => {};
    const strip = await parked(
      () => new Promise<SnapshotDiff>((resolve) => (release = resolve)),
    );

    const parking = strip.park("snap_1");
    // Mid-flight: still Live, still empty, and nothing claiming otherwise.
    expect(strip.parked, "switched before it had anything to show").toBe(null);
    expect(strip.bodyHtml).toBe("");
    expect(strip.titleForView).toBe("");
    // ...but the strip knows which notch is being fetched.
    expect(strip.pendingId).toBe("snap_1");

    release(diff());
    await parking;

    expect(strip.parked).toBe("snap_1");
    expect(strip.bodyHtml).toContain("r-was");
    expect(strip.titleForView).toBe("The Tide");
    expect(strip.pendingId).toBe(null);
  });

  it("a failed park leaves the author where they were", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    diffSnapshot.mockImplementation(async () => {
      throw new Error("gone");
    });
    await strip.park("snap_1");
    // Still reading the snapshot it successfully loaded, not dumped to Live
    // with an empty page.
    expect(strip.parked).toBe("snap_1");
    expect(strip.bodyHtml).toContain("r-was");
    expect(strip.pendingId).toBe(null);
  });

  it("only admits it is working once the wait is worth mentioning", async () => {
    vi.useFakeTimers();
    try {
      let release: (value: SnapshotDiff) => void = () => {};
      const strip = await parked(
        () => new Promise<SnapshotDiff>((resolve) => (release = resolve)),
      );
      const parking = strip.park("snap_1");
      expect(strip.slow, "flagged a wait nobody would notice").toBe(false);
      vi.advanceTimersByTime(1900);
      expect(strip.slow).toBe(false);
      vi.advanceTimersByTime(200);
      expect(strip.slow, "never admitted to a long wait").toBe(true);
      release(diff());
      await parking;
      expect(strip.slow, "left the cursor spinning after it finished").toBe(false);
    } finally {
      vi.useRealTimers();
    }
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

/**
 * The author's three new gestures (#468, slice 4). The load-bearing property
 * here is the asymmetry ADR-0043 makes deliberate: delete confirms because it
 * is irreversible; restore does not, because it captures first.
 */
describe("author gestures", () => {
  it("pin promotes the parked snapshot and re-lists", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    pinSnapshot.mockResolvedValue({ ...SNAPSHOT, retention: "kept" });
    listSnapshots.mockResolvedValue({ snapshots: [{ ...SNAPSHOT, retention: "kept" }] });

    await strip.pin();

    expect(pinSnapshot).toHaveBeenCalledWith("scene_1", "snap_1");
  });

  it("describe sends the trimmed text", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    setSnapshotDescription.mockResolvedValue({ ...SNAPSHOT, description: "A note" });
    listSnapshots.mockResolvedValue({ snapshots: [{ ...SNAPSHOT, description: "A note" }] });

    await strip.describe("  A note  ");
    expect(setSnapshotDescription).toHaveBeenCalledWith("scene_1", "snap_1", "A note");
  });

  it("a no-op edit writes nothing — closing the editor unchanged is the common gesture", async () => {
    // The guard lives on the controller precisely so this is reachable: there
    // is no component harness, so a guard in the blur handler could be dropped
    // with the whole suite still green.
    const described = { ...SNAPSHOT, description: "A note" };
    listSnapshots.mockResolvedValue({ snapshots: [described] });
    diffSnapshot.mockImplementation(async () => diff());
    const strip = new SnapshotStripController();
    strip.load("scene_1");
    await vi.waitFor(() => expect(strip.snapshots.length).toBe(1));
    await strip.park("snap_1");

    await strip.describe("A note"); // unchanged
    await strip.describe("  A note  "); // unchanged but for whitespace
    expect(setSnapshotDescription).not.toHaveBeenCalled();

    // ...and an actual change still goes through.
    await strip.describe("A different note");
    expect(setSnapshotDescription).toHaveBeenCalledWith("scene_1", "snap_1", "A different note");
  });

  it("clearing a description is a real change, not a no-op", async () => {
    const described = { ...SNAPSHOT, description: "A note" };
    listSnapshots.mockResolvedValue({ snapshots: [described] });
    diffSnapshot.mockImplementation(async () => diff());
    const strip = new SnapshotStripController();
    strip.load("scene_1");
    await vi.waitFor(() => expect(strip.snapshots.length).toBe(1));
    await strip.park("snap_1");
    setSnapshotDescription.mockResolvedValue({ ...SNAPSHOT, description: "" });

    await strip.describe("");
    expect(setSnapshotDescription).toHaveBeenCalledWith("scene_1", "snap_1", "");
  });

  it("delete asks first — the modal opens and nothing is deleted until it resolves", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    deleteSnapshot.mockResolvedValue({ snapshots: [] });
    listSnapshots.mockResolvedValue({ snapshots: [] });

    strip.del();
    // The gate is up: the confirmation is showing and nothing has been removed.
    expect(confirmService.active).not.toBe(null);
    expect(confirmService.active?.cannotBeUndone).toBe(true);
    expect(deleteSnapshot).not.toHaveBeenCalled();

    await confirmService.resolve();
    expect(deleteSnapshot).toHaveBeenCalledWith("scene_1", "snap_1");
    // Deleting the parked notch returns to Live — the id no longer exists.
    await vi.waitFor(() => expect(strip.parked).toBe(null));
  });

  it("restore does not ask — it captured first, so there is nothing to confirm", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    restoreSnapshot.mockResolvedValue({ id: "scene_1", title: "The Tide", body: "back" });
    listSnapshots.mockResolvedValue({ snapshots: [SNAPSHOT] });

    await strip.restore();

    expect(confirmService.active).toBe(null);
    expect(restoreSnapshot).toHaveBeenCalledWith("scene_1", "snap_1");
  });
});

/**
 * Adopting one region while parked (ADR-0044 Amendment 4). The re-projection
 * logic is `adoptRegion`'s, tested exhaustively in `diffRuns.test.ts`; these pin
 * the controller's half — the `onAdopt` wiring, and that it never re-diffs.
 */
describe("adopting a region", () => {
  it("restores the snapshot side into the buffer, and does not re-diff", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    const adopted: string[] = [];
    strip.onAdopt = (body) => {
      adopted.push(body);
    };
    diffSnapshot.mockClear();

    await strip.adopt(0, "was");

    expect(adopted).toEqual(["The tide went out further than she had seen."]);
    // The region is resolved and the payload was re-projected in hand — no
    // round trip, so a region settled earlier cannot resurface.
    expect(strip.runs.every((run) => run.kind === "equal")).toBe(true);
    expect(diffSnapshot).not.toHaveBeenCalled();
  });

  it("keeps the current wording without writing the document", async () => {
    const strip = await parked(async () => diff());
    await strip.park("snap_1");
    const adopted: string[] = [];
    strip.onAdopt = (body) => {
      adopted.push(body);
    };

    await strip.adopt(0, "now");

    expect(adopted).toEqual([]);
    expect(strip.runs.map((run) => run.text).join("")).toBe(
      "The tide went out much further than she had seen.",
    );
  });

  it("does nothing when not parked", async () => {
    const strip = await parked(async () => diff());
    const adopted: string[] = [];
    strip.onAdopt = (body) => {
      adopted.push(body);
    };

    await strip.adopt(0, "was");

    expect(adopted).toEqual([]);
  });
});
