<script module lang="ts">
  import type { EvalNode } from "@/lib/views/evaluateView";

  // A pane's intrinsic (non-view) render bucket. `label: null` is the headerless
  // flat list; a set label renders a collapsible header (count pill + optional
  // color stripe). `depth` indents the header (default 0). `reorderKey` is an
  // opaque grouping key a pane sets on buckets whose rows support within-group
  // drag (null / absent = not reorderable); it is handed back to the `row`
  // snippet so the pane can gate its own drag wiring without this widget knowing
  // anything about reordering. Both the Lore and Assistants panes render through
  // this so the flat-vs-header / empty-bucket / collapse logic lives once (#97).
  export type DisplayGroup<T> = {
    id: string;
    label: string | null;
    color: string | null;
    depth?: number;
    reorderKey?: string | null;
    entries: T[];
  };
</script>

<script lang="ts" generics="T extends EvalNode">
  import type { Snippet } from "svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import GroupTree from "@/components/widgets/GroupTree.svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import type { ViewGroup } from "@/lib/views/evaluateView";

  let {
    viewGroups,
    displayGroups,
    collapsed,
    onToggle,
    row,
  }: {
    // A view's own hard groups (rendered read-only through the recursive
    // GroupTree), or null to fall back to the pane's intrinsic buckets.
    viewGroups: ViewGroup<T>[] | null;
    displayGroups: DisplayGroup<T>[];
    // Per-group collapse, keyed by ViewGroup.key / DisplayGroup.id. Pane-owned so
    // one shared map re-renders every level.
    collapsed: Record<string, boolean>;
    onToggle: (key: string) => void;
    // Renders one member row at the given depth. `group` is the intrinsic bucket
    // it sits in, or null when it's a view (GroupTree) leaf — a pane reads
    // `group?.reorderKey` off it to decide whether to wire drag.
    row: Snippet<[T, number, DisplayGroup<T> | null]>;
  } = $props();
</script>

{#if viewGroups}
  <GroupTree groups={viewGroups} {collapsed} {onToggle} leaf={viewLeaf} />
{:else}
  {#each displayGroups as group (group.id)}
    {#if group.label === null}
      {#each group.entries as entry (entry.id)}
        {@render row(entry, 0, group)}
      {/each}
    {:else}
      {@const depth = group.depth ?? 0}
      {@const isCollapsed = !!collapsed[group.id] || group.entries.length === 0}
      <NodeRow
        groupHeader
        collapsed={isCollapsed}
        title={group.label}
        {depth}
        stripeColor={group.color ? getSwatch(group.color)?.hex ?? null : null}
        onClick={() => onToggle(group.id)}
        onmousedown={(event) => event.stopPropagation()}
      >
        {#snippet leading()}
          <GroupCaret collapsed={isCollapsed} />
        {/snippet}
        {#snippet trailing()}
          <CountPill count={group.entries.length} />
        {/snippet}
        {#snippet nested()}
          {#if !isCollapsed}
            {#each group.entries as entry (entry.id)}
              {@render row(entry, depth + 1, group)}
            {/each}
          {/if}
        {/snippet}
      </NodeRow>
    {/if}
  {/each}
{/if}

{#snippet viewLeaf(entry: T, depth: number)}
  {@render row(entry, depth, null)}
{/snippet}
