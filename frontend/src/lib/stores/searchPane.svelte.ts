// Search pane domain state (ADR-0085 §3 as-you-type, §4/§5 replace — slice 3).
// One instance per pane — NOT a module singleton, because two open Search
// panes must not share query state
// (`feedback_mode_is_presentation_not_functionality`).
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
//
// Replace (§4/§5): `deps` is the pane's one seam onto `editorPanes` and the
// app-level confirm modal — kept as three narrow functions (not the whole
// `editorPanes` store) so this controller stays unit-testable without
// mounting the shell. A hit's eligibility is computed here (todo/metadata/
// inherited/dirty), never trusted from a prior render — the backend's own
// `not_replaceable`/`stale` outcomes are the real backstop.

import { api } from "@/lib/api";
import type { ReplaceHitRef, SearchHit } from "@/lib/types";

// The pane's one seam onto the editor-pane store and the confirm modal.
export type SearchPaneDeps = {
  isDirtyOpen: (nodeId: string, kind: string, entryType?: string) => boolean;
  reconcile: (nodeId: string, kind: string, entryType?: string) => Promise<void>;
  confirm: (n: number, nodes: number, query: string) => Promise<boolean>;
};

// A hit's replace eligibility (§4/§5). `todo` and `metadata`/`inherited`/`dirty`
// are all reasons a hit can't be sent; `ok` is the only one Replace/Replace all
// act on. Undispatched kinds (assistant/view/tag/chat — no save primitive) come
// back from the server as `not_replaceable/kind` and are counted as skipped,
// same as a stale hit — the pane never guesses a kind's dispatch itself.
export type ReplaceEligibility = "ok" | "inherited" | "metadata" | "dirty" | "todo";

export type LastReplace = { replaced: number; stale: number; skipped: number; nodes: number };

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
  replacement = $state("");
  replacing = $state(false);
  lastReplace = $state<LastReplace | null>(null);

  #token = 0;

  constructor(
    private readonly run: (action: () => Promise<void>) => Promise<boolean>,
    private readonly deps: SearchPaneDeps,
  ) {}

  // A hit's replace eligibility (§4/§5's client-side half of the table — the
  // server has the real ownership/revision/dispatch checks). Order matters:
  // a TODO hit has no body range at all, so it's checked before field/owned.
  eligibility(hit: SearchHit): ReplaceEligibility {
    if (hit.todo_id) return "todo";
    if (hit.field !== "body") return "metadata";
    if (!hit.owned) return "inherited";
    if (this.deps.isDirtyOpen(hit.file_id, hit.kind, hit.entry_type)) return "dirty";
    return "ok";
  }

  eligibleHits = $derived(this.hits.filter((hit) => this.eligibility(hit) === "ok"));

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
      this.lastReplace = null;
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

  // ADR-0085 §4: one write per hit's node, through that node's own save — the
  // endpoint is the whole mechanism; this is "one or many hits" sent together.
  // Reconciles every node the server actually wrote to (never a stale one),
  // then re-runs the search so the list reflects what remains.
  async replace(hits: SearchHit[]): Promise<void> {
    if (hits.length === 0) return;
    this.replacing = true;
    try {
      const refs: ReplaceHitRef[] = hits.map((hit) => ({
        file_id: hit.file_id,
        field: hit.field,
        start: hit.start,
        end: hit.end,
        text: hit.text,
        revision: hit.revision,
      }));
      await this.run(async () => {
        const res = await api.replace({ replacement: this.replacement, hits: refs });
        // Reconcile every distinct node the server actually wrote to — the
        // outcome carries no kind/entry_type, so it's read off the hit that
        // named the node (any hit on it carries the same kind/entry_type).
        const replacedIds = new Set(
          res.outcomes.filter((outcome) => outcome.status === "replaced").map((outcome) => outcome.file_id),
        );
        const reconciled = new Set<string>();
        for (const hit of hits) {
          if (!replacedIds.has(hit.file_id) || reconciled.has(hit.file_id)) continue;
          reconciled.add(hit.file_id);
          await this.deps.reconcile(hit.file_id, hit.kind, hit.entry_type);
        }
        let replaced = 0;
        let stale = 0;
        let skipped = 0;
        for (const outcome of res.outcomes) {
          if (outcome.status === "replaced") replaced += 1;
          else if (outcome.status === "stale") stale += 1;
          else skipped += 1;
        }
        this.lastReplace = { replaced, stale, skipped, nodes: res.replaced_nodes };
        await this.fire();
      });
    } finally {
      this.replacing = false;
    }
  }

  replaceOne(hit: SearchHit): Promise<void> {
    return this.replace([hit]);
  }

  async replaceAll(): Promise<void> {
    const hits = this.eligibleHits;
    if (hits.length > 1) {
      const nodes = new Set(hits.map((hit) => hit.file_id)).size;
      if (!(await this.deps.confirm(hits.length, nodes, this.lastQuery))) return;
    }
    await this.replace(hits);
  }
}
