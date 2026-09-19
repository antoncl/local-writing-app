// @vitest-environment happy-dom
// scrollMemory (#2013) — the pure restore-gate and the rAF-throttled scroll
// listener behind ProseBodyView's/ReferenceListTab's scroll memory, pinned
// without mounting either (TipTap and ViewNodeList are not reliably
// mountable under happy-dom — see reference_svelteflow_headless_limits-style
// traps).
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyScrollWhenLaidOut, rememberScrollOnScroll, scrollRestorePlan } from "./scrollMemory";

describe("scrollRestorePlan", () => {
  it("restores now on a boundary load into a laid-out frame", () => {
    expect(scrollRestorePlan("boundary", 400)).toBe("now");
  });

  it("never restores on a reconcile load", () => {
    expect(scrollRestorePlan("reconcile", 400)).toBe("skip");
    expect(scrollRestorePlan("reconcile", 0)).toBe("skip");
  });

  it("defers when the frame has no height yet (reopened on a list tab)", () => {
    expect(scrollRestorePlan("boundary", 0)).toBe("defer");
  });
});

describe("applyScrollWhenLaidOut", () => {
  afterEach(() => vi.unstubAllGlobals());

  // A hand-rolled ResizeObserver: happy-dom has none, and the real one only
  // fires on layout, which no headless DOM performs.
  function stubResizeObserver() {
    const instances: { cb: ResizeObserverCallback; disconnect: ReturnType<typeof vi.fn> }[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        disconnect = vi.fn();
        constructor(public cb: ResizeObserverCallback) {
          instances.push(this);
        }
        observe() {}
        unobserve() {}
      },
    );
    return instances;
  }

  it("applies the pending offset once the element has height, then clears it", () => {
    const instances = stubResizeObserver();
    const el = document.createElement("div");
    let height = 0;
    Object.defineProperty(el, "clientHeight", { get: () => height });
    let pending: number | null = 320;
    const clear = vi.fn(() => {
      pending = null;
    });
    applyScrollWhenLaidOut(el, () => pending, clear);

    instances[0].cb([], instances[0] as unknown as ResizeObserver);
    expect(el.scrollTop).toBe(0);
    expect(clear).not.toHaveBeenCalled();

    height = 500;
    instances[0].cb([], instances[0] as unknown as ResizeObserver);
    expect(el.scrollTop).toBe(320);
    expect(clear).toHaveBeenCalledTimes(1);

    // Nothing pending any more: a later resize leaves the writer's scroll alone.
    el.scrollTop = 40;
    instances[0].cb([], instances[0] as unknown as ResizeObserver);
    expect(el.scrollTop).toBe(40);
  });

  it("disconnects the observer on the returned teardown", () => {
    const instances = stubResizeObserver();
    const off = applyScrollWhenLaidOut(document.createElement("div"), () => null, () => {});
    off();
    expect(instances[0].disconnect).toHaveBeenCalledTimes(1);
  });

  it("is a no-op where ResizeObserver is missing", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    expect(() => applyScrollWhenLaidOut(document.createElement("div"), () => 1, () => {})()).not.toThrow();
  });
});

describe("rememberScrollOnScroll", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("records scrollTop under the current key, throttled to one call per animation frame", () => {
    let frame: FrameRequestCallback | null = null;
    const raf = vi.fn((cb: FrameRequestCallback) => {
      frame = cb;
      return 1;
    });
    vi.stubGlobal("requestAnimationFrame", raf);

    const el = document.createElement("div");
    Object.defineProperty(el, "scrollTop", { value: 0, writable: true });
    const memory = { rememberScroll: vi.fn() };
    let nodeId = "node_a";
    rememberScrollOnScroll(el, () => ({ nodeId, surface: "body" }), memory);

    // Two scroll events before the frame fires — only one rAF scheduled.
    el.dispatchEvent(new Event("scroll"));
    (el as unknown as { scrollTop: number }).scrollTop = 40;
    el.dispatchEvent(new Event("scroll"));
    expect(raf).toHaveBeenCalledTimes(1);

    // The key is read at FIRE time, not attach time — a node switch between
    // the scroll and the frame lands under the new key.
    nodeId = "node_b";
    (frame as unknown as FrameRequestCallback)(0);
    expect(memory.rememberScroll).toHaveBeenCalledWith("node_b", "body", 40);
  });

  it("skips the record when the key resolves to null (e.g. no open node)", () => {
    let frame: FrameRequestCallback | null = null;
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((cb: FrameRequestCallback) => {
        frame = cb;
        return 1;
      }),
    );
    const el = document.createElement("div");
    const memory = { rememberScroll: vi.fn() };
    rememberScrollOnScroll(el, () => null, memory);

    el.dispatchEvent(new Event("scroll"));
    (frame as unknown as FrameRequestCallback)(0);
    expect(memory.rememberScroll).not.toHaveBeenCalled();
  });

  it("the returned unsubscribe stops future scroll events from scheduling a frame", () => {
    const raf = vi.fn(() => 1);
    vi.stubGlobal("requestAnimationFrame", raf);
    const el = document.createElement("div");
    const memory = { rememberScroll: vi.fn() };
    const unsubscribe = rememberScrollOnScroll(el, () => ({ nodeId: "node_a", surface: "body" }), memory);

    unsubscribe();
    el.dispatchEvent(new Event("scroll"));
    expect(raf).not.toHaveBeenCalled();
  });
});
