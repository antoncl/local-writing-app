<script lang="ts">
  // The metadata rail — the editor shell's Details sidecar.
  //
  // Extracted from `NodeEditor` in #409. It docks either to the right (a width
  // column) or the bottom (a full-width row) — the latter so the long-text
  // metadata fields get the whole editor width instead of a cramped column
  // (#1246). Side + size live in the per-project `editorRailLayout` store, so a
  // writer's preferred layout survives reloads and scene switches.
  //
  // It owns its own size: a drag handle on the inner edge (left when right-docked,
  // top when bottom-docked), clamped so the rail can never collapse the body.
  // Document-level mousemove/mouseup deliberately, the same as the pane drag in
  // App.svelte — the pointer leaves the 7px handle constantly.
  //
  // The content is a snippet rather than props: the rail does not know or care
  // what a metadata panel needs, and threading its long prop list through here
  // would make this component a second place to maintain that list.
  import type { Snippet } from "svelte";
  import {
    editorRailLayout as layout,
    RAIL_WIDTH_MIN,
    RAIL_WIDTH_MAX,
    RAIL_HEIGHT_MIN,
    RAIL_HEIGHT_MAX,
  } from "@/lib/stores/editorRailLayout.svelte";

  let {
    open = $bindable(true),
    label,
    content,
  }: {
    /** Bindable so the collapse/expand affordance lives with the rail while the
     *  shell reconciles it with per-body-shape defaults (chat opens collapsed). */
    open?: boolean;
    /** `${documentLabel} details`, for the landmark. */
    label: string;
    content: Snippet;
  } = $props();

  const side = $derived(layout.side);

  let railEl: HTMLElement | undefined = $state();
  let resizing = $state(false);
  // The fixed edge the drag measures from: the rail's right edge (right dock) or
  // its bottom edge (bottom dock). Dragging the inner handle toward that edge
  // grows the rail.
  let anchorEdge = 0;

  function startResize(event: MouseEvent) {
    event.preventDefault();
    resizing = true;
    const rect = railEl?.getBoundingClientRect();
    anchorEdge =
      side === "bottom"
        ? (rect?.bottom ?? event.clientY + layout.height)
        : (rect?.right ?? event.clientX + layout.width);
  }
  function onResizeMove(event: MouseEvent) {
    if (!resizing) return;
    // Live-set the store state during the drag (drives the layout reactively);
    // persistence happens once on mouseup so we don't hammer localStorage.
    if (side === "bottom") {
      layout.height = Math.min(RAIL_HEIGHT_MAX, Math.max(RAIL_HEIGHT_MIN, anchorEdge - event.clientY));
    } else {
      layout.width = Math.min(RAIL_WIDTH_MAX, Math.max(RAIL_WIDTH_MIN, anchorEdge - event.clientX));
    }
  }
  function endResize() {
    if (!resizing) return;
    resizing = false;
    if (side === "bottom") layout.setHeight(layout.height);
    else layout.setWidth(layout.width);
  }

  function toggleSide() {
    layout.setSide(side === "right" ? "bottom" : "right");
  }
</script>

<svelte:window onmousemove={onResizeMove} onmouseup={endResize} />

{#if open}
  <aside
    class="editor-rail"
    class:bottom={side === "bottom"}
    class:resizing
    style={side === "bottom" ? `height: ${layout.height}px` : `width: ${layout.width}px`}
    bind:this={railEl}
    aria-label={label}
  >
    <button
      class="rail-resize"
      class:bottom={side === "bottom"}
      type="button"
      title="Drag to resize details"
      aria-label="Resize details rail"
      onmousedown={startResize}
    ></button>
    <div class="rail-head">
      <span class="rail-head-label">Details</span>
      <button
        class="rail-icon-btn"
        type="button"
        title={side === "bottom" ? "Dock to the right" : "Dock to the bottom"}
        aria-label={side === "bottom" ? "Dock details to the right" : "Dock details to the bottom"}
        onclick={toggleSide}
      >
        <i class={`ti ${side === "bottom" ? "ti-layout-sidebar-right" : "ti-layout-bottombar"}`} aria-hidden="true"></i>
      </button>
      <button
        class="rail-icon-btn"
        type="button"
        title="Collapse details"
        aria-label="Collapse details"
        onclick={() => (open = false)}
      >
        <i class="ti ti-layout-sidebar-right-collapse" aria-hidden="true"></i>
      </button>
    </div>
    <div class="rail-scroll">
      {@render content()}
    </div>
  </aside>
{:else}
  <!-- Collapsed: an edge-tab that reopens the rail — vertical on the right, a
       horizontal bar along the bottom. -->
  <button
    class="rail-tab"
    class:bottom={side === "bottom"}
    type="button"
    title="Show details"
    aria-label="Show details"
    onclick={() => (open = true)}
  >
    <i class="ti ti-layout-sidebar-right-expand" aria-hidden="true"></i>
    <span class="rail-tab-label">Details</span>
  </button>
{/if}

<style>
  .editor-rail {
    display: flex;
    flex-direction: column;
    position: relative;
    width: 280px;
    min-height: 0;
    background: var(--inset);
    border-left: 1px solid var(--divider);
  }

  /* Bottom dock: a full-width row instead of a side column. Height is inline; the
     border moves to the top edge. */
  .editor-rail.bottom {
    width: auto;
    border-left: 0;
    border-top: 1px solid var(--divider);
  }

  /* Drag handle: left edge for the right dock (col-resize), top edge for the
     bottom dock (row-resize). */
  .rail-resize {
    position: absolute;
    top: 0;
    left: -3px;
    width: 7px;
    height: 100%;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    cursor: col-resize;
    z-index: 5;
  }

  .rail-resize.bottom {
    top: -3px;
    left: 0;
    width: 100%;
    height: 7px;
    cursor: row-resize;
  }

  .rail-resize:hover,
  .editor-rail.resizing .rail-resize {
    background: linear-gradient(to right, transparent 0 2px, var(--accent) 2px 4px, transparent 4px);
  }

  .rail-resize.bottom:hover,
  .editor-rail.resizing .rail-resize.bottom {
    background: linear-gradient(to bottom, transparent 0 2px, var(--accent) 2px 4px, transparent 4px);
  }

  .editor-rail.resizing {
    user-select: none;
  }

  .rail-head {
    display: flex;
    align-items: center;
    gap: 7px;
    flex: 0 0 auto;
    padding: 10px 12px;
    border-bottom: 1px solid var(--divider);
  }

  .rail-head-label {
    flex: 1;
    font-size: var(--fs-xs);
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3);
  }

  .rail-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-xl);
    cursor: pointer;
  }

  .rail-icon-btn:hover {
    background: var(--surface);
    border-color: var(--divider);
    color: var(--text-2);
  }

  .rail-scroll {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    overscroll-behavior: contain;
  }

  /* Collapsed edge-tab. Right dock: a 34px vertical tab. Bottom dock: a short
     horizontal bar reading left-to-right. */
  .rail-tab {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    width: 34px;
    padding: 12px 0;
    border: 0;
    border-left: 1px solid var(--divider);
    background: var(--inset);
    color: var(--text-3);
    font-size: var(--fs-lg);
    cursor: pointer;
  }

  .rail-tab.bottom {
    flex-direction: row;
    justify-content: center;
    width: auto;
    padding: 6px 0;
    border-left: 0;
    border-top: 1px solid var(--divider);
  }

  .rail-tab:hover {
    color: var(--text);
    background: var(--panel);
  }

  .rail-tab-label {
    writing-mode: vertical-rl;
    font-size: var(--fs-xs);
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }

  .rail-tab.bottom .rail-tab-label {
    writing-mode: horizontal-tb;
  }
</style>
