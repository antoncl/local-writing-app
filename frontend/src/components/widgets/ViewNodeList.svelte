<script module lang="ts">
  import type { EvalNode } from "@/lib/views/evaluateView";

  // The context handed to a consumer's `row` snippet for one REAL node (leaf OR
  // real-node parent — tree-uniformity, [[feedback-tree-uniformity-over-header-dichotomy]]).
  // Everything ViewNodeList owns and the consumer can't compute from the node
  // alone: the nesting `depth`, the annotation-derived stripe, and the collapse
  // triad for a real-node parent. `active` is resolved from the `active?(node)`
  // prop; the intent + escape-hatch handlers are pre-bound to this row's node —
  // phase-1 consumers mostly wire clicks in-snippet and ignore them, and #112
  // (Draft) exercises `onDblClick`/`onRename`/`onReorder`. Their signatures are
  // settled here so the contract does NOT widen when Draft plugs in.
  export type RowCtx<T extends EvalNode> = {
    depth: number;
    // Annotation color for this node as a resolved hex (a view Highlight), or
    // null. A consumer with its own precedence (Lore: view → instance → type)
    // may ignore this and compute its own.
    stripeColor: string | null;
    active: boolean;
    // A real-node PARENT (has children) is collapsible; a leaf is not. The row
    // snippet renders a caret via `toggle`/`collapsed` when `collapsible`, and can
    // show `childCount` (distinct leaf members in the subtree, 0 for a leaf) — the
    // count GroupTree drew on parent headers, now expressible on a real-node row.
    collapsible: boolean;
    collapsed: boolean;
    childCount: number;
    toggle: () => void;
    onClick: () => void;
    onDblClick: () => void;
    onRename?: (nextTitle: string) => void;
    onReorder?: (target: T, position: "before" | "after" | "into") => void;
    // Drag-reorder, present only when the list is reorderable (an `onReorder`
    // prop is wired). The wrapper owns the gesture; the snippet reflects
    // `dragging`/`dropPosition` on its NodeRow and spreads `reorder`'s handlers —
    // `onDragStart`/`onDragEnd` onto the drag handle, `onDragOver`/`onDrop` onto
    // the row. The before/after/into zones + settled intent are the wrapper's.
    dragging: boolean;
    dropPosition: "before" | "after" | "into" | null;
    reorder?: {
      onDragStart: (event: DragEvent) => void;
      onDragEnd: (event: DragEvent) => void;
      onDragOver: (event: DragEvent) => void;
      onDrop: (event: DragEvent) => void;
    };
  };

  // The context handed to a `groupHeader` override snippet for one SYNTHETIC
  // label bucket (`nodeId: null`). Only synthetic buckets are ViewNodeList chrome;
  // a consumer overrides their header rendering here while ViewNodeList keeps
  // ownership of the children and collapse.
  export type GroupCtx = {
    label: string | null;
    color: string | null;
    count: number;
    collapsed: boolean;
    toggle: () => void;
    depth: number;
  };
</script>

<script lang="ts" generics="T extends EvalNode">
  // ViewNodeList — the canonical list-render wrapper for a view's output (#182,
  // ADR-0035). It COMPOSES NodeList (view-blind naive chrome) and owns all
  // `ViewResult → row` logic: flat-vs-grouped, synthetic-bucket chrome, search
  // pruning, and ephemeral per-group collapse. Absorbs the old ViewGroupedList +
  // GroupTree glue and the per-pane viewGroups/displayGroups/collapsedGroups
  // boilerplate the #182 census found duplicated across Lore/Assistants/preview.
  //
  // Input contract (ADR-0035): the SOLE input is one `ViewResult<T>`. Non-view
  // sites lift their arrays via `nodeSet()` (lib/views/viewResult). There is no
  // `ViewResult | T[]` union and no `Array.isArray` branch here.
  import type { Snippet } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import ViewNodeTree from "@/components/widgets/ViewNodeTree.svelte";
  import { TreeDrag } from "@/components/widgets/treeDrag.svelte";
  import { filterGroups, type ViewGroup, type ViewResult } from "@/lib/views/evaluateView";
  import { leafGroup } from "@/lib/views/viewResult";

  let {
    result,
    row,
    groupHeader,
    mode = "card",
    searchPlaceholder = null,
    searchValue = $bindable(""),
    searchDebounceMs = 0,
    filter,
    active,
    onClick,
    onDblClick,
    onRename,
    onReorder,
    isContainer,
    collapsed = $bindable(new SvelteSet<string>()),
    defaultCollapsed,
    whenEmpty,
  }: {
    // The one and only input — a view's output (ADR-0035).
    result: ViewResult<T>;
    // Renders one REAL node (leaf or real-node parent). The main extension point.
    row: Snippet<[T, RowCtx<T>]>;
    // Optional override for SYNTHETIC label buckets; default is groupHeader chrome
    // (caret + count pill + tier panel). Real nodes never route here.
    groupHeader?: Snippet<[GroupCtx]>;
    mode?: "card" | "tree";
    // When set, NodeList renders a SearchInput; pair with `filter` to prune.
    searchPlaceholder?: string | null;
    searchValue?: string;
    searchDebounceMs?: number;
    // Membership predicate for the search box. `query` is pre-normalized (trimmed
    // + lowercased). ViewNodeList prunes `nodes` to matches, then prunes `groups`
    // via `filterGroups` (drops emptied branches). Absent ⇒ no search pruning.
    filter?: (node: T, query: string) => boolean;
    // Resolves a node's active (focused) state → RowCtx.active.
    active?: (node: T) => boolean;
    // Intent surface. Escape hatches (present phase 1, exercised by #112 Draft).
    onClick?: (node: T) => void;
    onDblClick?: (node: T) => void;
    onRename?: (node: T, nextTitle: string) => void;
    onReorder?: (moved: T, target: T, position: "before" | "after" | "into") => void;
    // Domain classification for drag: does this node accept an "into" drop (i.e.
    // it's a container, even an empty one)? The wrapper owns the drop-zone
    // mechanics; the consumer names what can contain. Absent ⇒ falls back to
    // "has children", so an empty container won't accept drops without this.
    isContainer?: (node: T) => boolean;
    // Per-group collapse keyed by stable `ViewGroup.key`. $bindable so #112 can
    // back it with persisted state; unbound ⇒ ephemeral internal set (phase 1).
    collapsed?: SvelteSet<string>;
    defaultCollapsed?: readonly string[];
    // Empty state; the caller differentiates "no items" vs "no matches".
    whenEmpty?: Snippet;
  } = $props();

  // Seed the initial collapsed set once from `defaultCollapsed`. Guarded so the
  // effect never re-seeds (and it reads neither `collapsed` nor the seed after,
  // so mutating the set can't retrigger it).
  let seeded = false;
  $effect(() => {
    if (seeded || !defaultCollapsed) return;
    seeded = true;
    for (const key of defaultCollapsed) collapsed.add(key);
  });

  const query = $derived(searchValue.trim().toLowerCase());
  // The kept id-set under the active search, or null when no pruning applies
  // (no filter, or an empty query) — distinct from an empty set (nothing matches).
  const keptIds = $derived.by(() => {
    if (!filter || !query) return null;
    const ids = new Set<string>();
    for (const node of result.nodes) if (filter(node, query)) ids.add(node.id);
    return ids;
  });

  const displayedNodes = $derived(keptIds ? result.nodes.filter((n) => keptIds.has(n.id)) : result.nodes);
  const displayedGroups = $derived(
    result.groups ? (keptIds ? filterGroups(result.groups, keptIds) : result.groups) : null,
  );

  // One render path: flat membership lifts to childless leaf groups, so grouped
  // and flat both flow through ViewNodeTree (which renders every real node via
  // `row` and every synthetic bucket as chrome).
  const effectiveGroups = $derived<ViewGroup<T>[]>(displayedGroups ?? displayedNodes.map((n) => leafGroup(n)));

  const isEmpty = $derived(effectiveGroups.length === 0);

  // One drag-gesture holder for the whole tree, threaded through the recursion
  // (inert unless `onReorder` is wired). See treeDrag.svelte.ts.
  const drag = new TreeDrag<T>();
</script>

<NodeList {mode} {searchPlaceholder} bind:searchValue {searchDebounceMs} {isEmpty} {whenEmpty}>
  <ViewNodeTree
    groups={effectiveGroups}
    depth={0}
    {collapsed}
    annotations={result.annotations}
    {active}
    {onClick}
    {onDblClick}
    {onRename}
    {onReorder}
    {isContainer}
    {drag}
    {row}
    {groupHeader}
  />
</NodeList>
