<script lang="ts">
  // NodeList — canonical container for a list of NodeRows. See
  // [[decisions-ui-widget-taxonomy]] and the 2026-06-22 design session.
  //
  // Intentionally thin. Owns only:
  //   1. An optional SearchInput rendered at the top (bind:searchValue,
  //      passes through to consumer for matching/filtering).
  //   2. The default slot — caller composes NodeRows however. Grouping
  //      happens via NodeRow recursion: a group header IS a NodeRow,
  //      its `children` slot may embed another NodeList for the
  //      grouped entries.
  //   3. The empty-state slot. Caller declares `isEmpty` (NodeList
  //      can't introspect arbitrary slot content); NodeList renders
  //      the `whenEmpty` snippet if provided, otherwise a default
  //      muted "No entries." line.
  //
  // What NodeList does NOT own (intentionally):
  //   - Drag / drop state — lives in the consumer pane.
  //   - "+ Entry" affordances — stay in the pane header.
  //   - Cross-row keyboard navigation — punted; revisit if a pattern
  //     emerges across panes.
  //   - Item iteration / filtering — caller controls both.
  //   - Per-list `id` / `scope` — `dragScope` lives on NodeRows where
  //     it's needed for hit-testing.

  import { setContext } from "svelte";
  import type { Snippet } from "svelte";
  import SearchInput from "./SearchInput.svelte";

  // Card mode → NodeRows in this list render with full card chrome
  //   (border + radius + padding + hover/active fills). The default.
  // Tree mode → NodeRows in this list render bare (no card chrome,
  //   hover-only highlight). Use for dense outline / schema trees.
  // A NodeRow with `groupHeader=true` always renders bare regardless
  // of mode — header rows are typographic dividers, not interactive
  // cards. NodeRow reads this mode via context so consumers don't
  // have to plumb a per-row `variant` prop.
  export let mode: "card" | "tree" = "card";
  setContext("nodeListMode", { get current() { return mode; } });

  // When set, NodeList renders a SearchInput at the top. The caller
  // is responsible for using the bound `searchValue` to filter the
  // children it passes into the default slot.
  export let searchPlaceholder: string | null = null;
  export let searchValue: string = "";
  // Pass-through to SearchInput. 0 (sync) is the default for both —
  // exposed here so consumers can opt into debounced search without
  // breaking the abstraction.
  export let searchDebounceMs: number = 0;

  // Caller-declared. NodeList renders the `whenEmpty` snippet (or its
  // default message) when this is true. Differentiating "no items"
  // vs "no matches" is the caller's job — they can swap the snippet's
  // content based on whether a search is active.
  export let isEmpty: boolean = false;

  // The list contents. Caller iterates NodeRows directly.
  export let children: Snippet | undefined = undefined;
  // Custom empty state. Falls back to a muted "No entries." line.
  export let whenEmpty: Snippet | undefined = undefined;
</script>

<div class="node-list">
  {#if searchPlaceholder !== null}
    <div class="node-list-search">
      <SearchInput
        bind:value={searchValue}
        placeholder={searchPlaceholder}
        debounceMs={searchDebounceMs}
      />
    </div>
  {/if}

  {#if isEmpty}
    <div class="node-list-empty">
      {#if whenEmpty}
        {@render whenEmpty()}
      {:else}
        <p class="muted">No entries.</p>
      {/if}
    </div>
  {:else if children}
    {@render children()}
  {/if}
</div>

<style>
  /* Provisional visual chrome — Claude Design pass will revisit
     spacing, padding, and how the search bar sits relative to the
     first row. Keep selectors minimal so the consumer pane controls
     enclosing layout. */
  .node-list {
    display: grid;
    gap: 6px;
    width: 100%;
  }

  .node-list-search {
    margin-bottom: 2px;
  }

  .node-list-empty {
    padding: 4px 0;
  }
</style>
