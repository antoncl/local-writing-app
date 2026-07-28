// Cross-pane hand-off for the lore brainstorm (ADR-0046 slice 2/3).
//
// The commit fires in the *chat* pane (ChatBodyView): a `revise:entry` brainstorm
// finalises and the server validates the model's reply into an `EntryPatch` —
// the entry's revised body plus proposed field values. But the review — the
// proposed-vs-current flip — renders on the *entry* pane, per the decided UX
// ("launch from the entry, review on the entry"). Those are two different editor
// panes, so this singleton rune controller bridges them: the chat pane
// `propose(entryId, patch)`s, the entry pane reads `proposalFor(entryId)` and
// clears once the author saves or discards.
//
// The value grew from a bare body string (slice 2) to an `EntryPatch` (slice 3)
// so the same hand-off carries long_text + structured field proposals, not just
// the body. A plain keyed map, not a queue: one pending proposal per entry is
// the whole model — a second commit for the same entry supersedes the first (the
// author re-finalised before reviewing). Mirrors the other lib/stores/*.svelte.ts
// singletons (editorPanes / chatSessions).

import type { EntryPatch } from "@/lib/types";

class LoreBrainstorm {
  // entryId -> proposed patch awaiting review on that entry's pane.
  #proposals = $state<Record<string, EntryPatch>>({});

  /** Chat pane: publish a committed patch for `entryId` to review. */
  propose(entryId: string, patch: EntryPatch): void {
    this.#proposals = { ...this.#proposals, [entryId]: patch };
  }

  /** Entry pane: the pending patch for `entryId`, or null if none. */
  proposalFor(entryId: string): EntryPatch | null {
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
