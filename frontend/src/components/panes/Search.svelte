<script lang="ts">
  import { untrack } from "svelte";
  import type { SearchHit } from "@/lib/types";
  import { kindLabel, orderKinds } from "@/lib/kindLabels";
  import { SearchPaneController } from "@/lib/stores/searchPane.svelte";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import SearchInput from "@/components/widgets/SearchInput.svelte";

  let {
    // App's error-catching async wrapper (same one Tree uses). Returns whether
    // the action completed without throwing.
    run,
    // Open a hit in an editor pane — App owns the pane set + the embedded-TODO
    // highlight that follows a scene hit.
    onOpenHit,
  }: {
    run: (action: () => Promise<void>) => Promise<boolean>;
    onOpenHit: (hit: SearchHit) => void;
  } = $props();

  // Domain state (query, options, hits, replace, in-flight token) lives in the
  // controller, not this component (ADR-0085 §3/§4/§5) — one instance per
  // pane. `run` is read once at construction (App passes a stable wrapper);
  // `untrack` silences the state_referenced_locally warning that comes with
  // reading a prop outside a reactive context. `deps` is the pane's one seam
  // onto `editorPanes` (dirty check + the generic reconcile entry point, §5)
  // and the app-level confirm modal (Replace all's "are you sure").
  const ctrl = new SearchPaneController(untrack(() => run), {
    isDirtyOpen: (id, kind, entryType) => editorPanes.isNodeOpenDirty(id, kind, entryType),
    reconcile: (id, kind, entryType) => editorPanes.reconcileNodeFromServer(id, kind, entryType),
    confirm: (n, nodes, query) =>
      new Promise<boolean>((resolve) => {
        confirmService.request({
          title: "Replace all?",
          message: `Replace ${n} occurrence${n === 1 ? "" : "s"} of "${query}" in ${nodes} node${nodes === 1 ? "" : "s"}.`,
          confirmLabel: "Replace all",
          destructive: false,
          onConfirm: async () => resolve(true),
          onCancel: () => resolve(false),
        });
      }),
  });

  // The Replace-all summary line's parts, in order, omitting whatever is zero
  // (a batch that replaced everything shows no "not replaceable" clause at
  // all) — joined with the same "·" separator the pane uses elsewhere.
  // `rejected` (a save that refused the new content) shows the first
  // outcome's `detail` when the server sent one.
  function replaceSummary(counts: {
    replaced: number;
    stale: number;
    skipped: number;
    rejected: number;
    detail: string | null;
    nodes: number;
  }): string {
    const parts: string[] = [];
    if (counts.replaced > 0) {
      parts.push(`Replaced ${counts.replaced} in ${counts.nodes} node${counts.nodes === 1 ? "" : "s"}`);
    }
    if (counts.stale > 0) parts.push(`${counts.stale} changed since the search`);
    if (counts.skipped > 0) parts.push(`${counts.skipped} not replaceable`);
    if (counts.rejected > 0) {
      parts.push(counts.detail ? `${counts.rejected} rejected: ${counts.detail}` : `${counts.rejected} rejected`);
    }
    return parts.join(" · ");
  }

  // Hits are heterogeneous — every kind the node index lists, plus the
  // synthetic "project" bucket for a TODO with no scene (ADR-0085 §2). `kind`
  // buckets them; the label table is data-driven (`kindLabels.ts`) rather than
  // a fixed three-entry constant, so an unrendered kind still shows up under
  // its title-cased kind name instead of being dropped. `project` always
  // sorts last — it is the TODO catch-all, not a content kind.
  const PANE_LABEL: Record<string, string> = { manuscript: "Scenes", project: "Project" };
  // Grouped from `visibleHits` (#1868) — the render window, not the full hit
  // list — but each group still carries `total`, the count of that kind across
  // the FULL `ctrl.hits`, so the group label reads correctly before every hit
  // of that kind has been revealed. Order follows the kinds present in the
  // VISIBLE slice, same orderKinds + project-last logic as before.
  const groups = $derived(
    orderKinds(new Set(ctrl.visibleHits.map((hit) => hit.kind)))
      .sort((a, b) => (a === "project" ? 1 : 0) - (b === "project" ? 1 : 0))
      .map((kind) => ({
        label: PANE_LABEL[kind] ?? kindLabel(kind),
        hits: ctrl.visibleHits.filter((hit) => hit.kind === kind),
        total: ctrl.hits.filter((hit) => hit.kind === kind).length,
      })),
  );

  // The reveal-more sentinel — an IntersectionObserver target below the last
  // group, only rendered while more hits remain (#1868).
  let moreSentinel = $state<HTMLElement | null>(null);

  // Split an excerpt around matches of `q` so the match can be wrapped in
  // <mark>. Only the excerpt is highlighted — never the path/line. The regex
  // is built the same way the backend builds its search pattern (`_compile_query`
  // in `search.py`): the mark must show exactly what the backend matched
  // (ADR-0085 §3 options) — a case-insensitive substring mark under Match case
  // highlights the very occurrences the toggle excluded.
  function segments(
    text: string,
    q: string,
    matchCase: boolean,
    wholeWord: boolean,
  ): { text: string; hit: boolean }[] {
    if (!q) return [{ text, hit: false }];
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const source = wholeWord ? `(?<!\\w)${escaped}(?!\\w)` : escaped;
    const re = new RegExp(source, matchCase ? "g" : "gi");
    const out: { text: string; hit: boolean }[] = [];
    let from = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(text))) {
      const at = match.index;
      const matched = match[0];
      if (matched.length === 0) {
        re.lastIndex += 1;
        continue;
      }
      if (at > from) out.push({ text: text.slice(from, at), hit: false });
      out.push({ text: matched, hit: true });
      from = at + matched.length;
    }
    if (from < text.length) out.push({ text: text.slice(from), hit: false });
    return out;
  }

  // Reveal the next batch when the sentinel scrolls into view. Reading
  // `ctrl.visibleCount` makes the effect re-run after every reveal, so the
  // observer is re-created and its initial callback fires again — if the
  // sentinel is STILL on screen (a tall pane), the next batch follows without
  // a scroll, until the sentinel is below the fold or everything is shown.
  // IntersectionObserver respects ancestor clipping, so the pane needn't know
  // which container scrolls it. Where the API is missing (tests), the Show
  // more button is the whole mechanism.
  $effect(() => {
    const el = moreSentinel;
    void ctrl.visibleCount;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) ctrl.revealMore();
    });
    observer.observe(el);
    return () => observer.disconnect();
  });

  // Search fires on input, debounced by `SearchInput` (`/api/search` reads
  // the corpus now — ADR-0085 §3, no longer an un-indexed full scan); the
  // controller drops any response superseded by a later keystroke. Enter
  // fires immediately, bypassing the debounce.
  //
  // Replace (ADR-0085 §4/§5, slice 3): the replace field feeds a per-hit
  // preview (each matched segment shown struck through + the replacement,
  // instead of the plain `<mark>`) and both Replace (one hit) and Replace all
  // (every currently eligible hit). Ineligibility — inherited, metadata,
  // TODO, or unsaved edits in an open pane — is computed client-side for the
  // note text; the actual write is always the backend's ownership/revision/
  // dispatch check (§4), never guessed here.
  //
  // Reveal window (#1868): rendering every hit as a NodeRow froze the tab on
  // a short/common query (thousands of hits) — the pane now renders only the
  // first `REVEAL_BATCH` hits and reveals more as the sentinel scrolls into
  // view (or via "Show more" where IntersectionObserver is unavailable). The
  // controller's `hits`/`eligibleHits` stay complete throughout — Replace all
  // still acts on every eligible hit, not just the visible ones.
</script>

<div class="search-bar">
  <SearchInput
    bind:value={ctrl.query}
    placeholder="Find in the project"
    debounceMs={150}
    onChange={() => ctrl.fire()}
    onEnter={() => ctrl.fire()}
  />
</div>
<div class="search-replace-row">
  <input
    class="search-replace"
    type="text"
    placeholder="Replace with"
    bind:value={ctrl.replacement}
    aria-label="Replace with"
  />
  <button
    type="button"
    class="search-replace-all"
    disabled={ctrl.eligibleHits.length === 0 || ctrl.replacing}
    onclick={() => ctrl.replaceAll()}
  >
    Replace all ({ctrl.eligibleHits.length})
  </button>
</div>
<div class="search-options">
  <label class="inline-check">
    <input
      type="checkbox"
      checked={ctrl.matchCase}
      onchange={(e) => ctrl.setMatchCase((e.currentTarget as HTMLInputElement).checked)}
    />
    Match case
  </label>
  <label class="inline-check">
    <input
      type="checkbox"
      checked={ctrl.wholeWord}
      onchange={(e) => ctrl.setWholeWord((e.currentTarget as HTMLInputElement).checked)}
    />
    Whole word
  </label>
  <label class="inline-check">
    <input
      type="checkbox"
      checked={ctrl.includeOpenTodos}
      onchange={(e) => ctrl.setIncludeOpenTodos((e.currentTarget as HTMLInputElement).checked)}
    />
    Include open TODOs
  </label>
</div>

{#if ctrl.lastReplace}
  <p class="search-replace-summary">{replaceSummary(ctrl.lastReplace)}</p>
{/if}

{#if groups.length > 0}
  <p class="search-count">{ctrl.hits.length} {ctrl.hits.length === 1 ? "match" : "matches"}</p>
  {#each groups as group (group.label)}
    <div class="search-group-label">{group.label} <span class="search-group-count">{group.total}</span></div>
    <!-- Unkeyed: hits are ephemeral and fully replaced each search, and are
         NOT unique on (file_id, line, path) — an entry matching in two metadata
         fields (title + aliases) yields two hits identical on those, so a keyed
         each collides (each_key_duplicate) and drops the group. -->
    <NodeList>
      {#each group.hits as hit}
        {@const elig = ctrl.eligibility(hit)}
        {@const previewReplace = ctrl.replacement !== "" && elig === "ok"}
        <NodeRow title={`${hit.path}:${hit.line}`} onClick={() => onOpenHit(hit)}>
          {#snippet detailSlot()}
            <small class="search-excerpt"
              >{#each segments(hit.excerpt, ctrl.lastQuery, ctrl.lastMatchCase, ctrl.lastWholeWord) as seg}{#if seg.hit}{#if previewReplace}<del
                    class="search-del">{seg.text}</del
                  ><ins class="search-ins">{ctrl.replacement}</ins>{:else}<mark>{seg.text}</mark>{/if}{:else}{seg.text}{/if}{/each}</small
            >
            {#if elig === "inherited"}
              <span class="search-hit-note">inherited — not replaceable here</span>
            {:else if elig === "metadata"}
              <span class="search-hit-note">metadata — not replaceable</span>
            {:else if elig === "dirty"}
              <span class="search-hit-note">unsaved edits in the editor — save first</span>
            {/if}
          {/snippet}
          {#snippet trailing()}
            {#if elig === "ok"}
              <button
                type="button"
                class="search-hit-replace"
                disabled={ctrl.replacing}
                onclick={(event) => {
                  event.stopPropagation();
                  ctrl.replaceOne(hit);
                }}
              >
                Replace
              </button>
            {/if}
          {/snippet}
        </NodeRow>
      {/each}
    </NodeList>
  {/each}
  {#if ctrl.visibleHits.length < ctrl.hits.length}
    <div class="search-more" bind:this={moreSentinel}>
      <span class="search-more-count">Showing {ctrl.visibleHits.length} of {ctrl.hits.length}</span>
      <button type="button" class="search-show-more" onclick={() => ctrl.revealMore()}>Show more</button>
    </div>
  {/if}
{:else if ctrl.searched}
  <p class="search-empty">No matches.</p>
{/if}

<style>
  .search-bar {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }

  .search-replace-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
  }

  .search-replace {
    flex: 1;
  }

  .search-replace-all {
    flex: 0 0 auto;
    padding: 6px 12px;
    font-size: var(--fs-sm);
    font-weight: var(--w-semibold);
    border-radius: var(--r-md);
    border: 1px solid var(--accent);
    background: var(--accent);
    color: #fff;
    cursor: pointer;
    white-space: nowrap;
  }

  .search-replace-all:hover:not(:disabled) {
    background: var(--accent-strong);
    border-color: var(--accent-strong);
  }

  .search-replace-all:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .search-replace-summary {
    margin-top: var(--sp-2);
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  .search-options {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-3);
  }

  .inline-check {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: var(--sp-2);
    color: var(--text-2);
  }

  .inline-check input {
    width: auto;
  }

  .search-group-label {
    margin: var(--sp-4) 0 var(--sp-2);
    color: var(--text-3);
    font-size: var(--fs-sm);
    font-weight: var(--w-bold);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .search-group-count {
    color: var(--text-3);
    font-weight: var(--w-regular);
    letter-spacing: 0;
    text-transform: none;
    margin-left: var(--sp-1);
  }

  .search-count {
    margin-top: var(--sp-3);
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  .search-more {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: var(--sp-3);
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  .search-show-more {
    padding: 3px 10px;
    font-size: var(--fs-xs);
    font-weight: var(--w-semibold);
    border-radius: var(--r-sm);
    border: 1px solid var(--accent);
    background: var(--surface);
    color: var(--accent-emphasis);
    cursor: pointer;
  }

  .search-show-more:hover:not(:disabled) {
    background: var(--accent-soft);
  }

  .search-show-more:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .search-excerpt {
    color: var(--text-2);
    line-height: 1.35;
  }

  .search-excerpt mark {
    background: var(--accent-soft2);
    color: var(--accent-emphasis);
    padding: 0 2px;
    border-radius: var(--r-sm);
  }

  .search-del {
    text-decoration: line-through;
    color: var(--text-3);
  }

  .search-ins {
    text-decoration: none;
    color: var(--accent-emphasis);
    background: var(--accent-soft2);
    padding: 0 2px;
    border-radius: var(--r-sm);
  }

  .search-hit-replace {
    padding: 3px 10px;
    font-size: var(--fs-xs);
    font-weight: var(--w-semibold);
    border-radius: var(--r-sm);
    border: 1px solid var(--accent);
    background: var(--surface);
    color: var(--accent-emphasis);
    cursor: pointer;
  }

  .search-hit-replace:hover:not(:disabled) {
    background: var(--accent-soft);
  }

  .search-hit-replace:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .search-hit-note {
    display: block;
    margin-top: var(--sp-2);
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-style: italic;
  }

  .search-empty {
    margin-top: var(--sp-4);
    color: var(--text-3);
  }
</style>
