// ADR-0090 §4: the Propose hand-off — a node-id-keyed record of which review
// item a chat's next commit should mark done. Mirrors `entryBrainstorm.svelte.ts`'s
// shape: there is at most one pending proposal per node (a second Propose on the
// same node supersedes the first), and the chat itself carries no provenance —
// stamping one onto the chat would be schema work, which ADR-0090 §4 explicitly
// wants none of (no new prompt vocabulary, no new field). Keyed by the
// DEPENDENT's node id (the chat's subject), not the chat id, so `entryProposal`'s
// commit — which already knows its own node id — can look the hand-off up
// without threading the chat id through the review controller.

class ReviewProposals {
  // node id -> the review item awaiting a mark-done once that node's next
  // commit adopts a patch.
  #pending = $state<Record<string, string>>({});

  /** Propose: record that `nodeId`'s next adopted commit should mark
   *  `reviewItemId` done. */
  set(nodeId: string, reviewItemId: string): void {
    this.#pending = { ...this.#pending, [nodeId]: reviewItemId };
  }

  /** Read without clearing — for a caller that only wants to know whether one
   *  is pending. */
  peek(nodeId: string): string | null {
    return this.#pending[nodeId] ?? null;
  }

  /** Consume: return the pending review item id for `nodeId` (or null) and
   *  clear it. A commit that adopts calls this once, on its single success
   *  path; a discard calls it too, to clear the hand-off without marking
   *  anything done. */
  take(nodeId: string): string | null {
    const id = this.#pending[nodeId] ?? null;
    if (id === null) return null;
    const next = { ...this.#pending };
    delete next[nodeId];
    this.#pending = next;
    return id;
  }
}

export const reviewProposals = new ReviewProposals();
