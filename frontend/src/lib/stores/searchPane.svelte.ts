// Search pane domain state (ADR-0085 §3, slice 2: as-you-type). One instance
// per pane — NOT a module singleton, because two open Search panes must not
// share query state (`feedback_mode_is_presentation_not_functionality`).
//
// The debounce itself lives in the input widget (`SearchInput`'s
// `debounceMs`); this controller owns the query/option state, the hit list,
// and the stale-response guard — a monotonic token, so a fast second
// keystroke's response can never land after a slower first keystroke's and
// show stale hits. This is NOT the same as `ChatBodyView.fetchChatEstimate`,
// which swallows every failure: here, a *current* request's failure still
// surfaces through `run` — a search that silently returned nothing would
// read as "no matches", so only a *superseded* request's failure is nobody's
// business (the writer has typed past it).

import { api } from "@/lib/api";
import type { SearchHit } from "@/lib/types";

export class SearchPaneController {
  query = $state("");
  matchCase = $state(false);
  wholeWord = $state(false);
  includeOpenTodos = $state(false);
  hits = $state<SearchHit[]>([]);
  // The query/options `hits` were found with — drives excerpt highlighting and
  // the "no matches" line, independent of what has since been typed/toggled.
  lastQuery = $state("");
  lastMatchCase = $state(false);
  lastWholeWord = $state(false);
  searched = $state(false);

  #token = 0;

  constructor(private readonly run: (action: () => Promise<void>) => Promise<boolean>) {}

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
      this.lastMatchCase = false;
      this.lastWholeWord = false;
      this.searched = false;
      return;
    }
    await this.run(async () => {
      let res;
      try {
        res = await api.search({
          query: q,
          match_case: this.matchCase,
          whole_word: this.wholeWord,
          kinds: null,
          include_open_todos: this.includeOpenTodos,
        });
      } catch (error) {
        // A superseded request's failure is nobody's business — the writer
        // has typed past it. A *current* request's failure still surfaces
        // through `run` (rethrown below).
        if (ours !== this.#token) return;
        throw error;
      }
      // ADR-0085 §3: a fast second keystroke's response must never show the
      // first keystroke's (now superseded) hits.
      if (ours !== this.#token) return;
      this.hits = res.hits;
      this.lastQuery = q;
      this.lastMatchCase = this.matchCase;
      this.lastWholeWord = this.wholeWord;
      this.searched = true;
    });
  }
}
