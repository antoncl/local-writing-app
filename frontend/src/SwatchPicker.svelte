<script lang="ts">
  // Popover swatch picker. Bind `value` to a swatch id (string | null).
  // The picker renders the currently-selected swatch as a small clickable
  // chip; clicking opens a grid of available swatches plus a "None" cell.
  //
  // Used wherever a `color` field renders — entry metadata pane, type
  // editor, select-option color, etc. Phase 1 reads from the same
  // `paletteStore` that App.svelte fills on settings load.

  import { paletteStore, getSwatch } from "./colors";
  import type { Swatch } from "./types";

  export let value: string | null = null;
  export let allowNone: boolean = true;
  export let onChange: ((id: string | null) => void) | undefined = undefined;

  let open = false;
  let anchor: HTMLButtonElement | undefined;
  // Viewport-relative popover position. Computed from the trigger's
  // bounding rect each time the popover opens (and on scroll/resize while
  // open) so the popover floats above ANY pane regardless of its overflow
  // — necessary because the schema_type pane and the metadata pane both
  // clip their content, which otherwise hides or squashes the popover.
  let popoverLeft = 0;
  let popoverTop = 0;

  const POPOVER_WIDTH = 180;   // matches CSS min-width
  const POPOVER_GAP = 4;       // visual gap below the trigger

  $: palette = $paletteStore;
  $: current = getSwatch(value);

  function positionPopover() {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    // Default: open below + left-aligned with the trigger. Flip to the
    // right edge of the trigger when there isn't room on the left; flip
    // above when there isn't room below.
    let left = r.left;
    if (left + POPOVER_WIDTH + 8 > window.innerWidth) {
      left = Math.max(8, r.right - POPOVER_WIDTH);
    }
    let top = r.bottom + POPOVER_GAP;
    // Rough height check — popover holds ~5 rows of 22px + padding.
    const approxHeight = 160;
    if (top + approxHeight + 8 > window.innerHeight) {
      top = Math.max(8, r.top - approxHeight - POPOVER_GAP);
    }
    popoverLeft = left;
    popoverTop = top;
  }

  function toggle() {
    if (!open) positionPopover();
    open = !open;
  }

  function close() {
    open = false;
  }

  function onScrollOrResize() {
    if (open) positionPopover();
  }

  function select(id: string | null) {
    value = id;
    onChange?.(id);
    close();
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      close();
    }
  }

  function onDocClick(event: MouseEvent) {
    if (!open) return;
    const target = event.target as Node | null;
    if (target && anchor && anchor.contains(target)) return;
    const pop = document.querySelector(".swatch-picker-popover");
    if (pop && target && pop.contains(target)) return;
    close();
  }
</script>

<svelte:window
  on:click={onDocClick}
  on:keydown={onKey}
  on:scroll={onScrollOrResize}
  on:resize={onScrollOrResize}
/>

<span class="swatch-picker">
  <button
    type="button"
    class="swatch-trigger"
    class:empty={!current}
    title={current ? current.label : "No color"}
    aria-label={current ? `Color: ${current.label}` : "Pick a color"}
    bind:this={anchor}
    on:click|stopPropagation={toggle}
  >
    {#if current}
      <span class="swatch-dot" style="background: {current.hex}"></span>
    {:else}
      <span class="swatch-dot swatch-dot-empty"></span>
    {/if}
  </button>

  {#if open}
    <div
      class="swatch-picker-popover"
      role="dialog"
      aria-label="Choose a color"
      style={`left: ${popoverLeft}px; top: ${popoverTop}px;`}
    >
      {#if allowNone}
        <button
          type="button"
          class="swatch-clear"
          class:selected={!value}
          title="Clear color (inherit / no override)"
          on:click|stopPropagation={() => select(null)}
        >
          <span class="swatch-dot swatch-dot-empty"></span>
          <span class="swatch-clear-label">Clear</span>
        </button>
      {/if}
      <div class="swatch-grid">
        {#each palette as s (s.id)}
          <button
            type="button"
            class="swatch-cell"
            class:selected={s.id === value}
            title={s.label}
            on:click|stopPropagation={() => select(s.id)}
          >
            <span class="swatch-dot" style="background: {s.hex}"></span>
          </button>
        {/each}
      </div>
      {#if current}
        <div class="swatch-current-label">{current.label}</div>
      {/if}
    </div>
  {/if}
</span>

<style>
  .swatch-picker {
    position: relative;
    display: inline-block;
    line-height: 0;
  }

  .swatch-trigger {
    appearance: none;
    background: transparent;
    border: 1px solid var(--ctx-border, #cdd8d3);
    border-radius: 6px;
    padding: 3px;
    cursor: pointer;
    line-height: 0;
    transition: border-color 80ms linear;
  }
  .swatch-trigger:hover { border-color: var(--ctx-accent, #3f7d68); }
  .swatch-trigger.empty .swatch-dot { background: transparent; }

  .swatch-dot {
    display: inline-block;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 1px solid rgba(0, 0, 0, 0.18);
  }
  .swatch-dot-empty {
    background: repeating-linear-gradient(
      45deg,
      transparent 0 3px,
      rgba(0, 0, 0, 0.18) 3px 4px
    );
  }

  .swatch-picker-popover {
    /* Anchored at viewport coords by the component — `position: fixed`
       so pane overflow can never clip the popover. z-index is high
       enough to sit above any pane and most modals. */
    position: fixed;
    z-index: 2500;
    background: var(--ctx-surface, #fff);
    border: 1px solid var(--ctx-border, #cdd8d3);
    border-radius: 8px;
    padding: 8px;
    box-shadow: 0 6px 16px rgba(40, 60, 52, 0.18);
    min-width: 180px;
  }

  .swatch-grid {
    display: grid;
    grid-template-columns: repeat(6, 22px);
    gap: 6px;
  }

  .swatch-cell {
    appearance: none;
    background: transparent;
    border: 2px solid transparent;
    border-radius: 50%;
    padding: 1px;
    cursor: pointer;
    line-height: 0;
    transition: border-color 80ms linear;
  }
  .swatch-cell:hover { border-color: rgba(0, 0, 0, 0.35); }
  .swatch-cell.selected { border-color: var(--ctx-accent, #3f7d68); }

  .swatch-clear {
    appearance: none;
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 4px 6px;
    margin-bottom: 8px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    font: inherit;
    font-size: 12px;
    color: var(--ctx-text-3, #6c7872);
    cursor: pointer;
    text-align: left;
  }
  .swatch-clear:hover {
    background: var(--ctx-panel-2, #eef3f0);
    color: var(--ctx-text, #28332f);
  }
  .swatch-clear.selected {
    border-color: var(--ctx-accent, #3f7d68);
    color: var(--ctx-accent-strong, #356b59);
  }
  .swatch-clear .swatch-dot-empty {
    border-style: dashed;
  }
  .swatch-clear-label {
    line-height: 1;
  }

  .swatch-current-label {
    margin-top: 8px;
    font-size: 11px;
    color: var(--ctx-text-3, #6c7872);
    text-align: center;
  }
</style>
