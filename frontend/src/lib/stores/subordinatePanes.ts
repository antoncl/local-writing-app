// Subordinate-pane lifecycle registry: a child pane that only makes sense while
// its master pane is open (the lore Brainstorm chat, the "Edit type…" schema_type
// pane) closes automatically when the master closes. Kind-neutral — each child
// registers its own closer, so this registry stays ignorant of whether the child
// is an editor document or a region pane. Not reactive state: it drives a
// side-effect on teardown, nothing renders from it, so a plain module singleton
// (no runes) is correct.

interface SubordinateLink {
  parentId: string;
  close: () => void;
}

class SubordinatePanes {
  // childPaneId -> { parentId, close }. A child has at most one parent; a fresh
  // register() re-homes it (the schema_type singleton, opened from a new editor).
  #links = new Map<string, SubordinateLink>();

  register(childId: string, parentId: string, close: () => void): void {
    this.#links.set(childId, { parentId, close });
  }

  unregister(childId: string): void {
    this.#links.delete(childId);
  }

  // Close every pane subordinate to `parentId`. Unregister before closing so a
  // closer that re-enters teardown (an editor child) can't recurse onto a stale
  // link, and so a child's own manual-close path finds nothing left to do.
  closeChildrenOf(parentId: string): void {
    for (const [childId, link] of [...this.#links]) {
      if (link.parentId !== parentId) continue;
      this.#links.delete(childId);
      link.close();
    }
  }
}

export const subordinatePanes = new SubordinatePanes();
