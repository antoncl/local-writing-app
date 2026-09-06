// @vitest-environment happy-dom
// The shared in-pane popover primitive (#1573): portal the popover to <body>
// and pin it at viewport coords off its trigger, so a pane's `overflow` box
// can't clip it. Positioning maths are layout-driven (happy-dom reports zero
// rects), so these assert the structural contract — reparent, fixed position,
// clean teardown — which is what makes the popover escape the clip.
import { afterEach, describe, expect, it, vi } from "vitest";
import { anchoredPopover } from "./anchoredPopover";

describe("anchoredPopover", () => {
  it("portals the node to <body> and pins it fixed", () => {
    const anchor = document.createElement("button");
    const host = document.createElement("div");
    const pop = document.createElement("div");
    host.appendChild(pop); // starts nested under a would-be clipping container
    document.body.appendChild(anchor);
    document.body.appendChild(host);

    const handle = anchoredPopover(pop, { anchor });

    // Lifted out of its nesting container, straight under <body>.
    expect(pop.parentElement).toBe(document.body);
    // Fixed positioning is what resolves it against the viewport, not the
    // (clipped/transformed) pane — the action owns this, not the CSS.
    expect(pop.style.position).toBe("fixed");
    expect(pop.style.left).not.toBe("");
    expect(pop.style.top).not.toBe("");

    handle.destroy();
    expect(pop.isConnected).toBe(false);
  });

  it("no-ops positioning when the anchor is missing but still mounts", () => {
    const pop = document.createElement("div");
    document.body.appendChild(pop);
    const handle = anchoredPopover(pop, { anchor: null });
    expect(pop.parentElement).toBe(document.body);
    expect(pop.style.position).toBe("fixed");
    handle.destroy();
    expect(pop.isConnected).toBe(false);
  });

  it("does not re-snap to (0, gap) once the anchor is detached from the DOM (#1803 review)", () => {
    const anchor = document.createElement("button");
    const pop = document.createElement("div");
    document.body.append(anchor, pop);
    // happy-dom reports a zero rect for every element by default, which would
    // make a real vs. a detached-anchor reposition indistinguishable — stub a
    // non-zero rect so a genuine snap-to-(0,gap) is observable.
    anchor.getBoundingClientRect = () =>
      ({ left: 40, right: 140, top: 20, bottom: 40, width: 100, height: 20, x: 40, y: 20, toJSON: () => ({}) }) as DOMRect;

    const handle = anchoredPopover(pop, { anchor });
    const leftAfterMount = pop.style.left;
    const topAfterMount = pop.style.top;
    expect(leftAfterMount).not.toBe("0px"); // sanity: the stubbed rect took effect

    anchor.remove(); // detached — isConnected is now false, rect would read zero
    handle.update({ anchor });

    // Left at its last real position, not snapped to (0, gap).
    expect(pop.style.left).toBe(leftAfterMount);
    expect(pop.style.top).toBe(topAfterMount);

    handle.destroy();
  });

  // #1586/#1587: the two options SwatchPicker/ColoredSelect/the schema
  // type-grid needed to retire their own inline rect-anchoring copies.
  // happy-dom reports zero rects and zero offsetWidth, so both are stubbed.
  describe("align / matchWidth (#1586, #1587)", () => {
    const origInnerWidth = window.innerWidth;

    afterEach(() => {
      Object.defineProperty(window, "innerWidth", { value: origInnerWidth, configurable: true });
    });

    function makeAnchorAndPop(rect: Partial<DOMRect>) {
      const anchor = document.createElement("button");
      const pop = document.createElement("div");
      document.body.append(anchor, pop);
      anchor.getBoundingClientRect = () =>
        ({ left: 400, right: 500, top: 20, bottom: 40, width: 100, height: 20, x: 400, y: 20, toJSON: () => ({}), ...rect }) as DOMRect;
      Object.defineProperty(pop, "offsetWidth", { value: 200, configurable: true });
      Object.defineProperty(pop, "offsetHeight", { value: 50, configurable: true });
      return { anchor, pop };
    }

    it('align: "right" puts the popover\'s right edge on the trigger\'s right edge', () => {
      Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
      const { anchor, pop } = makeAnchorAndPop({});
      const handle = anchoredPopover(pop, { anchor, align: "right" });
      expect(pop.style.left).toBe("300px"); // r.right 500 - w 200
      handle.destroy();
    });

    it("default align left-aligns with the trigger", () => {
      Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
      const { anchor, pop } = makeAnchorAndPop({});
      const handle = anchoredPopover(pop, { anchor });
      expect(pop.style.left).toBe("400px");
      handle.destroy();
    });

    it('align: "right" falls back to left-aligning (clamped) when right-aligning would overrun the left edge', () => {
      Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
      const { anchor, pop } = makeAnchorAndPop({ left: 50, right: 150 });
      const handle = anchoredPopover(pop, { anchor, align: "right" });
      // 150 - 200 < 8, so falls back to min(r.left, innerWidth - w - 8) = min(50, 992) = 50
      expect(pop.style.left).toBe("50px");
      handle.destroy();
    });

    it("matchWidth sets min-width to the anchor's width; off by default leaves it unset", () => {
      Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
      const { anchor, pop } = makeAnchorAndPop({});
      const handle = anchoredPopover(pop, { anchor, matchWidth: true });
      expect(pop.style.minWidth).toBe("100px");
      handle.destroy();

      const { anchor: anchor2, pop: pop2 } = makeAnchorAndPop({});
      const handle2 = anchoredPopover(pop2, { anchor: anchor2 });
      expect(pop2.style.minWidth).toBe("");
      handle2.destroy();
    });
  });

  // #245 (ADR-0082 slice 2b generalised TagPicker's inline copy here): under a
  // zoomed/panned SvelteFlow canvas the anchor moves on screen WITHOUT firing
  // scroll/resize (the canvas transform moves it, not the page), so `track`
  // re-measures every animation frame instead. These pin the RAF lifecycle —
  // the actual left/top maths are covered by the mount test above (happy-dom
  // reports zero rects, so a "did it move" assertion needs real layout, out of
  // reach here).
  describe("track (#245 anchor-track)", () => {
    // vi.stubGlobal, not vi.spyOn(window, ...): the DOM lib's overloaded
    // requestAnimationFrame/cancelAnimationFrame signatures make a typed
    // mockImplementation callback infeasible here; stubGlobal swaps the
    // property directly and needs no call-signature inference.
    afterEach(() => vi.unstubAllGlobals());

    it("does not schedule an animation frame when track is off (the default)", () => {
      const raf = vi.fn();
      vi.stubGlobal("requestAnimationFrame", raf);
      const anchor = document.createElement("button");
      const pop = document.createElement("div");
      document.body.append(anchor, pop);

      const handle = anchoredPopover(pop, { anchor });
      expect(raf).not.toHaveBeenCalled();

      handle.destroy();
    });

    it("re-measures every frame while track is on, and stops on destroy", () => {
      let frame: FrameRequestCallback | null = null;
      let nextId = 1;
      const raf = vi.fn((cb: FrameRequestCallback) => {
        frame = cb;
        return nextId++;
      });
      const caf = vi.fn();
      vi.stubGlobal("requestAnimationFrame", raf);
      vi.stubGlobal("cancelAnimationFrame", caf);
      const anchor = document.createElement("button");
      const pop = document.createElement("div");
      document.body.append(anchor, pop);

      const handle = anchoredPopover(pop, { anchor, track: true });
      // One frame scheduled on mount.
      expect(raf).toHaveBeenCalledTimes(1);

      // Firing the scheduled frame re-measures and schedules the NEXT one —
      // the loop, not a one-shot.
      // Cast, not `frame?.(0)`: TS narrows a captured `let` to its declared
      // initializer (`null`) at a later read, unaware the mock closure above
      // reassigned it — a `never` call-signature false positive, not a real
      // nullability risk (the mock ran synchronously on mount, just above).
      (frame as unknown as FrameRequestCallback)(0);
      expect(raf).toHaveBeenCalledTimes(2);

      handle.destroy();
      // The pending frame is cancelled, not left to fire into a torn-down node.
      expect(caf).toHaveBeenCalled();
    });

    it("update() toggles the loop on/off without a remount", () => {
      let scheduled = 0;
      const raf = vi.fn(() => ++scheduled);
      const caf = vi.fn();
      vi.stubGlobal("requestAnimationFrame", raf);
      vi.stubGlobal("cancelAnimationFrame", caf);
      const anchor = document.createElement("button");
      const pop = document.createElement("div");
      document.body.append(anchor, pop);

      const handle = anchoredPopover(pop, { anchor, track: false });
      expect(scheduled).toBe(0);

      handle.update({ anchor, track: true });
      expect(scheduled).toBe(1);

      handle.update({ anchor, track: false });
      expect(caf).toHaveBeenCalled();

      handle.destroy();
    });
  });
});
