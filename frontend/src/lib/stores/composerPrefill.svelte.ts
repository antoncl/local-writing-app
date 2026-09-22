// ADR-0090 §4: a review item's Propose message, held for the chat it belongs
// to until that chat's composer can show it — keyed by CHAT ID, at module
// level, because the chat pane is created by the very gesture that fills it
// and its body is remounted (and its composer cleared by `applyChatSession`)
// more than once while the session settles. Browser-verified: a per-instance
// hold applied the text and the next load wiped it. So the text stays here,
// every load of that chat re-applies it, and it is cleared only when the
// writer edits or sends — never by a load.

class ComposerPrefills {
  #pending = $state<Record<string, string>>({});

  /** Propose: the text `chatId`'s composer should show until the writer edits it. */
  set(chatId: string, text: string): void {
    this.#pending = { ...this.#pending, [chatId]: text };
  }

  /** The pending text for `chatId`, or null. Reading does not clear it. */
  peek(chatId: string): string | null {
    return this.#pending[chatId] ?? null;
  }

  /** The writer took over (edited or sent): the hold is done. */
  clear(chatId: string): void {
    if (!(chatId in this.#pending)) return;
    const next = { ...this.#pending };
    delete next[chatId];
    this.#pending = next;
  }
}

export const composerPrefills = new ComposerPrefills();
