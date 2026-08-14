// The keyboard-reach focus guard (ADR-0053 §7; extracted for testing, #909).
//
// Plot cards are `selectable:false`, so a drag or click lands focus on <body>, never
// inside `.plot-board`, and the board's bubbling Ctrl+Z never fires. PlotEditor makes
// the section programmatically focusable (`tabindex="-1"`) and focuses it on a board
// pointerdown / drag release — but it must NOT steal focus when the pointer landed on
// an editable or interactive control, or an inline title / synopsis / plotline input
// would lose focus mid-type (and native Ctrl+Z would leave that input).
//
// This is that skip-list, as a pure predicate: `true` when the target keeps its own
// focus (so the board must not grab it). The component wiring is browser-only; this
// makes the load-bearing selector unit-testable, so a regression that starts stealing
// input focus is caught by a gate rather than only by Anton at the keyboard.
export function keepsOwnFocus(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.closest("input, textarea, select, button, a, [contenteditable='true']") !== null
  );
}
