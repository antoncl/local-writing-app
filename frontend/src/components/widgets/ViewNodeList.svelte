<script module lang="ts">
  import type { EvalNode } from "@/lib/views/evaluateView";
  import type { MetadataSchema, ViewSpec } from "@/lib/types";

  // The view-driven input (ADR-0032 §D / ADR-0035). Instead of a pre-resolved
  // `result`, a consumer hands ViewNodeList the view to evaluate + its data
  // environment; the wrapper then owns the parameter strip, the bindings env, and
  // re-evaluation on override change. Exactly one of `view` / `result` is supplied
  // — `result` stays for non-view / already-resolved sites (they lift arrays via
  // `nodeSet()`, ADR-0035).
  export type ViewInput<T extends EvalNode> = {
    spec: ViewSpec;
    universe: readonly T[];
    schema?: MetadataSchema | null;
    referenceIndex?: ReadonlyMap<string, ReadonlySet<string>>;
    // (No roster data here.) The param strip's reference/tag pickers source the
    // full node universe from the global stores directly (see the store imports
    // above) — a pane doesn't thread it, because a param can reference ANY kind,
    // not the pane's own (#257).
  };

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
    // Inline rename (4c-iii). The wrapper owns the edit state; the snippet renders
    // the styled `<input>` when `editing`, feeding `editValue`/`onEditInput` and
    // calling `commitRename` (blur) / `cancelRename`. `beginRename` starts an edit
    // (e.g. a container's rename-on-dblclick).
    editing: boolean;
    editValue: string;
    onEditInput: (value: string) => void;
    beginRename: () => void;
    commitRename: () => void;
    cancelRename: () => void;
    // Deferred collapse toggle (4c-iv-c): schedules `toggle` past the dblclick
    // window so a following double-click (→ onDblClick) can cancel it. Use this
    // for a container's single-click; `onDblClick` cancels any pending toggle.
    toggleCollapse: () => void;
    // Per-container add-child "+" (4c-iv). The snippet renders a `.tree-menu-anchor`
    // button reflecting `addMenuOpen` and calling `toggleAddMenu(event)`; the popover
    // itself is the wrapper's (fed by the `addMenu` snippet, keyed to this node).
    addMenuOpen: boolean;
    toggleAddMenu: (event: MouseEvent) => void;
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
  import { tick } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import ViewNodeTree from "@/components/widgets/ViewNodeTree.svelte";
  import ParamStrip from "@/components/editor/body/view/ParamStrip.svelte";
  import { TreeDrag } from "@/components/widgets/treeDrag.svelte";
  import { TreeRename } from "@/components/widgets/treeRename.svelte";
  import { TreeAddMenu } from "@/components/widgets/treeAddMenu.svelte";
  import { CollapseGuard } from "@/components/widgets/treeCollapseGuard";
  import { evaluateView, filterGroups, type EvalBindings, type ViewGroup, type ViewResult } from "@/lib/views/evaluateView";
  import { leafGroup, nodeSet } from "@/lib/views/viewResult";
  import { buildBindings } from "@/lib/views/viewParams";
  import { repairSpecCycles } from "@/lib/views/cycleCheck";

  let {
    result,
    view,
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
    addMenu,
    collapsed = $bindable(new SvelteSet<string>()),
    defaultCollapsed,
    whenEmpty,
  }: {
    // The rendered input — a view's output (ADR-0035). Supplied directly by non-
    // view / already-resolved sites (which lift arrays via `nodeSet()`); for a
    // view-driven pane, omit this and pass `view` instead — the wrapper evaluates.
    result?: ViewResult<T>;
    // The view-driven input (ADR-0032 §D): the spec + data environment to
    // evaluate internally, so the wrapper owns the parameter strip + re-evaluation.
    // Exactly one of `view` / `result`.
    view?: ViewInput<T>;
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
    // Persist a committed inline rename (4c-iii). The wrapper owns the edit state
    // + guards and calls this only for a real, non-empty change; the consumer
    // does the domain write (optimistic update + rename API).
    onRename?: (node: T, nextTitle: string) => void;
    // Reorder intent (drag OR keyboard). May return a Promise; the keyboard path
    // awaits it before restoring focus to the moved row's new position.
    onReorder?: (moved: T, target: T, position: "before" | "after" | "into") => void | Promise<void>;
    // Domain classification for drag: does this node accept an "into" drop (i.e.
    // it's a container, even an empty one)? The wrapper owns the drop-zone
    // mechanics; the consumer names what can contain. Absent ⇒ falls back to
    // "has children", so an empty container won't accept drops without this.
    isContainer?: (node: T) => boolean;
    // Add-child popover CONTENT (4c-iv). The wrapper owns the open-state, position,
    // dismissal, and the `.row-add-popover` shell; this snippet fills it with the
    // consumer's heading + type choices for the given `parentId` (null = root),
    // calling `close` after a create. Present ⇒ the wrapper renders the popover
    // when a "+" (RowCtx.toggleAddMenu, or the imperative toggleAddMenu) opens it.
    addMenu?: Snippet<[{ parentId: string | null; close: () => void }]>;
    // Per-group collapse keyed by stable `ViewGroup.key`. $bindable so #112 can
    // back it with persisted state; unbound ⇒ ephemeral internal set (phase 1).
    collapsed?: SvelteSet<string>;
    defaultCollapsed?: readonly string[];
    // Empty state; the caller differentiates "no items" vs "no matches".
    whenEmpty?: Snippet;
  } = $props();

  // ── View evaluation + parameter strip (ADR-0032 §D) ──────────────────────
  // When `view` is supplied, the wrapper OWNS evaluation: it holds the ephemeral
  // overrides (edited via the shared `ParamStrip`), folds them into a bindings env,
  // and evaluates the spec against the roster. Centralized here so every
  // parameterized list gets the strip for free — not per pane (ADR-0032 §D rejects
  // per-pane bespoke UI). `result`-driven sites skip all of this and render their
  // pre-resolved result unchanged (ADR-0035).

  // Ephemeral runtime overrides for the view's declared formals (ADR-0032 §C):
  // pane/session state, seeded per-control by the authored default, never baked
  // into the shared view. Bound into `ParamStrip` (the strip UI + its controls);
  // stale keys (from a previously-selected view) are ignored by `buildBindings`.
  let paramOverrides = $state<Record<string, unknown>>({});
  const bindings = $derived.by((): EvalBindings => {
    if (!view) return {};
    return buildBindings(view.spec.params, paramOverrides);
  });
  // The pane's LOAD-time cycle repair (#275): a pane evaluates a STORED spec
  // directly (no designer graph, so `repairGraphCycles` never runs on it). A cyclic
  // `{orphans_of}` spec — only reachable via a hand-edited file / crafted POST,
  // never the designer — would recurse forever in `evalNest`. Repair it here, once
  // per spec (this derived tracks `view.spec`, not the per-keystroke overrides);
  // the acyclic common case returns the same spec object untouched.
  const safeSpec = $derived.by(() => {
    if (!view) return null;
    const { spec, repaired } = repairSpecCycles(view.spec);
    if (repaired > 0 && import.meta.env.DEV) {
      console.warn(`[views] pane load repair: neutralized ${repaired} cyclic orphans_of reference(s)`);
    }
    return spec;
  });
  // The rendered result: evaluated from `view` (re-runs on override/spec change),
  // or the pre-resolved `result`, or an empty set when neither is wired.
  const computedResult = $derived.by((): ViewResult<T> =>
    view && safeSpec
      ? evaluateView(safeSpec, view.universe as T[], {
          schema: view.schema,
          bindings,
          referenceIndex: view.referenceIndex,
        })
      : (result ?? nodeSet<T>([])),
  );

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
    for (const node of computedResult.nodes) if (filter(node, query)) ids.add(node.id);
    return ids;
  });

  const displayedNodes = $derived(keptIds ? computedResult.nodes.filter((n) => keptIds.has(n.id)) : computedResult.nodes);
  const displayedGroups = $derived(
    computedResult.groups ? (keptIds ? filterGroups(computedResult.groups, keptIds) : computedResult.groups) : null,
  );

  // One render path: flat membership lifts to childless leaf groups, so grouped
  // and flat both flow through ViewNodeTree (which renders every real node via
  // `row` and every synthetic bucket as chrome).
  const effectiveGroups = $derived<ViewGroup<T>[]>(displayedGroups ?? displayedNodes.map((n) => leafGroup(n)));

  const isEmpty = $derived(effectiveGroups.length === 0);

  // One drag-gesture holder for the whole tree, threaded through the recursion
  // (inert unless `onReorder` is wired). See treeDrag.svelte.ts.
  const drag = new TreeDrag<T>();

  // One collapse defer-guard for the tree (single-click vs dblclick). See
  // treeCollapseGuard.ts.
  const collapseGuard = new CollapseGuard();

  // Inline-rename controller (4c-iii). Owns edit state; persists via `onRename`.
  // Threaded down like `drag`; also driven imperatively by the consumer (F2 is
  // wrapper-side, but create-then-rename comes from outside a row render).
  const rename = new TreeRename<T>({
    persist: (node, nextTitle) => onRename?.(node, nextTitle),
    resolve: (id) => locate(id)?.node ?? null,
  });

  // Imperative rename entry points for the consumer (see the block comment): begin
  // an inline rename on a just-created node, or cancel one whose row is being
  // deleted. F2 / dblclick renames are driven wrapper-side (keyboard) or via RowCtx.
  export function beginRename(id: string, title: string): void {
    rename.begin(id, title);
  }
  export function cancelRename(id: string): void {
    rename.cancel(id);
  }

  // Per-instance add-child menu (4c-iv). The holder threads down for per-container
  // "+" buttons; these exports drive it from a consumer's header/pane button. A
  // document mousedown outside the anchor/popover closes it (per instance — no
  // shared App-level handler). See treeAddMenu.svelte.ts.
  const add = new TreeAddMenu();
  export function toggleAddMenu(parentId: string | null, key: string, event?: MouseEvent): void {
    add.toggle(parentId, key, event);
  }
  export function closeAddMenu(): void {
    add.close();
  }
  export function isAddMenuOpen(key: string): boolean {
    return add.isOpen(key);
  }
  $effect(() => {
    const onDown = (event: MouseEvent) => {
      if (add.key === null) return;
      const target = event.target;
      if (target instanceof Element && target.closest(".tree-menu-anchor, .row-add-popover")) return;
      add.close();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  });

  // ── Tree keyboard (4c-ii) ────────────────────────────────────────────────
  // The wrapper owns tree keyboard so every tree consumer inherits it. Ctrl+arrows
  // reorder by translating to the SAME `onReorder(moved, target, position)` intent
  // as drag (targets computed from the group tree — the wrapper knows siblings);
  // F2/Enter/Escape relay to the rename hooks. Rides a DIRECT listener (see the
  // `treeKeyboard` action) because Svelte-5 delegated `onkeydown` doesn't reach the
  // consumer's `row` snippet DOM, which is mounted under a foreign delegation root.

  // Locate a real node within the group tree: its sibling list + index + nearest
  // real-node ancestor (the outdent target). Synthetic buckets are transparent —
  // their `node` is null, so `parentNode` skips past them to the enclosing node.
  type Located = { node: T; siblings: ViewGroup<T>[]; index: number; parentNode: T | null };
  function locate(
    id: string,
    groups: ViewGroup<T>[] = effectiveGroups,
    parentNode: T | null = null,
  ): Located | null {
    for (let i = 0; i < groups.length; i++) {
      const g = groups[i];
      if (g.nodeId === id && g.node) return { node: g.node, siblings: groups, index: i, parentNode };
      if (g.children.length) {
        const found = locate(id, g.children, g.node ?? parentNode);
        if (found) return found;
      }
    }
    return null;
  }

  async function reorderTo(moved: T, target: T, position: "before" | "after" | "into"): Promise<void> {
    await onReorder?.(moved, target, position);
    // The moved row is a fresh DOM element after the structure re-renders; keep
    // focus on it so repeated Ctrl+arrows chain without a re-grab.
    await tick();
    const row = document.querySelector<HTMLElement>(`[data-node-id="${moved.id}"]`);
    (row?.querySelector<HTMLElement>("button.node-row-click") ?? row)?.focus();
  }

  function handleReorderKey(event: KeyboardEvent, nodeId: string): void {
    if (!onReorder) return;
    const loc = locate(nodeId);
    if (!loc) return;
    const prev = loc.index > 0 ? loc.siblings[loc.index - 1] : null;
    const next = loc.index < loc.siblings.length - 1 ? loc.siblings[loc.index + 1] : null;
    if (event.key === "ArrowUp" && prev?.node) {
      event.preventDefault();
      void reorderTo(loc.node, prev.node, "before");
    } else if (event.key === "ArrowDown" && next?.node) {
      event.preventDefault();
      void reorderTo(loc.node, next.node, "after");
    } else if (event.key === "ArrowRight" && prev?.node && (isContainer ? isContainer(prev.node) : prev.children.length > 0)) {
      event.preventDefault();
      void reorderTo(loc.node, prev.node, "into");
    } else if (event.key === "ArrowLeft" && loc.parentNode) {
      event.preventDefault();
      void reorderTo(loc.node, loc.parentNode, "after");
    }
  }

  // Direct keydown listener for the whole tree (see the block comment above).
  // Routes by the event target's data markers: rename input → commit/cancel;
  // a focused row → F2 rename-start or Ctrl+arrow reorder. Add-popover keys are
  // the popover's own.
  function treeKeyboard(container: HTMLElement) {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.closest(".row-add-popover")) return;
      // Enter/Escape inside the rename input commit/cancel the wrapper-owned edit.
      if (target.closest("[data-node-edit-id]")) {
        if (event.key === "Enter") {
          event.preventDefault();
          rename.commit();
        } else if (event.key === "Escape") {
          event.preventDefault();
          rename.cancel();
        }
        return;
      }
      const row = target.closest<HTMLElement>("[data-node-id]");
      const id = row?.getAttribute("data-node-id");
      if (!id) return;
      // F2 rename rides with the reorderable-tree keyboard bundle (preserving the
      // pre-4c parity where the non-reorderable Research tree had no F2).
      if (event.key === "F2") {
        if (!onReorder) return;
        event.preventDefault();
        const node = locate(id)?.node;
        if (node) rename.begin(node.id, node.title);
        return;
      }
      if (event.ctrlKey || event.metaKey) handleReorderKey(event, id);
    };
    container.addEventListener("keydown", onKey);
    return { destroy: () => container.removeEventListener("keydown", onKey) };
  }
</script>

{#if view}
  <!-- The runtime parameter strip (ADR-0032 §D): one control per declared formal,
       seeded by its default and overridable at runtime — a saved view's search box,
       generalized. The SAME `ParamStrip` the designer preview uses (#275) — every
       parameterized surface shares one implementation (§D rejects per-pane strips).
       It renders nothing when the view declares no parameters. -->
  <ParamStrip spec={view.spec} schema={view.schema} bind:overrides={paramOverrides} />
{/if}

<div class="tree-keys" use:treeKeyboard>
  <NodeList {mode} {searchPlaceholder} bind:searchValue {searchDebounceMs} {isEmpty} {whenEmpty}>
    <ViewNodeTree
      groups={effectiveGroups}
      depth={0}
      {collapsed}
      annotations={computedResult.annotations}
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
  </NodeList>
</div>

{#if add.key !== null && addMenu}
  <!-- Add-child popover shell: wrapper-owned open-state/position/dismissal; the
       consumer's `addMenu` snippet supplies the heading + type choices. -->
  <div
    class="row-add-popover"
    style={add.pos ? `top: ${add.pos.top}px; right: ${add.pos.right}px` : ""}
  >
    {@render addMenu({ parentId: add.parentId, close: () => add.close() })}
  </div>
{/if}

<style>
  /* Transparent to layout — hosts the direct keydown listener (treeKeyboard)
     around the list without introducing a box. */
  .tree-keys {
    display: contents;
  }
</style>
