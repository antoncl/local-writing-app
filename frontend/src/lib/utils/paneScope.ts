// Pane-scoping for editor-pane `svelte:window` keydown handlers.
//
// The workspace keeps every tab MOUNTED — "only the active one is shown"
// (`.hidden-doc { display: none }`) — so every open pane's `svelte:window`
// handler fires on every keypress. Without scoping, one press drives every
// pane's strip at once, and a hidden pane swallows plain letters wherever focus
// is not an input. Two rules, in order: an element inside a hidden tab is never
// addressed, and when focus sits inside another editor pane that pane owns the
// key.
//
// One copy, not N: extracted from `SnapshotStrip` and `EntryRevisionReview`,
// which each carried it verbatim, when the ADR-0088 foot dock became the single
// owner of the dock's keyboard (one traversal, not six).

/** Whether a keypress belongs to the editor pane containing `rootEl`. `rootEl`
 *  is the handler's own root element (the foot dock, the review overlay); the
 *  pane is its nearest `.editor-panel` ancestor. Returns false for a
 *  not-yet-mounted root and for a root inside a hidden tab. */
export function paneOwnsKey(rootEl: HTMLElement | null, target: HTMLElement | null): boolean {
  if (!rootEl) return false;
  if (rootEl.closest(".hidden-doc")) return false;
  const pane = rootEl.closest(".editor-panel");
  const focused = target?.closest?.(".editor-panel") ?? null;
  return !focused || !pane || focused === pane;
}
