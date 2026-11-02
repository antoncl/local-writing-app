// A Svelte action that portals an element to `<body>`.
//
// Why this exists: a `position: fixed` popover resolves against the nearest
// *transformed* ancestor, not the viewport. Inside the view designer a picker
// lives in a Svelte Flow node whose pane carries a CSS transform, which becomes
// the containing block for fixed descendants — trapping the popover in
// canvas-space (it renders offset/clipped and pans with the canvas). Moving the
// node to `<body>` escapes that. The popovers that use this already compute
// viewport coordinates from their trigger's `getBoundingClientRect()`, so the
// only fix needed is the DOM reparent. (#225 — was duplicated in NodePicker,
// TagPicker, SwatchPicker, ColoredSelect; now one copy.)
//
// The element must position itself absolutely/fixed at viewport coords, and any
// outside-click handler must locate it by reference or class (it no longer lives
// under the trigger's anchor). Svelte tracks DOM by reference, so reparenting is
// safe; `destroy` runs on `{#if}`-close or component unmount.
/** Marks a portaled node as the app's own UI, though it sits outside `#app`
 *  (read by inlineEdit.ts's `isAppTarget`). */
export const APP_PORTAL_ATTR = "data-app-portal";

export function portalToBody(node: HTMLElement) {
  node.setAttribute(APP_PORTAL_ATTR, "");
  document.body.appendChild(node);
  return { destroy: () => node.remove() };
}
