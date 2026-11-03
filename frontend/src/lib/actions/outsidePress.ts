// One place for what counts as "outside" a menu (#2649). Capture phase, so a canvas
// press that stops propagation still closes it. A popover the menu opened is portaled
// to <body> (`data-app-portal`) and counts as inside; a press on a browser extension's
// overlay is not the app's and leaves the menu alone. `focusout` is deliberately not
// used: a menu that swaps pages removes the focused button, which would close it.
import type { Action } from "svelte/action";
import { isAppTarget } from "./inlineEdit";
import { APP_PORTAL_ATTR } from "./portal";

/** Whether `event` is a press on the app's own UI that is neither within `node` nor
 *  within a popover portaled out of it. */
export function isOutsidePress(node: Element, event: Event): boolean {
  const target = event.target;
  if (!(target instanceof Node)) return false;
  if (node.contains(target)) return false;
  const path = event.composedPath();
  if (path.some((el) => el instanceof Element && el.hasAttribute(APP_PORTAL_ATTR))) return false;
  return isAppTarget(target, path);
}

export interface OutsidePressParams {
  open: boolean;
  close: () => void;
}

/** While `open`, `close` on a press outside `node` or on Escape. */
export const closeOnOutsidePress: Action<HTMLElement, OutsidePressParams> = (node, initial) => {
  let params = initial;
  const onDown = (event: PointerEvent) => {
    if (isOutsidePress(node, event)) params.close();
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") params.close();
  };
  let attached = false;
  const sync = () => {
    if (params.open === attached) return;
    attached = params.open;
    if (attached) {
      window.addEventListener("pointerdown", onDown, true);
      window.addEventListener("keydown", onKey, true);
    } else {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    }
  };
  sync();
  return {
    update(next) {
      params = next;
      sync();
    },
    destroy() {
      params = { ...params, open: false };
      sync();
    },
  };
};
