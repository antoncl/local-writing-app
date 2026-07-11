<script lang="ts" generics="T extends EvalNode">
  // Recursive renderer for a `ViewResult`'s tree-uniform groups (#182, ADR-0035),
  // the absorbed GroupTree + ViewGroupedList logic. Two cases per group:
  //   - REAL node (`nodeId` set) — leaf OR real-node parent (Draft acts/chapters,
  //     Nest parents) — renders via the consumer's `row` snippet. A parent also
  //     recurses its children below (indented by depth), and its RowCtx carries
  //     the collapse triad so the row can host a caret. This is tree-uniformity
  //     ([[feedback-tree-uniformity-over-header-dichotomy]]): every real node is a
  //     real NodeRow, never demoted to a "header".
  //   - SYNTHETIC bucket (`nodeId: null`, a named handle) — ViewNodeList chrome: a
  //     groupHeader NodeRow (caret + count pill) whose children recurse inside its
  //     tier-panel `nested` slot, or a consumer `groupHeader` override.
  //
  // Recursion is a COMPONENT boundary (this component renders itself), not a
  // recursive snippet, so collapse state propagates through every level (see
  // feedback_svelte5_reactivity_traps; the same reason GroupTree was a component).
  import type { Snippet } from "svelte";
  import type { SvelteSet } from "svelte/reactivity";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeTree from "@/components/widgets/ViewNodeTree.svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import type { EvalNode, ViewAnnotation, ViewGroup } from "@/lib/views/evaluateView";
  import type { GroupCtx, RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import type { DropPosition, TreeDrag } from "@/components/widgets/treeDrag.svelte";
  import type { TreeRename } from "@/components/widgets/treeRename.svelte";
  import type { TreeAddMenu } from "@/components/widgets/treeAddMenu.svelte";
  import type { CollapseGuard } from "@/components/widgets/treeCollapseGuard";

  let {
    groups,
    depth = 0,
    collapsed,
    annotations,
    active,
    onClick,
    onDblClick,
    onRename,
    onReorder,
    isContainer,
    drag,
    rename,
    add,
    collapseGuard,
    row,
    groupHeader,
  }: {
    groups: ViewGroup<T>[];
    depth?: number;
    collapsed: SvelteSet<string>;
    annotations: Map<string, ViewAnnotation>;
    active?: (node: T) => boolean;
    onClick?: (node: T) => void;
    onDblClick?: (node: T) => void;
    onRename?: (node: T, nextTitle: string) => void;
    onReorder?: (moved: T, target: T, position: "before" | "after" | "into") => void;
    isContainer?: (node: T) => boolean;
    drag: TreeDrag<T>;
    rename: TreeRename<T>;
    add: TreeAddMenu;
    collapseGuard: CollapseGuard;
    row: Snippet<[T, RowCtx<T>]>;
    groupHeader?: Snippet<[GroupCtx]>;
  } = $props();

  function toggle(key: string): void {
    if (collapsed.has(key)) collapsed.delete(key);
    else collapsed.add(key);
  }

  function annHex(id: string): string | null {
    return getSwatch(annotations.get(id)?.color)?.hex ?? null;
  }

  function rowCtx(group: ViewGroup<T>, node: T): RowCtx<T> {
    const key = group.key;
    return {
      depth,
      stripeColor: annHex(node.id),
      active: active?.(node) ?? false,
      collapsible: group.children.length > 0,
      collapsed: collapsed.has(key),
      childCount: subtreeCount(group),
      toggle: () => toggle(key),
      toggleCollapse: () => collapseGuard.defer(() => toggle(key)),
      onClick: () => onClick?.(node),
      onDblClick: () => {
        collapseGuard.cancel();
        onDblClick?.(node);
      },
      onRename: onRename ? (nextTitle: string) => onRename(node, nextTitle) : undefined,
      onReorder: onReorder ? (target: T, position: DropPosition) => onReorder(node, target, position) : undefined,
      dragging: drag.dragged?.id === node.id,
      dropPosition: drag.overId === node.id ? drag.position : null,
      reorder: onReorder ? reorderHandlers(group, node) : undefined,
      editing: rename.editingId === node.id,
      editValue: rename.editValue,
      onEditInput: (value: string) => rename.onInput(value),
      beginRename: () => rename.begin(node.id, node.title),
      commitRename: () => rename.commit(),
      cancelRename: () => rename.cancel(),
      addMenuOpen: add.key === node.id,
      toggleAddMenu: (event: MouseEvent) => add.toggle(node.id, node.id, event),
    };
  }

  // Drag-gesture handlers for one row (wrapper-owned; see treeDrag.svelte.ts).
  // dragstart/end mark the dragged node; dragover computes the before/after/into
  // zone by cursor ratio (into only over a container); drop settles the intent
  // and fires `onReorder(moved, target, position)`.
  function reorderHandlers(group: ViewGroup<T>, node: T) {
    const container = isContainer ? isContainer(node) : group.children.length > 0;
    return {
      onDragStart: (event: DragEvent) => {
        drag.dragged = node;
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", node.id);
        }
      },
      onDragEnd: () => drag.reset(),
      onDragOver: (event: DragEvent) => {
        const moved = drag.dragged;
        if (!moved || moved.id === node.id) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        const el = event.currentTarget;
        if (!(el instanceof HTMLElement)) return;
        const rect = el.getBoundingClientRect();
        const ratio = (event.clientY - rect.top) / rect.height;
        let position: DropPosition;
        if (container && ratio > 0.2 && ratio < 0.8) position = "into";
        else if (ratio < 0.5) position = "before";
        else position = "after";
        if (drag.overId !== node.id || drag.position !== position) {
          drag.overId = node.id;
          drag.position = position;
        }
      },
      onDrop: (event: DragEvent) => {
        event.preventDefault();
        const moved = drag.dragged;
        const position = drag.position;
        drag.reset();
        if (moved && position && moved.id !== node.id) onReorder?.(moved, node, position);
      },
    };
  }

  // Distinct leaf members in a synthetic bucket's subtree — the count pill total.
  // A container node isn't counted (it's a header); a node reachable via two
  // branches counts once.
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
  {@const isCollapsed = collapsed.has(group.key)}
  {#if group.nodeId !== null && group.node}
    <!-- Real node — leaf or real-node parent — always via the consumer's row. -->
    {@render row(group.node, rowCtx(group, group.node))}
    {#if group.children.length > 0 && !isCollapsed}
      <ViewNodeTree
        groups={group.children}
        depth={depth + 1}
        {collapsed}
        {annotations}
        {active}
        {onClick}
        {onDblClick}
        {onRename}
        {onReorder}
        {isContainer}
        {drag}
        {rename}
        {add}
        {collapseGuard}
        {row}
        {groupHeader}
      />
    {/if}
  {:else if groupHeader}
    <!-- Synthetic bucket, consumer-overridden header; ViewNodeList keeps children. -->
    {@render groupHeader({
      label: group.label,
      color: group.color,
      count: subtreeCount(group),
      collapsed: isCollapsed,
      toggle: () => toggle(group.key),
      depth,
    })}
    {#if !isCollapsed}
      <ViewNodeTree
        groups={group.children}
        depth={depth + 1}
        {collapsed}
        {annotations}
        {active}
        {onClick}
        {onDblClick}
        {onRename}
        {onReorder}
        {isContainer}
        {drag}
        {rename}
        {add}
        {collapseGuard}
        {row}
        {groupHeader}
      />
    {/if}
  {:else}
    <!-- Synthetic bucket, default groupHeader chrome. -->
    <NodeRow
      groupHeader
      collapsed={isCollapsed}
      title={group.label ?? "Everything else"}
      {depth}
      stripeColor={group.color ? getSwatch(group.color)?.hex ?? null : null}
      onClick={() => toggle(group.key)}
      onmousedown={(event) => event.stopPropagation()}
    >
      {#snippet leading()}
        <GroupCaret collapsed={isCollapsed} />
      {/snippet}
      {#snippet trailing()}
        <CountPill count={subtreeCount(group)} />
      {/snippet}
      {#snippet nested()}
        {#if !isCollapsed}
          <ViewNodeTree
            groups={group.children}
            depth={depth + 1}
            {collapsed}
            {annotations}
            {active}
            {onClick}
            {onDblClick}
            {onRename}
            {onReorder}
            {isContainer}
            {drag}
            {rename}
            {add}
            {collapseGuard}
            {row}
            {groupHeader}
          />
        {/if}
      {/snippet}
    </NodeRow>
  {/if}
{/each}
