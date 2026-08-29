<script lang="ts">
  import type { SearchHit } from "@/lib/types";
  import { api } from "@/lib/api";
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

  // All search state is local to this feature — nothing else in the app reads it.
  let query = $state("");
  let includeOpenTodos = $state(false);
  let hits: SearchHit[] = $state([]);
  // The query the current `hits` were found with — drives excerpt highlighting
  // and the "no matches" line. Find-only: search never fires on keystroke,
  // because `/api/search` is an un-indexed full scan (an index is the
  // prerequisite for as-you-type / replace — GH #1605).
  let lastQuery = $state("");
  let searched = $state(false);

  // Hits are heterogeneous (scene content/metadata/TODOs, lore, project TODOs);
  // `kind` buckets them. Synthetic buckets are tool labels → sans headers.
  const KIND_ORDER: SearchHit["kind"][] = ["manuscript", "lore", "project"];
  const KIND_LABEL: Record<SearchHit["kind"], string> = {
    manuscript: "Scenes",
    lore: "Lore",
    project: "Project",
  };
  const groups = $derived(
    KIND_ORDER.map((kind) => ({
      label: KIND_LABEL[kind],
      hits: hits.filter((hit) => hit.kind === kind),
    })).filter((group) => group.hits.length > 0),
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

  async function runSearch() {
    const q = query.trim();
    if (!q && !includeOpenTodos) return;
    await run(async () => {
      hits = (await api.search(q, includeOpenTodos)).hits;
      lastQuery = q;
      searched = true;
    });
  }
</script>

<div class="search-bar">
  <SearchInput bind:value={query} placeholder="Find in scenes and lore" onEnter={runSearch} />
  <button class="search-find" type="button" onclick={runSearch}>Find</button>
</div>
<label class="inline-check">
  <input type="checkbox" bind:checked={includeOpenTodos} />
  Include open TODOs
</label>

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
              >{#each segments(hit.excerpt, lastQuery) as seg}{#if seg.hit}<mark>{seg.text}</mark>{:else}{seg.text}{/if}{/each}</small
            >
          {/snippet}
        </NodeRow>
      {/each}
    </NodeList>
  {/each}
{:else if searched}
  <p class="search-empty">No matches.</p>
{/if}

<style>
  .search-bar {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }

  .search-find {
    flex: none;
    padding: 7px 16px;
    border: 1px solid var(--accent);
    border-radius: var(--r-md);
    background: var(--accent);
    color: var(--surface);
    font-family: inherit;
    font-size: var(--fs-md);
    font-weight: var(--w-semibold);
    cursor: pointer;
  }

  .search-find:hover {
    background: var(--accent-strong);
    border-color: var(--accent-strong);
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
