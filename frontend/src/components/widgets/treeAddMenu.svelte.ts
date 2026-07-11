// Add-child popover open-state for ViewNodeList (#112 step 4c-iv). Per-instance —
// each list owns its own, so opening one pane's add-menu no longer closes another
// pane's (the shared `treeActions.addMenuOpenFor` singleton made Draft/Research
// mutually exclusive, a latent bug). Threaded through the recursion like TreeDrag
// so a per-container "+" in any row can toggle it.
//
// This is pure open/position state: `key` is the open identity (a node id for a
// per-container button, or a caller-chosen root key), `parentId` is the create
// target (null = add at root), `pos` are fixed-position coords. The wrapper renders
// the popover SHELL from this and defers its CONTENT (headings + type choices) to a
// consumer snippet.

export type AddMenuPosition = { top: number; right: number };

// Popover flips above the anchor when there isn't this much room below it.
const POPOVER_HEIGHT = 180;

export class TreeAddMenu {
  key = $state<string | null>(null);
  parentId = $state<string | null>(null);
  pos = $state<AddMenuPosition | null>(null);

  isOpen(key: string): boolean {
    return this.key === key;
  }

  // Toggle the menu for `key` (create target `parentId`), positioning it off the
  // clicked anchor's right edge — dropping below, or flipping above near the
  // viewport bottom (mirrors the old treeActions.toggleAddMenu geometry).
  toggle(parentId: string | null, key: string, event?: MouseEvent): void {
    if (this.key === key) {
      this.close();
      return;
    }
    this.key = key;
    this.parentId = parentId;
    const anchor = event?.currentTarget;
    if (anchor instanceof HTMLElement) {
      const rect = anchor.getBoundingClientRect();
      const fitsBelow = window.innerHeight - rect.bottom > POPOVER_HEIGHT;
      this.pos = {
        top: fitsBelow ? rect.bottom + 4 : rect.top - POPOVER_HEIGHT - 4,
        right: window.innerWidth - rect.right,
      };
    } else {
      this.pos = null;
    }
  }

  close(): void {
    this.key = null;
    this.parentId = null;
    this.pos = null;
  }
}
