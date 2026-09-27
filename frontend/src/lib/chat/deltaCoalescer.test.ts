import { describe, expect, it } from "vitest";
import { createDeltaCoalescer, type DeltaBatch } from "./deltaCoalescer";

// A manual frame clock: `tick()` runs the pending frame callback, if any.
function manualFrames() {
  let pending: (() => void) | null = null;
  let scheduled = 0;
  return {
    schedule: (cb: () => void) => {
      pending = cb;
      scheduled += 1;
      return () => {
        if (pending === cb) pending = null;
      };
    },
    tick: () => {
      const cb = pending;
      pending = null;
      cb?.();
    },
    get scheduled() {
      return scheduled;
    },
  };
}

function setup() {
  const frames = manualFrames();
  const applied: DeltaBatch[] = [];
  const c = createDeltaCoalescer((b) => applied.push(b), frames.schedule);
  return { frames, applied, c };
}

describe("createDeltaCoalescer (#2294)", () => {
  it("applies many deltas as ONE write per frame", () => {
    const { frames, applied, c } = setup();
    for (let i = 0; i < 500; i++) c.content("x");
    c.thinking("hm");
    expect(applied).toEqual([]); // nothing applied until the frame
    expect(frames.scheduled).toBe(1); // one frame requested, not 501
    frames.tick();
    expect(applied).toEqual([{ content: "x".repeat(500), thinking: "hm" }]);
  });

  it("schedules a fresh frame for deltas after a flush", () => {
    const { frames, applied, c } = setup();
    c.content("a");
    frames.tick();
    c.content("b");
    frames.tick();
    expect(applied.map((b) => b.content)).toEqual(["a", "b"]);
    expect(frames.scheduled).toBe(2);
  });

  it("flush() applies synchronously and cancels the pending frame", () => {
    const { frames, applied, c } = setup();
    c.content("tail");
    c.flush();
    expect(applied).toEqual([{ content: "tail", thinking: "" }]);
    frames.tick(); // the cancelled frame must not apply anything again
    expect(applied).toHaveLength(1);
  });

  it("flush() with an empty buffer applies nothing", () => {
    const { applied, c } = setup();
    c.flush();
    expect(applied).toEqual([]);
  });

  it("cancel() drops the buffer unapplied", () => {
    const { frames, applied, c } = setup();
    c.content("gone");
    c.cancel();
    frames.tick();
    c.flush();
    expect(applied).toEqual([]);
  });
});
