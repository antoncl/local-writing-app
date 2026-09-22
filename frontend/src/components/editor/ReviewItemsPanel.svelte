<script lang="ts">
  // The "Review items" computed collection field tab (ADR-0090 Amendment 2
  // §1) — the open review items whose dependent is THIS entry. Modelled on
  // ConversationsPanel.svelte: a RailSectionHeader (count + collapse key),
  // then a NodeList of NodeRows over the filtered todos — a review item is a
  // todo, not a kind, so this reduces to the existing widgets rather than
  // growing a bespoke list (CLAUDE.md's "app reduces to NodeRow/NodeEditor").
  //
  // Never writes anything itself: opening a row routes through the same
  // `todoActions.openFileTodo` the Todo pane uses (opens the source parked on
  // its baseline, then this dependent, per ADR-0090 §3/Amendment 2 §2).
  import { get } from "svelte/store";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import RailSectionHeader from "@/components/editor/RailSectionHeader.svelte";
  import { todosStore } from "@/lib/stores/todos";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import { todoActions } from "@/lib/stores/todoActions.svelte";
  import { railSectionCollapse } from "@/lib/stores/railSectionCollapse.svelte";
  import { reviewItemSourceDetail } from "@/lib/utils/reviewItemDetail";
  import type { TodoItem } from "@/lib/types";

  let { nodeId, nodeTitle }: { nodeId: string; nodeTitle: string } = $props();

  let items = $derived(
    $todosStore.filter((item) => item.scope === "node" && item.node_id === nodeId && item.status === "open"),
  );

  // The source's title, off the cheapest lookup already loaded (lore is the
  // only kind ADR-0090 sources from) — falls back to the bare id when the
  // source entry isn't in the roster (deleted, or a project the roster
  // hasn't loaded yet).
  function sourceTitleFor(sourceId: string): string {
    return get(loreEntriesStore).find((entry) => entry.id === sourceId)?.title ?? sourceId;
  }

  function detailFor(item: TodoItem): string | null {
    return item.source ? reviewItemSourceDetail(item.source, sourceTitleFor(item.source.node_id)) : null;
  }

  const COLLAPSE_KEY = "reviewItems";
  const COLLAPSE_DEFAULT = true;
  const expanded = $derived(railSectionCollapse.isExpanded(COLLAPSE_KEY, COLLAPSE_DEFAULT));
</script>

<section class="review-items" aria-label={`Review items for ${nodeTitle}`}>
  <RailSectionHeader
    title="Review items"
    glyph="ti-list-check"
    count={items.length}
    {expanded}
    onToggle={() => railSectionCollapse.toggle(COLLAPSE_KEY, COLLAPSE_DEFAULT)}
  />
  {#if expanded}
    <div class="review-items-list">
      <NodeList isEmpty={items.length === 0}>
        {#snippet whenEmpty()}
          <p class="muted">No open review items.</p>
        {/snippet}
        {#each items as item (item.id)}
          <NodeRow
            title={item.text}
            detail={detailFor(item)}
            onClick={() => void todoActions.openFileTodo(item)}
          />
        {/each}
      </NodeList>
    </div>
  {/if}
</section>

<style>
  .review-items {
    padding-top: 8px;
  }

  /* Tier panel behind the rows — matches ConversationsPanel/BacklinksPanel's
     grouped-children tint so this reads as one grouped surface. */
  .review-items-list {
    padding: 8px;
    background: var(--tier1);
    border-radius: 10px;
  }

  .muted {
    margin: 0;
    padding: 2px 4px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
