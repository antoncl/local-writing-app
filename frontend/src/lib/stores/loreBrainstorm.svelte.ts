// Cross-pane hand-off for the lore brainstorm (ADR-0046 slice 2).
//
// The commit fires in the *chat* pane (ChatBodyView): a `revise:entry` brainstorm
// finalises and the assistant returns the entry's full revised body. But the
// review — the proposed-vs-current flip — renders on the *entry* pane, per the
// decided UX ("launch from the entry, review on the entry"). Those are two
// different editor panes, so this singleton rune controller bridges them: the
// chat pane `propose(entryId, body)`s, the entry pane reads `proposalFor(entryId)`
// and clears once the author saves or discards.
//
// A plain keyed map, not a queue: one pending proposal per entry is the whole
// model — a second commit for the same entry supersedes the first (the author
// re-finalised before reviewing). Mirrors the other lib/stores/*.svelte.ts
// singletons (editorPanes / chatSessions).

class LoreBrainstorm {
  // entryId -> proposed markdown body awaiting review on that entry's pane.
  #proposals = $state<Record<string, string>>({});

  /** Chat pane: publish a committed body for `entryId` to review. */
  propose(entryId: string, proposedBody: string): void {
    this.#proposals = { ...this.#proposals, [entryId]: proposedBody };
  }

  /** Entry pane: the pending proposal for `entryId`, or null if none. */
  proposalFor(entryId: string): string | null {
    return this.#proposals[entryId] ?? null;
  }

  /** Entry pane: drop the proposal once saved or discarded. */
  clear(entryId: string): void {
    if (!(entryId in this.#proposals)) return;
    const next = { ...this.#proposals };
    delete next[entryId];
    this.#proposals = next;
  }
}

export const loreBrainstorm = new LoreBrainstorm();
