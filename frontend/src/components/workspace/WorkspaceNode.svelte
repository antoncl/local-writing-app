<!--
  One node of the tiled workspace tree (#32). A `split` tiles its children with a
  draggable splitter between each pair; a `group` stacks its panels as tabs and
  renders the active one. Recurses into itself for nested splits.

  Splitter drag follows the house pattern (AGENTS.md): document-level
  mousemove/mouseup writing flex-grow to the two adjacent slots directly for
  smoothness, committing the fractions to the layout store on mouseup.
-->
<script lang="ts">
  import type { LayoutNode, PanelId } from "@/lib/types";
  import { getContext } from "svelte";
  import WorkspaceNode from "./WorkspaceNode.svelte";
  import { workspaceLayout, isEditorPanelId } from "@/lib/stores/workspaceLayout.svelte";
  import { panelRegistry } from "@/lib/stores/panelRegistry.svelte";
  import { WORKSPACE_KEY, type WorkspaceEditor } from "./workspaceContext";

  let { node }: { node: LayoutNode } = $props();
  const editor = getContext<WorkspaceEditor>(WORKSPACE_KEY);

  // Resolve a tab's presentation from either surface class: editor documents go
  // through the editor hooks, everything else through the region registry.
  function titleOf(id: PanelId): string {
    return isEditorPanelId(id) ? editor.title(id) : panelRegistry.get(id)?.title ?? id;
  }
  function badgeOf(id: PanelId): { text: string; saved: boolean } | null {
    return isEditorPanelId(id) ? editor.badge(id) : null;
  }
  function closableOf(id: PanelId): boolean {
    return isEditorPanelId(id) ? true : panelRegistry.get(id)?.closable ?? false;
  }
  function closeTab(id: PanelId): void {
    if (isEditorPanelId(id)) editor.onClose(id);
    else panelRegistry.get(id)?.onClose?.();
  }

  let containerEl: HTMLElement | undefined = $state();

  const MIN_FRACTION = 0.08;
  const EDGE_BAND = 0.25;

  const activeTab = $derived(
    node.kind === "group" ? (node.active ?? node.tabs[0] ?? null) : null,
  );

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
      let na = startA + delta;
      let nb = startB - delta;
      if (na < MIN_FRACTION) {
        na = MIN_FRACTION;
        nb = pairSum - MIN_FRACTION;
      }
      if (nb < MIN_FRACTION) {
        nb = MIN_FRACTION;
        na = pairSum - MIN_FRACTION;
      }
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

  function onBodyDragOver(event: DragEvent) {
    if (!workspaceLayout.dragging || node.kind !== "group") return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const el = event.currentTarget as HTMLElement;
    workspaceLayout.setDropZone(node.id, zoneFor(event, el));
  }

  function onBodyDrop(event: DragEvent) {
    if (!workspaceLayout.dragging) return;
    event.preventDefault();
    workspaceLayout.drop();
  }

  const dropHere = $derived(
    node.kind === "group" && workspaceLayout.dropZone?.groupId === node.id
      ? workspaceLayout.dropZone.zone
      : null,
  );
</script>

{#if node.kind === "split"}
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
{:else}
  <section class="ws-group" data-group-id={node.id} class:focused={activeTab === workspaceLayout.focusedPanel}>
    <div class="ws-tabbar" role="tablist">
      <div class="ws-tabs">
        {#each node.tabs as tab (tab)}
          <div
            class="ws-tab"
            class:active={tab === activeTab}
            role="tab"
            tabindex="0"
            aria-selected={tab === activeTab}
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
            {#if badgeOf(tab)}
              {@const b = badgeOf(tab)}
              <span class="ws-tab-badge" class:saved={b?.saved}>{b?.text}</span>
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
      {#if activeTab}
        <div class="ws-tab-actions">
          {#if isEditorPanelId(activeTab)}
            {@render editor.actions(activeTab)}
          {:else if panelRegistry.get(activeTab)?.actions}
            {@render panelRegistry.get(activeTab)!.actions!()}
          {/if}
        </div>
      {/if}
    </div>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="ws-body" ondragover={onBodyDragOver} ondrop={onBodyDrop}>
      <!-- Every tab in the group stays mounted; only the active one is shown.
           Preserves the old always-mounted semantics so live editors (TipTap),
           search state, etc. survive a tab switch without a remount. -->
      {#each node.tabs as tab (tab)}
        <div class="ws-doc" class:hidden-doc={tab !== activeTab}>
          {#if isEditorPanelId(tab)}
            {@render editor.body(tab)}
          {:else if panelRegistry.get(tab)}
            {@render panelRegistry.get(tab)!.body()}
          {/if}
        </div>
      {/each}
      {#if !activeTab}
        <p class="ws-empty">No document open.</p>
      {/if}
      {#if dropHere}
        <div class="ws-drop-indicator {dropHere}"></div>
      {/if}
    </div>
  </section>
{/if}

<style>
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
  .ws-group.focused {
    border-color: var(--accent);
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
