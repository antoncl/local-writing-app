// A Svelte action that turns a popover element into a body-portaled, viewport-
// anchored layer — so it escapes any `overflow`/`transform` ancestor that would
// otherwise clip it (#1573).
//
// Why this exists: an in-pane popover positioned `absolute` inside a pane's
// `overflow: auto` box gets cut off the moment the pane is short (its lower rows
// become unreachable). A viewport-based `flipUp` guess doesn't help — it reads
// `window.innerHeight`, not the pane's own clip box, so with room below the fold
// it never flips and still clips. The robust fix is to lift the popover out of
// the pane entirely: portal it to `<body>` (via `portalToBody`) and pin it at
// coords derived from the trigger's `getBoundingClientRect()`.
//
// SwatchPicker and TagPicker each already carry an inline copy of this
// rect-anchoring logic; this generalises it so any future in-pane popover has
// one home rather than a fourth copy.
//
// Contract (mirrors portalToBody's): mount this only while the popover is open
// (behind an `{#if}`); give the popover a stable class so the caller's
// outside-click handler can still recognise clicks inside it, since it no longer
// lives under the trigger. The popover supplies its own visual chrome + z-index
// in CSS; the action owns only `position: fixed` and the `left`/`top` coords.

import { portalToBody } from "./portal";

export interface AnchoredPopoverParams {
  /** The trigger element the popover floats against. */
  anchor: HTMLElement | null | undefined;
  /** Gap in px between the trigger and the popover (default 6). */
  gap?: number;
  /** #245: re-measure the anchor every animation frame while mounted, on top
   *  of the scroll/resize listeners below — for a popover hosted under a
   *  zoomed/panned SvelteFlow canvas (ViewFlowNode), where the anchor moves
   *  on screen WITHOUT firing scroll/resize (the canvas transform, not the
   *  page, moves it). Keeps the popover glued to the node at native 1× scale
   *  ("anchor-track"), not scaled with the canvas. Off by default — the
   *  scroll/resize path alone is enough outside a transformed ancestor, and a
   *  RAF loop is needless work for every other host. Mirrors the tracking
   *  loop TagPicker carried before ADR-0082 slice 2b generalised it here. */
  track?: boolean;
}

export function anchoredPopover(node: HTMLElement, params: AnchoredPopoverParams) {
  let current = params;
  // Structural, not cosmetic: fixed positioning is what lets the portaled node
  // resolve against the viewport instead of a clipped/transformed ancestor.
  node.style.position = "fixed";
  const portal = portalToBody(node);

  // The last-applied rect, so the RAF loop reassigns styles only when the
  // anchor actually moved — otherwise it would write `left`/`top` every frame
  // even while the canvas sits idle, thrashing layout (and, for a caller that
  // mirrors these coords into Svelte state, its reactivity) for nothing.
  let lastLeft = NaN;
  let lastTop = NaN;

  function reposition() {
    const anchor = current.anchor;
    if (!anchor) return;
    // A detached anchor (its node removed from the DOM while the popover is
    // still open) reports a zero rect — without this guard `track`'s RAF loop
    // would snap the popover to (0, gap) every frame instead of leaving it at
    // its last real position (review, #1803).
    if (!anchor.isConnected) return;
    const gap = current.gap ?? 6;
    const r = anchor.getBoundingClientRect();
    // The node is already in the DOM (portalToBody appended it), so reading its
    // offset size forces one sync layout and returns real dimensions — no
    // one-frame flash at (0,0) that a deferred measure would show.
    const w = node.offsetWidth;
    const h = node.offsetHeight;
    // Open below + left-aligned with the trigger; right-align under it when the
    // left edge would overrun the viewport.
    let left = r.left;
    if (left + w + 8 > window.innerWidth) left = Math.max(8, r.right - w);
    // Flip above when there isn't room below, clamping into view (8px margin)
    // rather than refusing the flip — so a popover shorter than the viewport is
    // always fully visible instead of hanging a few px past the bottom edge.
    let top = r.bottom + gap;
    if (top + h + 8 > window.innerHeight) {
      top = Math.max(8, r.top - h - gap);
    }
    if (left === lastLeft && top === lastTop) return;
    lastLeft = left;
    lastTop = top;
    node.style.left = `${left}px`;
    node.style.top = `${top}px`;
  }

  reposition();
  // Capture phase so a scroll inside the pane (which doesn't bubble to window)
  // still re-pins the popover to the moving trigger.
  const onScrollResize = () => reposition();
  window.addEventListener("scroll", onScrollResize, true);
  window.addEventListener("resize", onScrollResize);

  let rafId = 0;
  function trackLoop() {
    reposition();
    rafId = requestAnimationFrame(trackLoop);
  }
  function startTracking() {
    if (!rafId) rafId = requestAnimationFrame(trackLoop);
  }
  function stopTracking() {
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
  }
  if (current.track) startTracking();

  return {
    update(next: AnchoredPopoverParams) {
      current = next;
      reposition();
      if (next.track) startTracking();
      else stopTracking();
    },
    destroy() {
      window.removeEventListener("scroll", onScrollResize, true);
      window.removeEventListener("resize", onScrollResize);
      stopTracking();
      portal.destroy();
    },
  };
}
