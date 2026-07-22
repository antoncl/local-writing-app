<script lang="ts">
  // The metadata rail — the editor shell's right-hand sidecar.
  //
  // Extracted from `NodeEditor` in #409. The shell was 8 lines from the
  // file-size guard's hard cap, and this slice adds a compare axis to it; the
  // rail is the cleanest thing to lift out because it is a *sidecar* in the
  // shell + body-views + sidecars decomposition, not a split invented to buy
  // lines (`decisions-node-editor-modularization`).
  //
  // It owns its own width: a left-edge drag handle, clamped so the rail can be
  // made slimmer or wider but never collapses the body, persisted across
  // sessions. Document-level mousemove/mouseup deliberately, the same as the
  // pane drag in App.svelte — the pointer leaves a 7px handle constantly.
  //
  // The content is a snippet rather than props: the rail does not know or care
  // what a metadata panel needs, and threading its long prop list through here
  // would make this component a second place to maintain that list.
  import type { Snippet } from "svelte";

  let {
    open = $bindable(true),
    label,
    content,
  }: {
    /** Bindable so the collapse/expand affordance lives with the rail while the
     *  shell can still reset it per document (a chat pane opens collapsed). */
    open?: boolean;
    /** `${documentLabel} details`, for the landmark. */
    label: string;
    content: Snippet;
  } = $props();

  const RAIL_MIN = 220;
  const RAIL_MAX = 560;
  function loadRailWidth(): number {
    const stored = Number(localStorage.getItem("editorRailWidth"));
    return Number.isFinite(stored) && stored >= RAIL_MIN && stored <= RAIL_MAX ? stored : 280;
  }
  let railWidth = $state(loadRailWidth());
  let railEl: HTMLElement | undefined = $state();
  let railResizing = $state(false);
  let railRightEdge = 0;

  function startRailResize(event: MouseEvent) {
    event.preventDefault();
    railResizing = true;
    railRightEdge = railEl ? railEl.getBoundingClientRect().right : event.clientX + railWidth;
  }
  function onRailResizeMove(event: MouseEvent) {
    if (!railResizing) return;
    // The rail sits on the right edge; dragging its left handle leftward widens it.
    railWidth = Math.min(RAIL_MAX, Math.max(RAIL_MIN, railRightEdge - event.clientX));
  }
  function endRailResize() {
    if (!railResizing) return;
    railResizing = false;
    localStorage.setItem("editorRailWidth", String(railWidth));
  }
</script>

<svelte:window onmousemove={onRailResizeMove} onmouseup={endRailResize} />

{#if open}
  <aside class="editor-rail" class:resizing={railResizing} style={`width: ${railWidth}px`} bind:this={railEl} aria-label={label}>
    <button
      class="rail-resize"
      type="button"
      title="Drag to resize details"
      aria-label="Resize details rail"
      onmousedown={startRailResize}
    ></button>
    <div class="rail-head">
      <span class="rail-head-label">Details</span>
      <button
        class="rail-collapse"
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
  <!-- Collapsed: a 34px vertical edge-tab that reopens the rail. -->
  <button
    class="rail-tab"
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

  /* Left-edge drag handle to widen/narrow the rail. */
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

  .rail-resize:hover {
    background: linear-gradient(
      to right,
      transparent 0 2px,
      var(--accent) 2px 4px,
      transparent 4px
    );
  }

  .editor-rail.resizing {
    user-select: none;
  }

  .editor-rail.resizing .rail-resize {
    background: linear-gradient(
      to right,
      transparent 0 2px,
      var(--accent) 2px 4px,
      transparent 4px
    );
  }

  .rail-head {
    display: flex;
    align-items: center;
    gap: 7px;
    flex: 0 0 auto;
    padding: 10px 12px;
    border-bottom: 1px solid var(--divider, var(--divider));
  }

  .rail-head-label {
    flex: 1;
    font-size: var(--fs-xs);
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3, var(--text-3));
  }

  .rail-collapse {
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

  .rail-collapse:hover {
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

  /* Collapsed: a 34px vertical edge-tab that reopens the rail. */
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
</style>
