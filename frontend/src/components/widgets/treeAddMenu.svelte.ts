// Add-child popover open-state for ViewNodeList (#112 step 4c-iv). Per-instance —
// each list owns its own, so opening one pane's add-menu no longer closes another
// pane's (the shared `treeActions.addMenuOpenFor` singleton made Draft/Research
// mutually exclusive, a latent bug). Threaded through the recursion like TreeDrag
// so a per-container "+" in any row can toggle it.
//
// This is pure open/anchor state: `key` (open identity), `parentId` (create
// target), `anchor` (the trigger; the wrapper hands it to `anchoredPopover`,
// which owns positioning: body-portal, right-aligned, flips above by measured
// height, re-pins on scroll/resize — #1839 retired the last hand-rolled copy
// of that maths). The wrapper renders the popover SHELL from this and defers
// its CONTENT (headings + type choices) to a consumer snippet.

export class TreeAddMenu {
  key = $state<string | null>(null);
  parentId = $state<string | null>(null);
  anchor = $state<HTMLElement | null>(null);

  isOpen(key: string): boolean {
    return this.key === key;
  }

  // Toggle the menu for `key` (create target `parentId`), tracking the clicked
  // anchor element so the wrapper can position the popover against it.
  toggle(parentId: string | null, key: string, event?: MouseEvent): void {
    if (this.key === key) {
      this.close();
      return;
    }
    this.key = key;
    this.parentId = parentId;
    this.anchor = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null;
  }

  close(): void {
    this.key = null;
    this.parentId = null;
    this.anchor = null;
  }
}
