<script lang="ts">
  // Popover swatch picker. Bind `value` to a swatch id (string | null).
  // The picker renders the currently-selected swatch as a small clickable
  // chip; clicking opens a grid of available swatches plus a "None" cell.
  //
  // Used wherever a `color` field renders — entry metadata pane, type
  // editor, select-option color, etc. Phase 1 reads from the same
  // `paletteStore` that App.svelte fills on settings load.

  import { paletteStore, getSwatch } from "@/lib/utils/colors";

  interface Props {
    value?: string | null;
    allowNone?: boolean;
    onChange?: (id: string | null) => void;
    /** Read-only display (#64): the swatch chip renders, the popover never opens. */
    readOnly?: boolean;
  }

  let { value = $bindable(null), allowNone = true, onChange, readOnly = false }: Props = $props();

  let open = $state(false);
  let anchor: HTMLButtonElement | undefined = $state();
  // Viewport-relative popover position. Computed from the trigger's
  // bounding rect each time the popover opens (and on scroll/resize while
  // open) so the popover floats above ANY pane regardless of its overflow
  // — necessary because the schema_type pane and the metadata pane both
  // clip their content, which otherwise hides or squashes the popover.
  let popoverLeft = $state(0);
  let popoverTop = $state(0);

  const POPOVER_WIDTH = 180;   // matches CSS min-width
  const POPOVER_GAP = 4;       // visual gap below the trigger

  const palette = $derived($paletteStore);
  const current = $derived(getSwatch(value));

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
    if (readOnly) return;
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

  // Portal the popover to <body> so its `position: fixed` resolves against the
  // viewport, not a transformed ancestor. Inside the view designer the picker
  // lives in a Svelte Flow node whose pane carries a CSS transform, which makes
  // it the containing block for fixed descendants — trapping the popover in
  // canvas-space (#225). Mirrors NodePicker; positionPopover() already computes
  // viewport coordinates, and onDocClick already queries the portaled node.
  function portalToBody(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

<svelte:window
  onclick={onDocClick}
  onkeydown={onKey}
  onscroll={onScrollOrResize}
  onresize={onScrollOrResize}
/>

<span class="swatch-picker">
  <button
    type="button"
    class="swatch-trigger"
    class:empty={!current}
    class:read-only={readOnly}
    title={current ? current.label : "No color"}
    aria-label={current ? `Color: ${current.label}` : "Pick a color"}
    disabled={readOnly}
    bind:this={anchor}
    onclick={(e) => { e.stopPropagation(); toggle(); }}
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
      use:portalToBody
    >
      {#if allowNone}
        <button
          type="button"
          class="swatch-clear"
          class:selected={!value}
          title="Clear color (inherit / no override)"
          onclick={(e) => { e.stopPropagation(); select(null); }}
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
            onclick={(e) => { e.stopPropagation(); select(s.id); }}
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
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px;
    cursor: pointer;
    line-height: 0;
    transition: border-color 80ms linear;
  }
  .swatch-trigger:hover { border-color: var(--accent); }
  .swatch-trigger.read-only { cursor: default; }
  .swatch-trigger.read-only:hover { border-color: var(--border); }
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
       so pane overflow can never clip the popover. Stays a DOM child of
       its invoker, so inside a dialog it stacks within the dialog's own
       stacking context. */
    position: fixed;
    z-index: var(--z-dropdown);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px;
    box-shadow: var(--elev-2);
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
  .swatch-cell.selected { border-color: var(--accent); }

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
    font-size: var(--fs-sm);
    color: var(--text-3);
    cursor: pointer;
    text-align: left;
  }
  .swatch-clear:hover {
    background: var(--panel);
    color: var(--text);
  }
  .swatch-clear.selected {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  .swatch-clear .swatch-dot-empty {
    border-style: dashed;
  }
  .swatch-clear-label {
    line-height: 1;
  }

  .swatch-current-label {
    margin-top: 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    text-align: center;
  }
</style>
