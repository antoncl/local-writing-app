<!--
  ViewSwitcher — the pane handle-bar view selector (0.5.0 step 4, #81, doc §5).
  Sits beside a pane's "+ Entry" / "+ Assistant" action: the implicit default
  view first, then the saved views anchored to this pane's kind, then a
  "New view…" affordance that opens the designer (reusing createAndOpenView).
  Selection is UI state (paneViews / localStorage), not project data.
-->
<script lang="ts">
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";

  interface Props {
    // The pane's anchor kind ("lore" / "scene" / "assistant").
    kind: string;
  }
  let { kind }: Props = $props();

  let open = $state(false);

  let saved = $derived(paneViews.viewsFor(kind));
  let selectedId = $derived(paneViews.selectedId(kind));
  let currentLabel = $derived(
    selectedId ? (saved.find((v) => v.id === selectedId)?.title ?? "View") : "Default view",
  );

  function toggle(): void {
    open = !open;
    if (open) void paneViews.reload(); // freshen the roster on open
  }

  function pick(id: string | null): void {
    paneViews.select(kind, id);
    open = false;
  }

  function newView(): void {
    open = false;
    void editorPanes.createAndOpenView(kind);
  }

  function editView(id: string): void {
    open = false;
    void editorPanes.openView(id);
  }

  function deleteView(id: string, title: string): void {
    open = false;
    editorPanes.requestDeleteView(id, title);
  }

  function onWindowClick(event: MouseEvent): void {
    if (!(event.target as HTMLElement)?.closest?.(".view-switcher")) open = false;
  }
</script>

<svelte:window onclick={onWindowClick} />

<span class="view-switcher">
  <button
    class="pin-button view-switcher-trigger"
    class:active={open}
    type="button"
    title="Switch view"
    aria-haspopup="listbox"
    aria-expanded={open}
    onmousedown={(event) => event.stopPropagation()}
    onclick={toggle}
  >
    <span class="view-switcher-label">{currentLabel}</span>
    <span class="view-switcher-caret" aria-hidden="true">▾</span>
  </button>
  {#if open}
    <div class="view-switcher-popover" role="listbox">
      <button
        class="view-switcher-item"
        class:selected={!selectedId}
        type="button"
        role="option"
        aria-selected={!selectedId}
        onclick={() => pick(null)}
      >
        <span class="view-switcher-check">{!selectedId ? "✓" : ""}</span>
        <span class="view-switcher-item-label">Default view</span>
      </button>
      {#each saved as view (view.id)}
        <div class="view-switcher-item" class:selected={selectedId === view.id}>
          <button
            class="view-switcher-pick"
            type="button"
            role="option"
            aria-selected={selectedId === view.id}
            onclick={() => pick(view.id)}
          >
            <span class="view-switcher-check">{selectedId === view.id ? "✓" : ""}</span>
            <span class="view-switcher-item-label">{view.title}</span>
          </button>
          <span class="view-switcher-actions">
            <button class="vsa" type="button" title="Edit view" aria-label={`Edit ${view.title}`} onclick={() => editView(view.id)}>✎</button>
            <button class="vsa vsa-del" type="button" title="Delete view" aria-label={`Delete ${view.title}`} onclick={() => deleteView(view.id, view.title)}>×</button>
          </span>
        </div>
      {/each}
      <div class="view-switcher-divider"></div>
      <button class="view-switcher-item view-switcher-new" type="button" onclick={newView}>
        <span class="view-switcher-check">＋</span>
        <span class="view-switcher-item-label">New view…</span>
      </button>
    </div>
  {/if}
</span>

<style>
  .view-switcher {
    position: relative;
    display: inline-flex;
  }

  .view-switcher-trigger {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    max-width: 160px;
  }

  .view-switcher-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .view-switcher-caret {
    font-size: 9px;
    opacity: 0.7;
  }

  .view-switcher-popover {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 1000;
    min-width: 180px;
    max-width: 260px;
    padding: 4px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 6px 18px var(--shadow2);
  }

  .view-switcher-item {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 5px 8px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .view-switcher-item:hover {
    background: var(--panel);
  }

  .view-switcher-item.selected {
    color: var(--accent-strong);
  }

  /* Saved-view rows wrap a pick button + hover-revealed edit/delete
     affordances (right-aligned, per the widget taxonomy). The container
     keeps the row padding; the pick button is unpadded and fills the row. */
  .view-switcher-pick {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1;
    min-width: 0;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .view-switcher-actions {
    display: inline-flex;
    gap: 2px;
    flex: 0 0 auto;
    opacity: 0;
    transition: opacity 80ms linear;
  }

  .view-switcher-item:hover .view-switcher-actions,
  .view-switcher-item:focus-within .view-switcher-actions {
    opacity: 1;
  }

  .vsa {
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: 13px;
    line-height: 1;
    padding: 2px 4px;
    border-radius: 4px;
    cursor: pointer;
  }

  .vsa:hover {
    background: var(--surface);
    color: var(--text);
  }

  .vsa-del:hover {
    color: var(--danger, #d64545);
  }

  .view-switcher-check {
    flex: 0 0 auto;
    width: 12px;
    color: var(--accent-strong);
    font-size: 11px;
  }

  .view-switcher-item-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .view-switcher-divider {
    height: 1px;
    margin: 4px 2px;
    background: var(--border);
  }

  .view-switcher-new {
    color: var(--text-2);
  }
</style>
