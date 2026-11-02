// An inline edit box (a plot card's name or synopsis) that ends when the writer
// leaves it for the app's own UI, not on every blur (#2647). A browser writing
// assistant (ProWritingAid, Grammarly) draws its suggestion popup outside the app;
// a click there takes focus out of the box, and ending the edit on that blur
// unmounted the box before the assistant wrote its fix into it.
import type { Action } from "svelte/action";
import { APP_PORTAL_ATTR } from "./portal";

/** Whether `target` is part of the app's own UI rather than something a browser
 *  extension injected: inside the app's mount root (when there is one) or one of
 *  its popovers portaled to `<body>` (`data-app-portal`, portal.ts), and not
 *  inside a custom element. Extensions draw their overlays in custom elements;
 *  the app renders none. `path` is the event's composedPath, which reaches into
 *  an extension's shadow DOM; without one, the target's ancestors are walked. */
export function isAppTarget(target: EventTarget | null, path: readonly EventTarget[] = []): boolean {
  if (!(target instanceof Node)) return false;
  const nodes = path.length ? path : ancestors(target);
  const elements = nodes.filter((node): node is Element => node instanceof Element);
  if (elements.some((el) => el.localName.includes("-"))) return false;
  if (elements.some((el) => el.hasAttribute(APP_PORTAL_ATTR))) return true;
  const root = document.getElementById("app");
  return root ? root.contains(target) : target.isConnected;
}

/** `node` and everything above it, crossing out of a shadow root to its host. */
function ancestors(node: Node): Node[] {
  const chain: Node[] = [];
  for (let at: Node | null = node; at; at = at instanceof ShadowRoot ? at.host : at.parentNode) chain.push(at);
  return chain;
}

/** What an inline edit box does when the writer moves away from it. */
export interface InlineEditExit {
  /** Store what's typed, keeping the box open. */
  save: () => void;
  /** Store what's typed and end the edit. */
  leave: () => void;
}

/** `leave` when the writer presses elsewhere in the app, or moves focus to another
 *  of its controls. A blur toward anything else (an extension's popup, another
 *  window, the browser's own UI) only `save`s: the box stays open, so a fix the
 *  assistant applies still lands in it, and nothing typed is lost meanwhile. */
export const leaveOnAppExit: Action<HTMLElement, InlineEditExit> = (box, initial) => {
  let exit = initial;
  const onPress = (event: PointerEvent) => {
    if (!box.contains(event.target as Node) && isAppTarget(event.target, event.composedPath())) exit.leave();
  };
  const onFocusOut = (event: FocusEvent) => {
    const next = event.relatedTarget;
    if (next && box.contains(next as Node)) return;
    if (isAppTarget(next)) exit.leave();
    else exit.save();
  };
  // Capture phase: a board control that stops propagation still ends the edit.
  document.addEventListener("pointerdown", onPress, true);
  box.addEventListener("focusout", onFocusOut);
  return {
    update(next) {
      exit = next;
    },
    destroy() {
      document.removeEventListener("pointerdown", onPress, true);
      box.removeEventListener("focusout", onFocusOut);
    },
  };
};
