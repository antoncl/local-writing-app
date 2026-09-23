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
  // The gesture itself (ADR-0091 §7) is the shared `SplitHandle` widget — this
  // component keeps only the clamp and persistence, in the drag callbacks.
  //
  // The content is a snippet rather than props: the rail does not know or care
  // what a metadata panel needs, and threading its long prop list through here
  // would make this component a second place to maintain that list.
  import type { Snippet } from "svelte";
  import SplitHandle from "@/components/widgets/SplitHandle.svelte";
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
    detached = false,
    onDetach,
    onReattach,
  }: {
    /** Bindable so the collapse/expand affordance lives with the rail while the
     *  shell reconciles it with per-body-shape defaults (chat opens collapsed). */
    open?: boolean;
    /** `${documentLabel} details`, for the landmark. */
    label: string;
    content: Snippet;
    /** The rail's content has been torn out into its own subordinate pane
     *  (ADR-0062 reuse, #1258). The rail itself shows only a reattach husk; the
     *  content renders in the detached pane, so it is NOT rendered here. */
    detached?: boolean;
    /** Tear the rail's content out into its own pane. Absent ⇒ no detach glyph
     *  (the shell only wires it where a host pane exists). */
    onDetach?: () => void;
    /** Fold the detached pane back into the rail. */
    onReattach?: () => void;
  } = $props();

  const side = $derived(layout.side);

  let railEl: HTMLElement | undefined = $state();
  let resizing = $state(false);
  // The fixed edge the drag measures from: the rail's right edge (right dock) or
  // its bottom edge (bottom dock). Dragging the inner handle toward that edge
  // grows the rail.
  let anchorEdge = 0;

  // The three `SplitHandle` callbacks: this component keeps only the clamp and
  // the persistence, matching every host's contract (ADR-0091 §7) — the drag
  // gesture itself (preventDefault, the document-level listeners) lives in
  // the shared widget now.
  function onDragStart(event: MouseEvent) {
    resizing = true;
    const rect = railEl?.getBoundingClientRect();
    anchorEdge =
      side === "bottom"
        ? (rect?.bottom ?? event.clientY + layout.height)
        : (rect?.right ?? event.clientX + layout.width);
  }
  function onDrag(event: MouseEvent) {
    // Live-set the store state during the drag (drives the layout reactively);
    // persistence happens once on drag end so we don't hammer localStorage.
    if (side === "bottom") {
      layout.height = Math.min(RAIL_HEIGHT_MAX, Math.max(RAIL_HEIGHT_MIN, anchorEdge - event.clientY));
    } else {
      layout.width = Math.min(RAIL_WIDTH_MAX, Math.max(RAIL_WIDTH_MIN, anchorEdge - event.clientX));
    }
  }
  function onDragEnd() {
    resizing = false;
    if (side === "bottom") layout.setHeight(layout.height);
    else layout.setWidth(layout.width);
  }

  function toggleSide() {
    layout.setSide(side === "right" ? "bottom" : "right");
  }
</script>

{#if detached}
  <!-- Detached: the content lives in its own subordinate pane (#1258). The rail
       keeps only a husk edge-tab that folds it back — the counterpart to the
       prompt sub-tab's in-strip reattach glyph. -->
  <button
    class="rail-tab detached"
    class:bottom={side === "bottom"}
    type="button"
    title="Reattach details"
    aria-label="Reattach details"
    onclick={() => onReattach?.()}
  >
    <i class="ti ti-arrow-bar-to-left" aria-hidden="true"></i>
    <span class="rail-tab-label">Details</span>
  </button>
{:else if open}
  <aside
    class="editor-rail"
    class:bottom={side === "bottom"}
    class:resizing
    style={side === "bottom" ? `height: ${layout.height}px` : `width: ${layout.width}px`}
    bind:this={railEl}
    aria-label={label}
  >
    <SplitHandle
      orientation={side === "bottom" ? "horizontal" : "vertical"}
      label="Resize details rail"
      {onDragStart}
      {onDrag}
      {onDragEnd}
      class={side === "bottom" ? "rail-resize bottom" : "rail-resize"}
    />
    <div class="rail-head">
      <span class="rail-head-label">Details</span>
      <button
        class="rail-icon-btn"
        type="button"
        title={side === "bottom" ? "Dock to the right" : "Dock to the bottom"}
        aria-label={side === "bottom" ? "Dock details to the right" : "Dock details to the bottom"}
        onclick={toggleSide}
      >
        <!-- Directional chevron: down = dock to the bottom, right = dock to the
             right. The `ti-layout-*` dock glyphs are in the tabler CSS but absent
             from the font the app loads (they render zero-width, #1251); chevrons
             are verified to render. -->
        <i class={`ti ${side === "bottom" ? "ti-chevron-right" : "ti-chevron-down"}`} aria-hidden="true"></i>
      </button>
      {#if onDetach}
        <!-- Tear Details out into its own subordinate pane (#1258), the same
             gesture the prompt editor's sub-tabs use. `ti-arrow-bar-to-right` is
             verified to render (the `ti-layout-*` dock glyphs are not, #1251). -->
        <button
          class="rail-icon-btn"
          type="button"
          title="Detach details into its own pane"
          aria-label="Detach details into its own pane"
          onclick={() => onDetach?.()}
        >
          <i class="ti ti-arrow-bar-to-right" aria-hidden="true"></i>
        </button>
      {/if}
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

  /* Drag handle placement only (ADR-0091 §7): the gesture, the hover/dragging
     accent stripe, and the cursor all live in the shared `SplitHandle` widget
     now — this is `:global()` (valid inside a Svelte scoped block, unlike a
     plain .css file) because the class is passed INTO a child component, so
     it never carries the rail's own scope attribute. Left edge for the right
     dock, top edge for the bottom dock. */
  :global(.rail-resize) {
    position: absolute;
    top: 0;
    left: -3px;
    width: 7px;
    height: 100%;
    z-index: 5;
  }

  :global(.rail-resize.bottom) {
    top: -3px;
    left: 0;
    width: 100%;
    height: 7px;
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
    font-weight: var(--w-semibold);
    letter-spacing: 0.07em;
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
