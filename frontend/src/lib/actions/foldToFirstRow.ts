// A pure fit helper + Svelte action for folding a wrapping pill row down to its
// first line + a trailing `+N` chip (#1884 slice 2) — the rail's `entity_ref_list`
// pill row is otherwise every pill, always, which can run a list field to eight
// rows for a 20-value field. `firstRowFit` is pure geometry (unit-tested on its
// own, no DOM); `foldToFirstRow` is the thin DOM-measuring wrapper that calls it.

import type { Action } from "svelte/action";

export type PillBox = { left: number; right: number; top: number };

/** How many leading pills stay visible on the first line when the row is
 *  folded. `chipWidth` is the measured width of the `+N` chip that must also
 *  sit on that line whenever anything is hidden; `gap` the flex gap. Pure.
 *  - all pills share the first line's top → every pill visible (no chip);
 *  - otherwise the first-line pills, minus as many trailing ones as it takes
 *    for `+N` to fit before `containerRight`; never below 0 (chip alone). */
export function firstRowFit(pills: PillBox[], containerRight: number, chipWidth: number, gap: number): number {
  if (pills.length === 0) return 0;
  const rowTop = pills[0].top;
  let n = 0;
  while (n < pills.length && pills[n].top === rowTop) n++;
  if (n === pills.length) return pills.length;
  let visible = n;
  while (visible > 0 && pills[visible - 1].right + gap + chipWidth > containerRight) visible--;
  return visible;
}

export type FoldToFirstRowParams = { enabled: boolean; total: number; onFit: (visible: number) => void };

// A rendered `+NN` chip at --fs-sm is ~36px; used only on the first measure
// after a value change, before the chip itself exists to measure (nothing is
// hidden yet, so nothing has rendered one) — see the module doc above.
const FALLBACK_CHIP_WIDTH = 40;

/** Measures the node's `.ref-pill` children (in DOM order) and the `.ref-pill-more`
 *  chip, calls `onFit(visible)` — and re-measures when the node resizes (ResizeObserver,
 *  when the environment has one) or the params change. With `enabled: false` it
 *  reports `total` (nothing hidden) and observes nothing. */
export const foldToFirstRow: Action<HTMLElement, FoldToFirstRowParams> = (node, params) => {
  let current = params;
  // Re-entrancy guard: onFit can drive a re-render (visibleCount changes,
  // pills toggle display) that a ResizeObserver could otherwise notice mid-
  // measurement and loop on. `measuring` blocks a nested call; `lastWidth`
  // means the RO only re-measures when the node's own width actually changed.
  let measuring = false;
  let lastWidth = -1;

  function measure() {
    if (measuring) return;
    if (!current.enabled) {
      current.onFit(current.total);
      return;
    }
    measuring = true;
    try {
      // Un-hide every pill (see the component's `[data-measuring]` CSS) so the
      // fold is computed against real, laid-out widths, not the folded subset.
      node.dataset.measuring = "";
      const pillRects = [...node.querySelectorAll(".ref-pill:not(.ref-pill-more)")].map((el) =>
        el.getBoundingClientRect(),
      );
      const chip = node.querySelector(".ref-pill-more");
      const chipWidth = chip ? chip.getBoundingClientRect().width : FALLBACK_CHIP_WIDTH;
      const containerRect = node.getBoundingClientRect();
      const gap = parseFloat(getComputedStyle(node).columnGap) || 0;
      lastWidth = containerRect.width;

      // No layout at all (the test harness, happy-dom rects are all zero) — the
      // fold degrades to "everything fits": all pills visible, no chip.
      const noLayout = pillRects.every((r) => r.width === 0 && r.height === 0);
      if (noLayout) {
        current.onFit(current.total);
        return;
      }
      const boxes: PillBox[] = pillRects.map((r) => ({ left: r.left, right: r.right, top: r.top }));
      current.onFit(firstRowFit(boxes, containerRect.right, chipWidth, gap));
    } finally {
      delete node.dataset.measuring;
      measuring = false;
    }
  }

  measure();

  let ro: ResizeObserver | undefined;
  if (typeof ResizeObserver !== "undefined") {
    ro = new ResizeObserver(() => {
      if (node.getBoundingClientRect().width !== lastWidth) measure();
    });
    ro.observe(node);
  }

  return {
    update(next: FoldToFirstRowParams) {
      current = next;
      measure();
    },
    destroy() {
      ro?.disconnect();
    },
  };
};
