<script lang="ts">
  // Shared chrome for the two mutation dialogs (/mutate authoring + the
  // Mutations-pane set editor): backdrop-click/Escape to cancel, an editorial
  // card with header + scrollable body + action footer, and a drag-resize
  // corner. Deliberately NOT Modal.svelte — that chrome is for settings-style
  // dialogs that must not dismiss on backdrop click and never resize.
  //
  // Resize follows the App.svelte pane convention: document-level
  // mousemove/mouseup with direct DOM style updates (no reactive state on the
  // hot path) — do not "simplify" without re-testing drag in a real browser.
  import type { Snippet } from "svelte";

  let {
    title,
    subtitle = "",
    ariaLabel = "",
    initialWidth = 560,
    onCancel,
    footer,
    children,
  }: {
    title: string;
    subtitle?: string;
    ariaLabel?: string;
    /** Starting card width in px; height stays auto (capped) until dragged. */
    initialWidth?: number;
    onCancel: () => void;
    footer?: Snippet;
    children?: Snippet;
  } = $props();

  let card: HTMLDivElement | undefined = $state();

  function onResizeStart(event: MouseEvent) {
    if (!card) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const rect = card.getBoundingClientRect();
    const el = card;
    function onMove(e: MouseEvent) {
      const width = Math.min(
        Math.max(420, rect.width + (e.clientX - startX)),
        window.innerWidth * 0.94,
      );
      const height = Math.min(
        Math.max(280, rect.height + (e.clientY - startY)),
        window.innerHeight * 0.9,
      );
      el.style.width = `${width}px`;
      el.style.height = `${height}px`;
      el.style.maxHeight = "none";
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="mdlg-overlay" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    bind:this={card}
    class="mdlg-card"
    role="dialog"
    aria-label={ariaLabel || title}
    tabindex="-1"
    style={`width: min(${initialWidth}px, 94vw);`}
    onclick={(e) => e.stopPropagation()}
  >
    <header class="mdlg-head">
      <h3>{title}</h3>
      {#if subtitle}
        <p>{subtitle}</p>
      {/if}
    </header>
    <div class="mdlg-body">
      {@render children?.()}
    </div>
    {#if footer}
      <footer class="mdlg-foot">
        {@render footer()}
      </footer>
    {/if}
    <div class="mdlg-resize" role="presentation" title="Drag to resize" onmousedown={onResizeStart}></div>
  </div>
</div>

<style>
  .mdlg-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--scrim);
  }
  .mdlg-card {
    position: relative;
    display: flex;
    flex-direction: column;
    max-height: 84vh;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: var(--elev-3);
    padding: 18px;
  }
  .mdlg-head {
    flex: none;
  }
  .mdlg-head h3 {
    margin: 0 0 2px;
    font-size: var(--fs-xl);
    color: var(--text);
  }
  .mdlg-head p {
    margin: 0 0 14px;
    font-size: var(--fs-md);
    color: var(--text-3);
  }
  .mdlg-body {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    /* Keep focus rings / picker popovers from clipping at the left edge. */
    padding: 1px;
  }
  .mdlg-foot {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 12px;
  }
  .mdlg-resize {
    position: absolute;
    right: 0;
    bottom: 0;
    width: 16px;
    height: 16px;
    cursor: nwse-resize;
    /* Corner grip: two short diagonal strokes. */
    background:
      linear-gradient(135deg, transparent 50%, var(--border) 50%, var(--border) 58%, transparent 58%),
      linear-gradient(135deg, transparent 70%, var(--border) 70%, var(--border) 78%, transparent 78%);
    border-bottom-right-radius: 9px;
  }
  /* Footer button vocabulary shared by both mutation dialogs. */
  .mdlg-foot :global(button) {
    padding: 7px 14px;
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
    border: 1px solid var(--border);
  }
  .mdlg-foot :global(button.ghost) {
    background: transparent;
    color: var(--text-2);
  }
  .mdlg-foot :global(button.danger) {
    background: transparent;
    color: var(--danger);
    border-color: color-mix(in oklab, var(--danger) 40%, transparent);
  }
  .mdlg-foot :global(button.primary) {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
    font-weight: 600;
  }
  .mdlg-foot :global(button.primary:disabled) {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .mdlg-foot :global(.spacer) {
    flex: 1 1 auto;
  }
</style>
