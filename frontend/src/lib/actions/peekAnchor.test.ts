// @vitest-environment happy-dom
// peekAnchor (#2011): the timer core (createPeekTimers) pinned directly with
// fake timers, then the DOM-wiring action's hover/touch/Escape/singleton
// contract on real elements.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bridgePeek, createPeekTimers, peekAnchor, type PeekAnchorParams } from "./peekAnchor";

// The `Action` type's return is `void | ActionReturn<...>` since a caller
// invoking it directly (not via `use:`) isn't statically known to get a
// handle back — but this action always returns one. A thin non-null wrapper
// keeps every call site's `.destroy()` untyped-cast-free.
function mountPeekAnchor(el: HTMLElement, params: PeekAnchorParams) {
  const handle = peekAnchor(el, params);
  if (!handle) throw new Error("peekAnchor returned no handle");
  return handle;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("createPeekTimers", () => {
  function make() {
    const onOpen = vi.fn();
    const onClose = vi.fn();
    const timers = createPeekTimers({ openDelay: 350, closeDelay: 150, onOpen, onClose });
    return { timers, onOpen, onClose };
  }

  it("opens after the delay and not before", () => {
    const { timers, onOpen } = make();
    timers.scheduleOpen();
    vi.advanceTimersByTime(349);
    expect(onOpen).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("leaving before the delay cancels the open — it never fires", () => {
    const { timers, onOpen } = make();
    timers.scheduleOpen();
    vi.advanceTimersByTime(200);
    timers.scheduleClose();
    vi.advanceTimersByTime(1000);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("leaving after open closes after the close delay", () => {
    const { timers, onOpen, onClose } = make();
    timers.scheduleOpen();
    vi.advanceTimersByTime(350);
    expect(onOpen).toHaveBeenCalledOnce();
    timers.scheduleClose();
    vi.advanceTimersByTime(149);
    expect(onClose).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("entering the card within the close delay cancels the close", () => {
    const { timers, onClose } = make();
    timers.scheduleOpen();
    vi.advanceTimersByTime(350);
    timers.scheduleClose();
    vi.advanceTimersByTime(100);
    timers.cancelClose(); // the card's mouseenter bridge
    vi.advanceTimersByTime(1000);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("openNow/closeNow bypass the delay", () => {
    const { timers, onOpen, onClose } = make();
    timers.openNow();
    expect(onOpen).toHaveBeenCalledOnce();
    timers.closeNow();
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("peekAnchor action", () => {
  function mount(el: HTMLElement, over: Partial<Parameters<typeof peekAnchor>[1]> = {}) {
    const onOpen = vi.fn();
    const onClose = vi.fn();
    const handle = mountPeekAnchor(el, { onOpen, onClose, ...over });
    return { handle, onOpen, onClose };
  }

  function fire(el: Element, type: string, init: MouseEventInit = {}) {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, ...init }));
  }

  it("hover opens after the default delay and not before", () => {
    const anchor = document.createElement("button");
    document.body.appendChild(anchor);
    const { onOpen } = mount(anchor);
    fire(anchor, "mouseover");
    vi.advanceTimersByTime(349);
    expect(onOpen).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onOpen).toHaveBeenCalledWith(anchor);
  });

  it("leaving before the delay cancels the open", () => {
    const anchor = document.createElement("button");
    document.body.appendChild(anchor);
    const { onOpen } = mount(anchor);
    fire(anchor, "mouseover");
    vi.advanceTimersByTime(200);
    fire(anchor, "mouseout", { relatedTarget: document.body });
    vi.advanceTimersByTime(1000);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("leaving after open closes after the close delay", () => {
    const anchor = document.createElement("button");
    document.body.appendChild(anchor);
    const { onOpen, onClose } = mount(anchor);
    fire(anchor, "mouseover");
    vi.advanceTimersByTime(350);
    expect(onOpen).toHaveBeenCalledOnce();
    fire(anchor, "mouseout", { relatedTarget: document.body });
    vi.advanceTimersByTime(149);
    expect(onClose).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("entering the card (via bridgePeek) within the close delay cancels the close", () => {
    const anchor = document.createElement("button");
    const cardEl = document.createElement("div");
    document.body.append(anchor, cardEl);
    const onOpen = vi.fn();
    const onClose = vi.fn();
    const handle = mountPeekAnchor(anchor, { onOpen, onClose });
    const unbridge = bridgePeek(cardEl);
    fire(anchor, "mouseover");
    vi.advanceTimersByTime(350);
    fire(anchor, "mouseout", { relatedTarget: document.body });
    vi.advanceTimersByTime(80);
    fire(cardEl, "mouseenter");
    vi.advanceTimersByTime(1000);
    expect(onClose).not.toHaveBeenCalled();
    unbridge();
    handle.destroy?.();
  });

  it("leaving the bridged card restarts the close", () => {
    const anchor = document.createElement("button");
    const cardEl = document.createElement("div");
    document.body.append(anchor, cardEl);
    const onOpen = vi.fn();
    const onClose = vi.fn();
    const handle = mountPeekAnchor(anchor, { onOpen, onClose });
    const unbridge = bridgePeek(cardEl);
    fire(anchor, "mouseover");
    vi.advanceTimersByTime(350);
    fire(anchor, "mouseout", { relatedTarget: document.body });
    vi.advanceTimersByTime(80);
    fire(cardEl, "mouseenter");
    fire(cardEl, "mouseleave");
    vi.advanceTimersByTime(150);
    expect(onClose).toHaveBeenCalledOnce();
    unbridge();
    handle.destroy?.();
  });

  it("a second anchor opening closes the first", () => {
    const a = document.createElement("button");
    const b = document.createElement("button");
    document.body.append(a, b);
    const { onOpen: openA, onClose: closeA } = mount(a);
    fire(a, "mouseover");
    vi.advanceTimersByTime(350);
    expect(openA).toHaveBeenCalledOnce();

    const { onOpen: openB } = mount(b);
    fire(b, "mouseover");
    vi.advanceTimersByTime(350);
    expect(openB).toHaveBeenCalledOnce();
    expect(closeA).toHaveBeenCalledOnce();
  });

  it("Escape closes the open card", () => {
    const anchor = document.createElement("button");
    document.body.appendChild(anchor);
    const { onClose } = mount(anchor);
    fire(anchor, "mouseover");
    vi.advanceTimersByTime(350);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("a touch pointerdown toggles the card open, then closed, and swallows the follow-up click", () => {
    const anchor = document.createElement("button");
    document.body.appendChild(anchor);
    const { onOpen, onClose } = mount(anchor);
    const down = new PointerEvent("pointerdown", { bubbles: true, cancelable: true, pointerType: "touch" });
    anchor.dispatchEvent(down);
    expect(onOpen).toHaveBeenCalledOnce(); // immediate, no delay

    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    anchor.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true); // swallowed, not a second navigation

    anchor.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, pointerType: "touch" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
