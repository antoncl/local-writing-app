// Search pane domain state (ADR-0085 §3, slice 2: as-you-type). One instance
// per pane — NOT a module singleton, because two open Search panes must not
// share query state (`feedback_mode_is_presentation_not_functionality`).
//
// The debounce itself lives in the input widget (`SearchInput`'s
// `debounceMs`); this controller owns the query/option state, the hit list,
// and the stale-response guard — a monotonic token, the same pattern
// `ChatBodyView.fetchChatEstimate` uses, so a fast second keystroke's
// response can never land after a slower first keystroke's and show stale
// hits.

import { api } from "@/lib/api";
import type { SearchHit } from "@/lib/types";

export class SearchPaneController {
  query = $state("");
  matchCase = $state(false);
  wholeWord = $state(false);
  includeOpenTodos = $state(false);
  hits = $state<SearchHit[]>([]);
  // The query `hits` were found with — drives excerpt highlighting and the
  // "no matches" line, independent of what has since been typed.
  lastQuery = $state("");
  searched = $state(false);

  #token = 0;

  constructor(private readonly run: (action: () => Promise<void>) => Promise<boolean>) {}

  setQuery(value: string): void {
    this.query = value;
    void this.fire();
  }

  setMatchCase(on: boolean): void {
    this.matchCase = on;
    void this.fire();
  }

  setWholeWord(on: boolean): void {
    this.wholeWord = on;
    void this.fire();
  }

  setIncludeOpenTodos(on: boolean): void {
    this.includeOpenTodos = on;
    void this.fire();
  }

  async fire(): Promise<void> {
    const ours = ++this.#token;
    const q = this.query.trim();
    if (!q && !this.includeOpenTodos) {
      this.hits = [];
      this.lastQuery = "";
      this.searched = false;
      return;
    }
    await this.run(async () => {
      const res = await api.search({
        query: q,
        match_case: this.matchCase,
        whole_word: this.wholeWord,
        kinds: null,
        include_open_todos: this.includeOpenTodos,
      });
      // ADR-0085 §3: a fast second keystroke's response must never show the
      // first keystroke's (now superseded) hits.
      if (ours !== this.#token) return;
      this.hits = res.hits;
      this.lastQuery = q;
      this.searched = true;
    });
  }
}
