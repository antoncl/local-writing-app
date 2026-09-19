// Hover/keyboard/touch anchor for a reference peek card (#2011). Mirrors the
// split `anchoredPopover`/`foldToFirstRow` already use: a pure timer core
// (`createPeekTimers`, unit-testable with fake timers) + a thin DOM-wiring
// action. The action owns ONLY open/close timing — the site owns what "open"
// means (which ref, which anchor, what to render): `onOpen(anchor)` receives
// the element to float the card off (the node itself, or — in delegated mode
// — the hovered descendant); `onClose()` tears the card down.
//
// Click on the anchor is NEVER intercepted — a ref pill still navigates, a
// tag-line hit still opens its editor; the peek card is a hover/focus
// preview layered on top, not a replacement for the click affordance. Touch
// is the one exception: there is no hover, so a touch pointerdown toggles the
// card immediately and swallows the click that follows it (else the click
// would ALSO fire the anchor's own handler the instant the card opens).
//
// The card is rendered by the SITE (often body-portaled, e.g. inside
// `PeekCard`'s own `anchoredPopover`), not by this action — so bridging hover
// across the gap onto the card is a separate export, `bridgePeek(cardEl)`:
// `PeekCard` calls it with its own root element once mounted, and it wires
// straight into whichever peek is the current module-level singleton
// (mouseenter cancels the pending close, mouseleave restarts it) — the same
// shape `createHoverCard`'s `keep()`/`hideSoon()` bridge uses for the prose
// hover card.
//
// One peek open at a time (module-level): opening a new one closes whatever
// was open through ITS OWN onClose, so every site's state stays truthful.

import type { Action } from "svelte/action";

export type PeekTimersParams = {
  openDelay: number;
  closeDelay: number;
  onOpen: () => void;
  onClose: () => void;
};

export type PeekTimers = {
  scheduleOpen(): void;
  cancelOpen(): void;
  scheduleClose(): void;
  cancelClose(): void;
  /** Open immediately, bypassing the delay (touch). Cancels any pending
   *  timer first. A no-op when already open. */
  openNow(): void;
  /** Close immediately, bypassing the delay (Escape, a second anchor
   *  opening, touch-toggle-off). Cancels any pending timer first. A no-op
   *  when not open. */
  closeNow(): void;
  readonly isOpen: boolean;
  destroy(): void;
};

/** Pure timer core — no DOM, no globals beyond setTimeout/clearTimeout, so a
 *  fake-timers test can pin every edge. `onOpen`/`onClose` fire exactly once
 *  per open/close; scheduling the same edge twice while it's already pending
 *  (or already in that state) is a no-op — mirrors the prose hover card's
 *  `hideSoon`. Delays are read fresh off `params` on every call, so a live
 *  caller (the action below) can update them without recreating the timers. */
export function createPeekTimers(params: PeekTimersParams): PeekTimers {
  let openTimer: ReturnType<typeof setTimeout> | null = null;
  let closeTimer: ReturnType<typeof setTimeout> | null = null;
  let open = false;

  function cancelOpen() {
    if (openTimer !== null) {
      clearTimeout(openTimer);
      openTimer = null;
    }
  }
  function cancelClose() {
    if (closeTimer !== null) {
      clearTimeout(closeTimer);
      closeTimer = null;
    }
  }
  function scheduleOpen() {
    if (open || openTimer !== null) return;
    cancelClose();
    openTimer = setTimeout(() => {
      openTimer = null;
      open = true;
      params.onOpen();
    }, params.openDelay);
  }
  function scheduleClose() {
    // Leaving before the open delay elapsed cancels the open outright — it
    // never fires, so there is nothing to schedule a close for.
    cancelOpen();
    if (!open || closeTimer !== null) return;
    closeTimer = setTimeout(() => {
      closeTimer = null;
      open = false;
      params.onClose();
    }, params.closeDelay);
  }
  function openNow() {
    cancelOpen();
    cancelClose();
    if (open) return;
    open = true;
    params.onOpen();
  }
  function closeNow() {
    cancelOpen();
    cancelClose();
    if (!open) return;
    open = false;
    params.onClose();
  }
  function destroy() {
    cancelOpen();
    cancelClose();
  }

  return {
    scheduleOpen,
    cancelOpen,
    scheduleClose,
    cancelClose,
    openNow,
    closeNow,
    get isOpen() {
      return open;
    },
    destroy,
  };
}

export type PeekAnchorParams = {
  onOpen: (anchor: HTMLElement) => void;
  onClose: () => void;
  openDelay?: number;
  closeDelay?: number;
  /** Delegated mode (RailTagLine's one-button rest line): a CSS selector for
   *  a descendant to treat as the anchor instead of the action's own node —
   *  `onOpen` receives the matched descendant, found via `.closest(delegate)`
   *  off the hovered/focused element. */
  delegate?: string;
};

const DEFAULT_OPEN_DELAY = 350;
const DEFAULT_CLOSE_DELAY = 150;

type SingletonHandle = { closeNow: () => void; cancelClose: () => void; scheduleClose: () => void };

// One peek open at a time, across every `peekAnchor` instance on the page —
// also the bridge target for `bridgePeek` below, since the card that needs
// bridging is always whichever peek is currently open.
let activePeek: SingletonHandle | null = null;
function claimSingleton(handle: SingletonHandle) {
  if (activePeek && activePeek !== handle) activePeek.closeNow();
  activePeek = handle;
}
function releaseSingleton(handle: SingletonHandle) {
  if (activePeek === handle) activePeek = null;
}

/** Close whichever peek is open, from OUTSIDE its anchor action — the card's
 *  own Escape / outside-pointerdown handlers call this so the action's timers
 *  and the singleton agree with the site (otherwise the action still believes
 *  it is open and the next hover, focus or tap on the same anchor is
 *  swallowed). Closing runs the action's own `onClose`, so a site must expect
 *  it after calling this. A no-op when nothing is open. */
export function closeActivePeek(): void {
  activePeek?.closeNow();
}

/** Wire the open card's own root element into the singleton's close timer:
 *  crossing onto the card cancels a pending close, leaving it restarts one —
 *  the same bridge `createHoverCard`'s `keep()`/`hideSoon()` gives the prose
 *  hover card. `PeekCard` calls this with its own root element once mounted
 *  and runs the returned cleanup on teardown; it needs no reference to
 *  whichever `peekAnchor` instance opened it; the singleton always names it. */
export function bridgePeek(cardEl: HTMLElement): () => void {
  const onEnter = () => activePeek?.cancelClose();
  const onLeave = () => activePeek?.scheduleClose();
  cardEl.addEventListener("mouseenter", onEnter);
  cardEl.addEventListener("mouseleave", onLeave);
  return () => {
    cardEl.removeEventListener("mouseenter", onEnter);
    cardEl.removeEventListener("mouseleave", onLeave);
  };
}

export const peekAnchor: Action<HTMLElement, PeekAnchorParams> = (node, params) => {
  let current = params;
  let delegateTarget: HTMLElement | null = null;

  function resolveAnchor(): HTMLElement | null {
    return current.delegate ? delegateTarget : node;
  }

  function handleOpen() {
    document.addEventListener("keydown", onKeydown, true);
    const anchor = resolveAnchor();
    if (anchor) current.onOpen(anchor);
  }
  function handleClose() {
    document.removeEventListener("keydown", onKeydown, true);
    releaseSingleton(singletonHandle);
    current.onClose();
  }
  const timers = createPeekTimers({
    get openDelay() {
      return current.openDelay ?? DEFAULT_OPEN_DELAY;
    },
    get closeDelay() {
      return current.closeDelay ?? DEFAULT_CLOSE_DELAY;
    },
    onOpen: () => {
      claimSingleton(singletonHandle);
      handleOpen();
    },
    onClose: handleClose,
  });
  const singletonHandle: SingletonHandle = {
    closeNow: () => timers.closeNow(),
    cancelClose: () => timers.cancelClose(),
    scheduleClose: () => timers.scheduleClose(),
  };

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") timers.closeNow();
  }

  // --- Hover (mouse) --------------------------------------------------
  function onMouseOver(event: MouseEvent) {
    if (current.delegate) {
      const target = (event.target as Element | null)?.closest<HTMLElement>(current.delegate) ?? null;
      if (!target || target === delegateTarget) return;
      delegateTarget = target;
      timers.scheduleOpen();
      return;
    }
    timers.scheduleOpen();
  }
  function onMouseOut(event: MouseEvent) {
    if (current.delegate) {
      if (!delegateTarget) return;
      const related = event.relatedTarget;
      if (related instanceof Node && delegateTarget.contains(related)) return;
      delegateTarget = null;
      timers.scheduleClose();
      return;
    }
    const related = event.relatedTarget;
    if (related instanceof Node && node.contains(related)) return;
    timers.scheduleClose();
  }

  // --- Keyboard (focus-visible) ----------------------------------------
  function onFocusIn(event: FocusEvent) {
    if (current.delegate) return; // the delegated rest line has no per-name focus stop
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    // Only a keyboard-visible focus opens the card — a mouse-driven focus
    // (already covered by mouseover) must not double-schedule.
    if (typeof target.matches === "function" && target.matches(":focus-visible")) timers.scheduleOpen();
  }
  function onFocusOut(event: FocusEvent) {
    if (current.delegate) return;
    const related = event.relatedTarget;
    if (related instanceof Node && node.contains(related)) return;
    timers.scheduleClose();
  }

  // --- Touch: toggle + swallow the follow-up click ----------------------
  let suppressNextClick = false;
  function onPointerDown(event: PointerEvent) {
    if (event.pointerType !== "touch") return;
    if (current.delegate) {
      // A touch that lands on the rest line but not on a name is the line's
      // own click (open the editor) — only a name toggles a peek, and only a
      // toggled peek swallows the follow-up click.
      const target = (event.target as Element | null)?.closest<HTMLElement>(current.delegate) ?? null;
      if (!target) return;
      delegateTarget = target;
    }
    suppressNextClick = true;
    if (timers.isOpen) timers.closeNow();
    else timers.openNow();
  }
  function onClickCapture(event: MouseEvent) {
    if (!suppressNextClick) return;
    suppressNextClick = false;
    event.preventDefault();
    event.stopPropagation();
  }

  node.addEventListener("mouseover", onMouseOver);
  node.addEventListener("mouseout", onMouseOut);
  node.addEventListener("focusin", onFocusIn);
  node.addEventListener("focusout", onFocusOut);
  node.addEventListener("pointerdown", onPointerDown);
  node.addEventListener("click", onClickCapture, true);

  return {
    update(next: PeekAnchorParams) {
      current = next;
    },
    destroy() {
      node.removeEventListener("mouseover", onMouseOver);
      node.removeEventListener("mouseout", onMouseOut);
      node.removeEventListener("focusin", onFocusIn);
      node.removeEventListener("focusout", onFocusOut);
      node.removeEventListener("pointerdown", onPointerDown);
      node.removeEventListener("click", onClickCapture, true);
      document.removeEventListener("keydown", onKeydown, true);
      releaseSingleton(singletonHandle);
      timers.destroy();
    },
  };
};
