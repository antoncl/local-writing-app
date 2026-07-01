<script lang="ts">
  import type { SearchHit } from "@/lib/types";
  import { api } from "@/lib/api";

  // App's error-catching async wrapper (same one Tree uses). Returns whether
  // the action completed without throwing.
  export let run: (action: () => Promise<void>) => Promise<boolean>;
  // Open a hit in an editor pane — App owns the pane set + the embedded-TODO
  // highlight that follows a scene hit.
  export let onOpenHit: (hit: SearchHit) => void;

  // All search state is local to this feature — nothing else in the app reads it.
  let query = "";
  let includeOpenTodos = false;
  let hits: SearchHit[] = [];

  async function runSearch() {
    if (!query.trim() && !includeOpenTodos) return;
    await run(async () => {
      hits = (await api.search(query.trim(), includeOpenTodos)).hits;
    });
  }
</script>

<div class="todo-entry">
  <input bind:value={query} placeholder="Find in scenes and lore" on:keydown={(event) => event.key === "Enter" && runSearch()} />
  <button on:click={runSearch}>Find</button>
</div>
<label class="inline-check">
  <input type="checkbox" bind:checked={includeOpenTodos} />
  Include open TODOs
</label>
{#each hits as hit}
  <button class="search-hit" on:click={() => onOpenHit(hit)}>
    <strong>{hit.path}:{hit.line}</strong>
    <span>{hit.excerpt}</span>
  </button>
{/each}

<style>
  .inline-check {
    display: flex;
    grid-template-columns: none;
    align-items: center;
    gap: 7px;
    margin-top: 8px;
    color: var(--text-2);
  }

  .inline-check input {
    width: auto;
  }

  .search-hit {
    display: grid;
    gap: 4px;
    width: 100%;
    text-align: left;
    margin: 8px 0;
    background: var(--surface);
  }

  .search-hit span {
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
