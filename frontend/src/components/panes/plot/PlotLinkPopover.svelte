<!--
  PlotLinkPopover — the shared roomy surface the card's link editors live on (#820).
  Beats and "Leads to…" used to render as sub-pages of the ~160px kebab menu, where a
  checklist of titles collapsed to "First p…". This gives both pickers real width: a
  back-to-menu header (chevron + the page title, so the whole header reads as one
  affordance), a filter box, and a scrollable body the picker rows fill.

  Purely presentational — the SHELL only (header + filter + scroll box). The picker
  rows come in as the `children` snippet and keep their own style scope. It owns no
  dismiss/positioning: PlotCardNode places it and reuses the card's outside-click /
  Escape machinery (the board is a transformed canvas, so the chrome Popover's
  viewport overlay can't anchor here). Mounts in happy-dom for its render test.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    title,
    filter = $bindable(""),
    onBack,
    children,
  }: {
    // The page title, shown in the back button (mirrors the kebab's .menu-back).
    title: string;
    // The live filter query, bindable so the host can hand it to the picker.
    filter?: string;
    // Return to the card's main menu (the host flushes the pending draft here).
    onBack: () => void;
    children: Snippet;
  } = $props();
</script>

<div class="link-popover" role="group" aria-label={title}>
  <button class="lp-back nodrag nopan" type="button" onclick={onBack}>
    <i class="ti ti-chevron-left" aria-hidden="true"></i>
    {title}
  </button>
  <div class="lp-filter-row">
    <input
      class="lp-filter nodrag nopan"
      type="text"
      placeholder="Filter…"
      bind:value={filter}
      aria-label={`Filter ${title}`}
    />
  </div>
  <div class="lp-body">
    {@render children()}
  </div>
</div>

<style>
  .link-popover {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  /* Back-to-menu affordance — the whole header row is the button, so chevron + title
     read as one target (the kebab's .menu-back pattern, widened here). */
  .lp-back {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid var(--divider);
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }
  .lp-back:hover {
    background: var(--surface);
  }
  .lp-back i {
    color: var(--text-3);
  }
  .lp-filter-row {
    padding: 7px 8px;
    border-bottom: 1px solid var(--divider);
  }
  .lp-filter {
    width: 100%;
    box-sizing: border-box;
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    background: var(--surface);
    color: var(--text);
    font-size: var(--fs-sm);
  }
  .lp-body {
    max-height: 300px;
    overflow-y: auto;
    padding: 2px;
  }
</style>
