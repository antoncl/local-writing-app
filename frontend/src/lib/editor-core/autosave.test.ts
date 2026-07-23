// The autosave scheduler's timing contract (#369).
//
// The load-bearing test is `test_a_burst_with_no_idle_gap_still_saves`: before
// the ceiling existed, the idle debounce was re-armed on every keystroke with no
// elapsed-time bound, so an author typing without a full 6-second pause never
// saved at all. The exposure was the length of the burst, not `idleMs` — which
// is what made it a data-loss bug rather than a tuning question.
//
// Fake timers throughout: these assert the *rule*, not wall-clock behaviour.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AutosaveScheduler } from "@/lib/editor-core/autosave";

const IDLE = 6000;
const MAX_WAIT = 30000;

function makeScheduler() {
  const saves: string[] = [];
  let dirty = true;
  const scheduler = new AutosaveScheduler({
    idleMs: IDLE,
    maxWaitMs: MAX_WAIT,
    indicatorMs: 2000,
    shouldSave: () => dirty,
    save: (id) => {
      saves.push(id);
    },
    clearIndicator: () => {},
  });
  return {
    scheduler,
    saves,
    setDirty: (value: boolean) => {
      dirty = value;
    },
  };
}

describe("AutosaveScheduler", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("saves after the idle debounce when the author stops typing", () => {
    const { scheduler, saves } = makeScheduler();
    scheduler.schedule("a");
    vi.advanceTimersByTime(IDLE - 1);
    expect(saves).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(saves).toEqual(["a"]);
  });

  it("does not save while the author keeps typing inside the idle window", () => {
    const { scheduler, saves } = makeScheduler();
    // Five keystrokes, each 5s apart — never a full idle gap. Total 25s, still
    // under the ceiling, so the idle timer must stay pushed out.
    for (let n = 0; n < 5; n += 1) {
      scheduler.schedule("a");
      vi.advanceTimersByTime(5000);
    }
    expect(saves).toEqual([]);
  });

  it("saves a continuous burst at the ceiling, with no idle gap in it", () => {
    // THE regression test. Two minutes of typing with a keystroke every second:
    // the idle debounce alone would never fire, and every one of those minutes
    // would be held only in the tab.
    const { scheduler, saves } = makeScheduler();
    for (let second = 0; second < 120; second += 1) {
      scheduler.schedule("a");
      vi.advanceTimersByTime(1000);
    }
    expect(saves.length).toBeGreaterThan(0);
    // Four ceilings in two minutes, give or take the run that is still open.
    expect(saves.length).toBeGreaterThanOrEqual(3);
    expect(new Set(saves)).toEqual(new Set(["a"]));
  });

  it("measures the ceiling from the start of the run, not the last keystroke", () => {
    // If keystrokes re-armed the ceiling the way they re-arm the idle timer,
    // it would bound nothing and this fires late (or never).
    const { scheduler, saves } = makeScheduler();
    for (let second = 0; second < MAX_WAIT / 1000; second += 1) {
      scheduler.schedule("a");
      vi.advanceTimersByTime(1000);
    }
    expect(saves).toEqual(["a"]);
  });

  it("starts a fresh ceiling for the next dirty run", () => {
    const { scheduler, saves } = makeScheduler();
    scheduler.schedule("a");
    vi.advanceTimersByTime(IDLE);
    expect(saves).toEqual(["a"]);

    // A new run, typing continuously again.
    for (let second = 0; second < MAX_WAIT / 1000; second += 1) {
      scheduler.schedule("a");
      vi.advanceTimersByTime(1000);
    }
    expect(saves).toEqual(["a", "a"]);
  });

  it("re-checks dirtiness when the ceiling fires", () => {
    // Reaching the ceiling's own re-check takes some care, and two easier
    // spellings of this test prove nothing:
    //   - set `dirty` false and just wait: the *idle* timer reaches `#fire`
    //     first at 6s, does the re-check itself, and clears the ceiling as it
    //     goes, so the ceiling never fires;
    //   - set it false and keep typing: `schedule` bails on `!shouldSave` and
    //     clears the ceiling before it can fire.
    // So: type right up to the ceiling, then have something else clean the pane
    // *without* a further keystroke — which is what another save path doing
    // `flushSceneIfDirty` looks like from here.
    const { scheduler, saves, setDirty } = makeScheduler();
    for (let second = 0; second < MAX_WAIT / 1000 - 1; second += 1) {
      scheduler.schedule("a");
      vi.advanceTimersByTime(1000);
    }
    setDirty(false);
    // Past the ceiling (t=30s) but not yet past the last idle arm (t=34s).
    vi.advanceTimersByTime(2000);
    expect(saves).toEqual([]);
  });

  it("cancel drops the ceiling as well as the idle timer", () => {
    // Otherwise a torn-down pane fires a save into a document that is gone.
    const { scheduler, saves } = makeScheduler();
    scheduler.schedule("a");
    vi.advanceTimersByTime(1000);
    scheduler.cancel("a");
    vi.advanceTimersByTime(MAX_WAIT * 2);
    expect(saves).toEqual([]);
  });

  it("dispose drops the ceiling as well as the idle timer", () => {
    const { scheduler, saves } = makeScheduler();
    scheduler.schedule("a");
    scheduler.schedule("b");
    vi.advanceTimersByTime(1000);
    scheduler.dispose();
    vi.advanceTimersByTime(MAX_WAIT * 2);
    expect(saves).toEqual([]);
  });

  it("keeps each pane's ceiling independent", () => {
    // Both panes typed continuously so neither idle timer ever fires — the only
    // thing that can save either one is its own ceiling. `b` starts halfway
    // through `a`'s run, so at t = MAX_WAIT only `a` is due.
    const { scheduler, saves } = makeScheduler();
    const halfway = MAX_WAIT / 2000;
    for (let second = 0; second < MAX_WAIT / 1000; second += 1) {
      scheduler.schedule("a");
      if (second >= halfway) scheduler.schedule("b");
      vi.advanceTimersByTime(1000);
    }
    expect(saves).toEqual(["a"]);
  });
});
