<!--
  One node of the tiled workspace tree (#32). A `split` tiles its children with a
  draggable splitter between each pair; a `group` stacks its panels as tabs and
  renders the active one. Recurses into itself for nested splits.

  Splitter drag follows the house pattern (AGENTS.md): document-level
  mousemove/mouseup writing flex-grow to the two adjacent slots directly for
  smoothness, committing the fractions to the layout store on mouseup.

  Responsive collapse (#155): a split whose measured main-axis size can't fit its
  children at their declared minimum widths renders its whole subtree as a single
  tab strip instead of tiling — a view-time transform that never mutates the
  layout tree, so it re-tiles exactly when the space returns.
-->
<script lang="ts">
  import type { LayoutNode, PanelId } from "@/lib/types";
  import { getContext, untrack } from "svelte";
  import WorkspaceNode from "./WorkspaceNode.svelte";
  import { workspaceLayout, isEditorPanelId } from "@/lib/stores/workspaceLayout.svelte";
  import { flattenPanels, subtreeMinMain } from "@/lib/stores/workspaceLayout.serialize";
  import { panelRegistry } from "@/lib/stores/panelRegistry.svelte";
  import RegionActions from "./RegionActions.svelte";
  import RegionBody from "./RegionBody.svelte";
  import { WORKSPACE_KEY, type WorkspaceEditor } from "./workspaceContext";

  let { node }: { node: LayoutNode } = $props();
  const editor = getContext<WorkspaceEditor>(WORKSPACE_KEY);

  // Resolve a tab's presentation from either surface class: editor documents go
  // through the editor hooks, everything else through the region registry.
  function titleOf(id: PanelId): string {
    return isEditorPanelId(id) ? editor.title(id) : panelRegistry.get(id)?.title ?? id;
  }
  function badgeOf(id: PanelId): { text: string; saved: boolean; error?: boolean } | null {
    return isEditorPanelId(id) ? editor.badge(id) : null;
  }
  function closableOf(id: PanelId): boolean {
    return isEditorPanelId(id) ? true : panelRegistry.get(id)?.closable ?? false;
  }
  function closeTab(id: PanelId): void {
    if (isEditorPanelId(id)) editor.onClose(id);
    else panelRegistry.get(id)?.onClose?.();
  }

  // `containerEl` is the `.ws-split` (queried for slots during splitter drag).
  // `measureEl` is a wrapper present in BOTH the tiled and collapsed states, so
  // we can keep measuring to un-collapse after the split has been replaced by a
  // tab strip.
  let containerEl: HTMLElement | undefined = $state();
  let measureEl: HTMLElement | undefined = $state();

  const MIN_FRACTION = 0.08;
  const EDGE_BAND = 0.25;

  const activeTab = $derived(
    node.kind === "group" ? (node.active ?? node.tabs[0] ?? null) : null,
  );

  // --- Responsive collapse -------------------------------------------------

  // Measured pixel size of a split container. Kept current by three triggers so
  // it's robust: an initial measure when the element mounts, a window-resize
  // handler (the app's only outer resize), and a ResizeObserver that also
  // catches ancestor-splitter-driven width changes in a real browser.
  let measured = $state({ w: 0, h: 0 });

  function measure() {
    const el = measureEl;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    // Only react to real changes so `collapsed` doesn't churn on sub-pixel jitter.
    if (Math.abs(rect.width - measured.w) > 0.5 || Math.abs(rect.height - measured.h) > 0.5) {
      measured = { w: rect.width, h: rect.height };
    }
  }

  $effect(() => {
    const el = measureEl;
    if (!el || node.kind !== "split") return;
    // untrack the initial read: measure() reads `measured` for its change-guard,
    // and we must NOT make this effect depend on `measured` (it also writes it),
    // or every size change would tear down and rebuild the observer.
    untrack(measure);
    const observer = new ResizeObserver(() => measure());
    observer.observe(el);
    return () => observer.disconnect();
  });

  // Collapse when the split can't fit its children along its own axis at their
  // declared minimums. Guard on a positive measurement so we don't collapse
  // before the first layout pass.
  const collapsed = $derived.by(() => {
    if (node.kind !== "split") return false;
    const main = node.dir === "row" ? measured.w : measured.h;
    if (main <= 0) return false;
    return main < subtreeMinMain(node, node.dir);
  });

  const flat = $derived(node.kind === "split" ? flattenPanels(node) : []);
  const collapsedActive = $derived.by(() => {
    const focused = workspaceLayout.focusedPanel;
    return focused && flat.includes(focused) ? focused : flat[0] ?? null;
  });

  function startSplitDrag(event: MouseEvent, index: number) {
    if (node.kind !== "split" || event.button !== 0) return;
    event.preventDefault();
    const split = node;
    const el = containerEl;
    if (!el) return;
    const horizontal = split.dir === "row";
    const total = horizontal ? el.clientWidth : el.clientHeight;
    if (total <= 0) return;
    // The direct children of the split are slot/splitter divs interleaved; grab
    // just the slots so we can write flex-grow to the dragged pair live.
    const slots = [...el.children].filter((c) => (c as HTMLElement).classList.contains("ws-slot")) as HTMLElement[];
    const startPos = horizontal ? event.clientX : event.clientY;
    const a = index;
    const b = index + 1;
    const startA = split.sizes[a];
    const startB = split.sizes[b];
    const pairSum = startA + startB;
    let pendingA = startA;
    let pendingB = startB;

    const move = (e: MouseEvent) => {
      const pos = horizontal ? e.clientX : e.clientY;
      const delta = (pos - startPos) / total;
      // Clamp so neither slot drops below MIN_FRACTION. When the pair is already
      // smaller than two minimums (reachable after repeated splits), enforce only
      // the pair sum so the user can still rebalance, rather than the two
      // sequential clamps leaving one slot below the minimum as an ungrabbable
      // sliver.
      const lo = MIN_FRACTION;
      const hi = pairSum - MIN_FRACTION;
      let na = startA + delta;
      na = hi >= lo ? Math.min(Math.max(na, lo), hi) : Math.min(Math.max(na, 0), pairSum);
      const nb = pairSum - na;
      pendingA = na;
      pendingB = nb;
      if (slots[a]) slots[a].style.flexGrow = String(na);
      if (slots[b]) slots[b].style.flexGrow = String(nb);
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      const sizes = [...split.sizes];
      sizes[a] = pendingA;
      sizes[b] = pendingB;
      workspaceLayout.commitSizes(split.id, sizes);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up, { once: true });
  }

  // --- Tab drag-and-drop ---------------------------------------------------

  function onTabDragStart(event: DragEvent, panelId: PanelId) {
    workspaceLayout.beginDrag(panelId);
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", panelId);
    }
  }

  function zoneFor(event: DragEvent, el: HTMLElement): "center" | "left" | "right" | "top" | "bottom" {
    const r = el.getBoundingClientRect();
    const px = (event.clientX - r.left) / r.width;
    const py = (event.clientY - r.top) / r.height;
    if (px < EDGE_BAND) return "left";
    if (px > 1 - EDGE_BAND) return "right";
    if (py < EDGE_BAND) return "top";
    if (py > 1 - EDGE_BAND) return "bottom";
    return "center";
  }

  function onBodyDragOver(event: DragEvent, groupId: string) {
    if (!workspaceLayout.dragging) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const el = event.currentTarget as HTMLElement;
    workspaceLayout.setDropZone(groupId, zoneFor(event, el));
  }

  function onBodyDrop(event: DragEvent) {
    if (!workspaceLayout.dragging) return;
    event.preventDefault();
    workspaceLayout.drop();
  }

  function dropZoneFor(groupId: string): "center" | "left" | "right" | "top" | "bottom" | null {
    return workspaceLayout.dropZone?.groupId === groupId ? workspaceLayout.dropZone.zone : null;
  }
</script>

<svelte:window onresize={measure} />

<!-- Tab-group chrome, shared by real groups and collapsed splits. `droppable`
     is false for a collapsed split (a synthetic group with no tree node to
     receive a drop) — its tabs stay draggable OUT, but nothing drops onto it. -->
{#snippet tabGroup(groupId: string, tabs: PanelId[], active: PanelId | null, droppable: boolean)}
  <section
    class="ws-group"
    data-group-id={groupId}
    tabindex="-1"
    class:focused={active !== null && active === workspaceLayout.focusedPanel}
    class:zoomed={droppable && workspaceLayout.zoomedGroupId === groupId}
  >
    <div class="ws-tabbar" role="tablist">
      <div class="ws-tabs">
        {#each tabs as tab (tab)}
          {@const b = badgeOf(tab)}
          <div
            class="ws-tab"
            class:active={tab === active}
            role="tab"
            tabindex="0"
            aria-selected={tab === active}
            draggable="true"
            onclick={() => workspaceLayout.activate(tab)}
            onkeydown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                workspaceLayout.activate(tab);
              }
            }}
            ondragstart={(event) => onTabDragStart(event, tab)}
            ondragend={() => workspaceLayout.endDrag()}
          >
            <span class="ws-tab-label">{titleOf(tab)}</span>
            {#if b}
              <span class="ws-tab-badge" class:saved={b.saved} class:error={b.error}>{b.text}</span>
            {/if}
            {#if closableOf(tab)}
              <button
                class="ws-tab-close"
                type="button"
                title="Close {titleOf(tab)}"
                aria-label="Close {titleOf(tab)}"
                onmousedown={(event) => event.stopPropagation()}
                onclick={(event) => {
                  event.stopPropagation();
                  closeTab(tab);
                }}
              >×</button>
            {/if}
          </div>
        {/each}
      </div>
      <!-- Actions rail: per-region/editor actions plus the shell-level zoom
           toggle (#219, ADR-0038 §F). Real groups only — a collapsed split's
           synthetic id has no group to maximize. -->
      {#if droppable}
        <div class="ws-tab-actions">
          {#if active}
            {#if isEditorPanelId(active)}
              {@render editor.actions(active)}
            {:else}
              <RegionActions id={active} />
            {/if}
          {/if}
          <button
            class="ws-zoom"
            class:active={workspaceLayout.zoomedGroupId === groupId}
            type="button"
            title={workspaceLayout.zoomedGroupId === groupId ? "Restore pane" : "Maximize pane"}
            aria-label={workspaceLayout.zoomedGroupId === groupId ? "Restore pane" : "Maximize pane"}
            aria-pressed={workspaceLayout.zoomedGroupId === groupId}
            onmousedown={(event) => event.stopPropagation()}
            onclick={() => workspaceLayout.toggleZoom(groupId)}
          >⤢</button>
        </div>
      {/if}
    </div>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="ws-body"
      ondragover={droppable ? (event) => onBodyDragOver(event, groupId) : undefined}
      ondrop={droppable ? onBodyDrop : undefined}
    >
      <!-- Every tab stays mounted; only the active one is shown. Preserves the
           old always-mounted semantics so live editors (TipTap), search state,
           etc. survive a tab switch (or a collapse) without a remount. -->
      {#each tabs as tab (tab)}
        <div class="ws-doc" class:hidden-doc={tab !== active}>
          {#if isEditorPanelId(tab)}
            {@render editor.body(tab)}
          {:else}
            <RegionBody id={tab} />
          {/if}
        </div>
      {/each}
      {#if !active}
        <p class="ws-empty">No document open.</p>
      {/if}
      {#if droppable}
        {@const zone = dropZoneFor(groupId)}
        {#if zone}
          <div class="ws-drop-indicator {zone}"></div>
        {/if}
      {/if}
    </div>
  </section>
{/snippet}

{#if node.kind === "split"}
  <!-- Always-present wrapper so we can keep measuring (and un-collapse) after
       the tiled `.ws-split` has been swapped for a collapsed tab strip. -->
  <div class="ws-node-fill" bind:this={measureEl}>
    {#if collapsed}
      <!-- Over-subscribed split → one tab strip over its whole subtree. The tree
           is untouched, so it re-tiles exactly when there's room again. -->
      {@render tabGroup(node.id, flat, collapsedActive, false)}
    {:else}
      <div class="ws-split {node.dir}" bind:this={containerEl}>
        {#each node.children as child, i (child.id)}
          {#if i > 0}
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <div
              class="ws-splitter {node.dir}"
              role="separator"
              aria-orientation={node.dir === "row" ? "vertical" : "horizontal"}
              onmousedown={(event) => startSplitDrag(event, i - 1)}
            ></div>
          {/if}
          <div class="ws-slot" style="flex-grow: {node.sizes[i]}">
            <WorkspaceNode node={child} />
          </div>
        {/each}
      </div>
    {/if}
  </div>
{:else}
  {@render tabGroup(node.id, node.tabs, activeTab, true)}
{/if}

<style>
  /* Fills its slot and passes the fill to whichever child is showing (the tiled
     split or the collapsed tab strip), so both measure the same box. */
  .ws-node-fill {
    display: flex;
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
  }
  .ws-node-fill > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
  }
  .ws-split {
    display: flex;
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
  }
  .ws-split.row {
    flex-direction: row;
  }
  .ws-split.col {
    flex-direction: column;
  }
  .ws-slot {
    flex-basis: 0;
    min-width: 0;
    min-height: 0;
    display: flex;
  }
  .ws-slot > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
  }

  .ws-splitter {
    flex: 0 0 auto;
    background: transparent;
    position: relative;
    z-index: var(--z-sticky);
  }
  .ws-splitter.row {
    width: var(--sp-1);
    cursor: col-resize;
  }
  .ws-splitter.col {
    height: var(--sp-1);
    cursor: row-resize;
  }
  .ws-splitter::after {
    content: "";
    position: absolute;
    inset: 0;
    background: var(--divider);
    transition: background var(--t-fast);
  }
  .ws-splitter:hover::after {
    background: var(--accent);
  }

  .ws-group {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    width: 100%;
    height: 100%;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    overflow: hidden;
  }
  .ws-group:focus {
    outline: none;
  }
  .ws-group.focused {
    border-color: var(--accent);
  }
  /* Zoom (#219): CSS-promote this tile to fill the positioned .workspace,
     painting over the tiled tree beneath — which stays mounted, so no editor
     remounts on maximize/restore. Sits above the splitters (--z-sticky);
     popovers/dialogs still layer above it. */
  .ws-group.zoomed {
    position: absolute;
    inset: 0;
    z-index: var(--z-dropdown);
  }

  /* The bar wraps: when a region is too narrow to fit tabs + actions on one
     row, the actions drop to a second row instead of crowding out / sliding
     over the tabs. Wide regions stay a single row. */
  .ws-tabbar {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: var(--sp-2);
    min-height: var(--sp-5);
    padding-right: var(--sp-2);
    border-bottom: 1px solid var(--divider);
    background: var(--panel);
  }
  /* Tabs take the first row and scroll within it when there are many; the
     actions keep their natural width, pinned right (or wrapped to row two). */
  .ws-tabs {
    flex: 1 1 auto;
    display: flex;
    align-items: stretch;
    min-width: 0;
    overflow-x: auto;
  }
  .ws-tab {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    padding: var(--sp-1) var(--sp-3);
    font-size: var(--fs-md);
    color: var(--text-3);
    border-right: 1px solid var(--divider);
    border-bottom: 2px solid transparent;
    cursor: pointer;
    white-space: nowrap;
    user-select: none;
    transition: color var(--t-fast), background var(--t-fast);
  }
  .ws-tab:hover {
    background: var(--inset);
    color: var(--text-2);
  }
  .ws-tab.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .ws-tab-label {
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 22ch;
  }
  .ws-tab-badge {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .ws-tab-badge.saved {
    color: var(--accent-emphasis);
  }
  .ws-tab-badge.error {
    color: var(--danger);
    font-weight: 600;
  }
  .ws-tab-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--sp-4);
    height: var(--sp-4);
    padding: 0;
    border: none;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
  }
  .ws-tab-close:hover {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .ws-tab-actions {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    margin-left: auto;
    padding-left: var(--sp-2);
  }

  /* Shell zoom toggle — a quiet ghost glyph at rest; accent-tinted while this
     tile is maximized so the live state reads without a hover (§4 stateful
     selector). */
  .ws-zoom {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--sp-5);
    height: var(--sp-5);
    padding: 0;
    border: none;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
    transition: color var(--t-fast), background var(--t-fast);
  }
  .ws-zoom:hover {
    background: var(--inset);
    color: var(--text-2);
  }
  .ws-zoom.active {
    background: var(--accent-soft);
    color: var(--accent-emphasis);
  }

  .ws-body {
    position: relative;
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .ws-doc {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  /* Fill on the primary child (the region body / editor), letting a leading
     banner keep its natural height. */
  .ws-doc > :global(*) {
    min-height: 0;
  }
  .ws-doc > :global(*:last-child) {
    flex: 1 1 auto;
  }
  .hidden-doc {
    display: none;
  }
  .ws-empty {
    margin: auto;
    color: var(--text-3);
    font-size: var(--fs-md);
  }

  .ws-drop-indicator {
    position: absolute;
    background: var(--accent-soft);
    border: 1px solid var(--accent);
    border-radius: var(--r-sm);
    pointer-events: none;
    z-index: var(--z-overlay);
  }
  .ws-drop-indicator.center {
    inset: var(--sp-2);
  }
  .ws-drop-indicator.left {
    top: 0;
    bottom: 0;
    left: 0;
    width: 50%;
  }
  .ws-drop-indicator.right {
    top: 0;
    bottom: 0;
    right: 0;
    width: 50%;
  }
  .ws-drop-indicator.top {
    left: 0;
    right: 0;
    top: 0;
    height: 50%;
  }
  .ws-drop-indicator.bottom {
    left: 0;
    right: 0;
    bottom: 0;
    height: 50%;
  }
</style>
