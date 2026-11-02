// An inline edit box (a plot card's name or synopsis) that ends when the writer
// leaves it for the app's own UI, not on every blur (#2647). A browser writing
// assistant (ProWritingAid, Grammarly) draws its suggestion popup outside the app;
// a click there takes focus out of the box, and ending the edit on that blur
// unmounted the box before the assistant wrote its fix into it.
import type { Action } from "svelte/action";

/** Whether `target` is part of the app's own UI rather than something a browser
 *  extension injected: inside the app's mount root (when there is one) and not
 *  inside a custom element. Extensions draw their overlays in custom elements;
 *  the app renders none. `path` is the event's composedPath, which reaches into
 *  an extension's shadow DOM; without one, the target's ancestors are walked. */
export function isAppTarget(target: EventTarget | null, path: readonly EventTarget[] = []): boolean {
  if (!(target instanceof Node)) return false;
  const nodes = path.length ? path : ancestors(target);
  if (nodes.some((node) => node instanceof Element && node.localName.includes("-"))) return false;
  const root = document.getElementById("app");
  return root ? root.contains(target) : target.isConnected;
}

/** `node` and everything above it, crossing out of a shadow root to its host. */
function ancestors(node: Node): Node[] {
  const chain: Node[] = [];
  for (let at: Node | null = node; at; at = at instanceof ShadowRoot ? at.host : at.parentNode) chain.push(at);
  return chain;
}

/** Call `onLeave` when the writer presses elsewhere in the app, or moves focus to
 *  another of its controls. A blur toward anything else (an extension's popup,
 *  another window) keeps the box open, so a fix the assistant applies still lands
 *  in it. */
export const leaveOnAppExit: Action<HTMLElement, () => void> = (box, onLeave) => {
  let leave = onLeave;
  const onPress = (event: PointerEvent) => {
    if (!box.contains(event.target as Node) && isAppTarget(event.target, event.composedPath())) leave();
  };
  const onFocusOut = (event: FocusEvent) => {
    const next = event.relatedTarget;
    if (next && !box.contains(next as Node) && isAppTarget(next)) leave();
  };
  // Capture phase: a board control that stops propagation still ends the edit.
  document.addEventListener("pointerdown", onPress, true);
  box.addEventListener("focusout", onFocusOut);
  return {
    update(next) {
      leave = next;
    },
    destroy() {
      document.removeEventListener("pointerdown", onPress, true);
      box.removeEventListener("focusout", onFocusOut);
    },
  };
};
