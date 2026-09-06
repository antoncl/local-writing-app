<script lang="ts">
  import { untrack } from "svelte";
  import type { SearchHit } from "@/lib/types";
  import { kindLabel, orderKinds } from "@/lib/kindLabels";
  import { SearchPaneController } from "@/lib/stores/searchPane.svelte";
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

  // Domain state (query, options, hits, in-flight token) lives in the
  // controller, not this component (ADR-0085 §3) — one instance per pane.
  // `run` is read once at construction (App passes a stable wrapper); `untrack`
  // silences the state_referenced_locally warning that comes with reading a
  // prop outside a reactive context.
  const ctrl = new SearchPaneController(untrack(() => run));

  // Hits are heterogeneous — every kind the node index lists, plus the
  // synthetic "project" bucket for a TODO with no scene (ADR-0085 §2). `kind`
  // buckets them; the label table is data-driven (`kindLabels.ts`) rather than
  // a fixed three-entry constant, so an unrendered kind still shows up under
  // its title-cased kind name instead of being dropped. `project` always
  // sorts last — it is the TODO catch-all, not a content kind.
  const PANE_LABEL: Record<string, string> = { manuscript: "Scenes", project: "Project" };
  const groups = $derived(
    orderKinds(new Set(ctrl.hits.map((hit) => hit.kind)))
      .sort((a, b) => (a === "project" ? 1 : 0) - (b === "project" ? 1 : 0))
      .map((kind) => ({
        label: PANE_LABEL[kind] ?? kindLabel(kind),
        hits: ctrl.hits.filter((hit) => hit.kind === kind),
      })),
  );

  // Split an excerpt around case-insensitive matches of `q` so the match can be
  // wrapped in <mark>. Only the excerpt is highlighted — never the path/line.
  function segments(text: string, q: string): { text: string; hit: boolean }[] {
    if (!q) return [{ text, hit: false }];
    const out: { text: string; hit: boolean }[] = [];
    const lower = text.toLowerCase();
    const needle = q.toLowerCase();
    let from = 0;
    for (;;) {
      const at = lower.indexOf(needle, from);
      if (at < 0) {
        if (from < text.length) out.push({ text: text.slice(from), hit: false });
        break;
      }
      if (at > from) out.push({ text: text.slice(from, at), hit: false });
      out.push({ text: text.slice(at, at + q.length), hit: true });
      from = at + q.length;
    }
    return out;
  }

  // Search fires on input, debounced by `SearchInput` (`/api/search` reads
  // the corpus now — ADR-0085 §3, no longer an un-indexed full scan); the
  // controller drops any response superseded by a later keystroke. Enter
  // fires immediately, bypassing the debounce.
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

{#if groups.length > 0}
  {#each groups as group (group.label)}
    <div class="search-group-label">{group.label}</div>
    <!-- Unkeyed: hits are ephemeral and fully replaced each search, and are
         NOT unique on (file_id, line, path) — an entry matching in two metadata
         fields (title + aliases) yields two hits identical on those, so a keyed
         each collides (each_key_duplicate) and drops the group. -->
    <NodeList>
      {#each group.hits as hit}
        <NodeRow title={`${hit.path}:${hit.line}`} onClick={() => onOpenHit(hit)}>
          {#snippet detailSlot()}
            <small class="search-excerpt"
              >{#each segments(hit.excerpt, ctrl.lastQuery) as seg}{#if seg.hit}<mark>{seg.text}</mark>{:else}{seg.text}{/if}{/each}</small
            >
          {/snippet}
        </NodeRow>
      {/each}
    </NodeList>
  {/each}
{:else if ctrl.searched}
  <p class="search-empty">No matches.</p>
{/if}

<style>
  .search-bar {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
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

  .search-empty {
    margin-top: var(--sp-4);
    color: var(--text-3);
  }
</style>
