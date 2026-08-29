// Stick-to-bottom geometry for the chat transcript (#1611). Pure so it is
// unit-testable — happy-dom has no layout, so the DOM wiring is verified live.
export const NEAR_BOTTOM_PX = 48;

/** True when the viewport is within `threshold` px of the bottom (or content
 *  is shorter than the viewport). Drives whether new content auto-scrolls. */
export function isNearBottom(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  threshold: number = NEAR_BOTTOM_PX,
): boolean {
  return scrollHeight - scrollTop - clientHeight <= threshold;
}
