<script lang="ts" generics="T extends EvalNode">
  // Recursive renderer for a view's tree-uniform groups (#101, #181). Every
  // group is a real node or a synthetic handle bucket: a childless real-node
  // group is a leaf, rendered via the caller-supplied `leaf` snippet; any group
  // with children is a collapsible NodeRow header whose `children` recurse
  // through this same component (a component boundary — not a recursive snippet —
  // so collapse state propagates; see feedback_svelte5_reactivity_traps). Leaves
  // and sub-containers share one ordered `children` list, so they interleave in
  // document order. Lore and Assistants share it, each passing its own leaf row.
  import type { Snippet } from "svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import { type EvalNode, type ViewGroup } from "@/lib/views/evaluateView";
  import GroupTree from "@/components/widgets/GroupTree.svelte";

  let {
    groups,
    depth = 0,
    collapsed,
    onToggle,
    leaf,
  }: {
    groups: ViewGroup<T>[];
    depth?: number;
    // Per-group collapse state, keyed by ViewGroup.key. Owned by the pane so
    // toggling one shared map re-renders every level.
    collapsed: Record<string, boolean>;
    onToggle: (key: string) => void;
    // Renders one member leaf at the given depth (the pane's own row).
    leaf: Snippet<[T, number]>;
  } = $props();

  // Distinct leaf members in a group's whole subtree — the count pill total. A
  // leaf is a childless real-node group; a node reachable via two branches
  // counts once (same entry). Container nodes aren't counted (they're headers).
  function subtreeCount(group: ViewGroup<T>): number {
    const ids = new Set<string>();
    const walk = (g: ViewGroup<T>): void => {
      if (g.children.length === 0) {
        if (g.nodeId) ids.add(g.nodeId);
        return;
      }
      for (const c of g.children) walk(c);
    };
    walk(group);
    return ids.size;
  }
</script>

{#each groups as group (group.key)}
  {#if group.children.length === 0 && group.node}
    <!-- A childless real-node group is a leaf: render the caller's row. -->
    {@render leaf(group.node, depth)}
  {:else}
    <NodeRow
      groupHeader
      collapsed={!!collapsed[group.key]}
      title={group.label ?? "Everything else"}
      {depth}
      stripeColor={group.color ? getSwatch(group.color)?.hex ?? null : null}
      onClick={() => onToggle(group.key)}
      onmousedown={(event) => event.stopPropagation()}
    >
      {#snippet leading()}
        <GroupCaret collapsed={!!collapsed[group.key]} />
      {/snippet}
      {#snippet trailing()}
        <CountPill count={subtreeCount(group)} />
      {/snippet}
      {#snippet nested()}
        {#if !collapsed[group.key]}
          <GroupTree groups={group.children} depth={depth + 1} {collapsed} {onToggle} {leaf} />
        {/if}
      {/snippet}
    </NodeRow>
  {/if}
{/each}
