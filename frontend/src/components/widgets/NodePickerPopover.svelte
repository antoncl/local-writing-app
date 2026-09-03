<script module lang="ts">
  import type { PickTreeRow } from "@/components/widgets/PickTree.svelte";

  // A source rendered in the popover: the root shows one axis row per axis
  // (name · count · ▸); drilling in renders that axis's tri-state `rows`.
  export type PickAxis = { id: string; label: string; count: number; rows: PickTreeRow[] };

  // The presentational view-model NodePicker derives and hands down. Every
  // field is read-only render state — the domain logic (what's picked, what a
  // toggle does) stays in the NodePicker controller (frontend-architecture.md).
  export type NodePickerPopoverModel = {
    axes: PickAxis[];
    effectiveAxis: string | null;
    singleAxis: string | null;
    atRoot: boolean;
    activeAxisLabel: string;
    activePanelRows: PickTreeRow[];
    hasAnyConfigured: boolean;
    hasAnyResults: boolean;
    totalVisibleItems: number;
    // ADR-0082 §2 / F1: "Create ‹title›" — present only when the active
    // panel's config resolves to one concrete entry type and the typed
    // search matches no existing candidate by title. Rendered above the
    // panel's own rows, wherever they show (drilled-in or single-axis).
    createRow: { title: string; onCreate: () => void } | null;
  };
</script>

<script lang="ts">
  // NodePickerPopover — the floating menu shell of NodePicker (the drill-in
  // context picker, ADR-0074). Extracted from NodePicker.svelte (#1538) as a
  // pure view over the picker's derived state: it renders the search head, the
  // root axis list / drilled-in tri-state panel / contextual search results,
  // and the per-panel Clear. It owns no domain state — NodePicker passes a
  // view-model plus `search`/`searchInputEl` (bindable, so the controller keeps
  // positioning + focus) and three navigation callbacks.

  import { isSearchActive } from "@/lib/utils/entrySearch";
  import { portalToBody } from "@/lib/actions/portal";
  import PickTree from "@/components/widgets/PickTree.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  let {
    model,
    menuStyle = "",
    compact = false,
    search = $bindable(""),
    searchInputEl = $bindable(null),
    onDrillInto,
    onBackToRoot,
    onClearPanel,
  }: {
    model: NodePickerPopoverModel;
    menuStyle?: string;
    compact?: boolean;
    search?: string;
    searchInputEl?: HTMLInputElement | null;
    onDrillInto: (id: string) => void;
    onBackToRoot: () => void;
    onClearPanel: () => void;
  } = $props();
</script>

<div class="ctx-menu" class:compact role="menu" style={menuStyle} use:portalToBody>
  {#snippet emptySearch()}
    <div class="ctx-empty">
      <svg class="ctx-empty-icon-svg" width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.4" />
        <line x1="15" y1="15" x2="21" y2="21" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
      </svg>
      <span class="ctx-empty-title">No matches for <strong>"{search}"</strong></span>
      <span class="ctx-empty-hint">Try a different term, or clear the search to browse.</span>
    </div>
  {/snippet}

  {#snippet createRow(row: { title: string; onCreate: () => void })}
    <!-- ADR-0082 §2 / F1: lifted from TagRosterPopover's `trp-create` gesture
         (same "Create ‹x›" affordance, generalized to any create_missing
         source — NodePicker/this shell know nothing about tags). -->
    <button
      type="button"
      class="ctx-create-row"
      data-testid="node-picker-create"
      onmousedown={(e) => e.preventDefault()}
      onclick={row.onCreate}
    >
      <span class="ctx-create-plus" aria-hidden="true">+</span> Create “{row.title}”
    </button>
  {/snippet}

  <!-- Popover head: ← back (when drilled into an axis) + the panel title +
       the search box (ADR-0074 slice 7b drill-in). -->
  <div class="ctx-pop-head">
    {#if model.effectiveAxis && !model.singleAxis}
      <button type="button" class="ctx-back" aria-label="Back to sources" onclick={onBackToRoot}>←</button>
    {/if}
    {#if model.effectiveAxis}
      <span class="ctx-panel-title">{model.activeAxisLabel}</span>
    {/if}
    <label class="ctx-search-wrap" class:has-query={search.length > 0}>
      <svg class="ctx-search-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <circle cx="6" cy="6" r="4.2" stroke="currentColor" stroke-width="1.6" />
        <line x1="9.2" y1="9.2" x2="12.5" y2="12.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
      </svg>
      <input
        class="ctx-search"
        type="text"
        placeholder={compact ? "Search…" : "Search titles, tags, aliases…  (#tag)"}
        bind:value={search}
        bind:this={searchInputEl}
      />
      {#if search.length > 0}
        <button
          type="button"
          class="ctx-search-clear"
          aria-label="Clear search"
          onclick={() => (search = "")}
        >×</button>
      {:else if model.hasAnyResults}
        <span class="ctx-search-count">{model.totalVisibleItems}{compact ? "" : " items"}</span>
      {/if}
    </label>
  </div>

  <div class="ctx-pop-body">
    {#if !model.hasAnyConfigured}
      <div class="ctx-empty">
        <span class="ctx-empty-icon" aria-hidden="true">∅</span>
        <span class="ctx-empty-title">No content sources configured</span>
        <span class="ctx-empty-hint">
          This prompt's author didn't enable any pickable types or presets for this input.
        </span>
      </div>
    {:else if isSearchActive(search)}
      <!-- Search is contextual: cross-axis results at root, within-axis when
           drilled in (ADR-0074 slice 7b). -->
      {#if model.effectiveAxis}
        {#if model.createRow}
          {@render createRow(model.createRow)}
        {/if}
        {#if model.activePanelRows.length > 0}
          <PickTree rows={model.activePanelRows} ariaLabel={model.activeAxisLabel} />
        {:else if !model.createRow}
          {@render emptySearch()}
        {/if}
      {:else if model.axes.length > 0}
        {#each model.axes as ax (ax.id)}
          <div class="ctx-result-head">{ax.label}</div>
          <PickTree rows={ax.rows} ariaLabel={ax.label} />
        {/each}
      {:else}
        {@render emptySearch()}
      {/if}
    {:else if model.atRoot}
      <!-- Root: the axis list. Tap an axis to drill into its panel. -->
      {#if model.axes.length > 0}
        {#each model.axes as ax (ax.id)}
          <button type="button" class="ctx-axis-row" onclick={() => onDrillInto(ax.id)}>
            <span class="ctx-axis-name">{ax.label}</span>
            <span class="ctx-axis-count">{ax.count}</span>
            <GroupCaret size="xs" collapsed />
          </button>
        {/each}
      {:else}
        <div class="ctx-empty">
          <span class="ctx-empty-icon" aria-hidden="true">∅</span>
          <span class="ctx-empty-title">No pickable items in this project yet</span>
        </div>
      {/if}
    {:else if model.activePanelRows.length > 0}
      <!-- Drilled-in panel: the axis's tri-state rows. -->
      <PickTree rows={model.activePanelRows} ariaLabel={model.activeAxisLabel} />
    {:else}
      <div class="ctx-empty">
        <span class="ctx-empty-icon" aria-hidden="true">∅</span>
        <span class="ctx-empty-title">Nothing here yet</span>
      </div>
    {/if}
  </div>

  {#if model.effectiveAxis && !isSearchActive(search) && model.activePanelRows.length > 0}
    <button type="button" class="ctx-clear" onclick={onClearPanel}>⃠ Clear this panel’s selection</button>
  {/if}
</div>

<style>
  /* The popover shell (portaled to <body> to escape a transformed Svelte Flow
     ancestor / metadata-panel overflow). Role tokens live on :root, so they
     reach it anywhere in the tree. */
  .ctx-menu {
    /* `fixed` so the popover escapes ancestor overflow:auto/hidden
       containers (notably .metadata-panel's scroll region that was
       clipping it when this picker is hosted by ReferencePicker inside
       a lore/scene metadata field). Coordinates are JS-computed from
       the trigger's getBoundingClientRect — see NodePicker.positionMenu(). */
    position: fixed;
    /* Keep width/max-height in sync with MENU_WIDTH / MENU_MAX_HEIGHT in
       NodePicker.positionMenu() — that math clamps this box to the viewport. */
    width: 344px;
    max-width: calc(100vw - 16px);
    max-height: 420px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 11px;
    box-shadow: var(--elev-2);
    /* The head (search + back/title) and the per-panel Clear pin; the pop-body
       scrolls between them (ADR-0074 slice 7b drill-in), so the menu itself
       clips rather than scrolls and carries no padding of its own. */
    overflow: hidden;
    /* Above modal backdrops (InputsDialog's scrim is z-index 1000): this
       picker is launched from inside the inputs dialog, so a lower value
       let the scrim paint over the menu and swallow every click (#1274).
       10000 matches the sibling body-portaled popovers — TagPicker,
       SwatchPicker, ColoredSelect — which all float above modals. */
    z-index: 10000;
    display: flex;
    flex-direction: column;
    min-width: 0;
    color: var(--text);
  }

  /* `compact` is set on the menu itself (not just the picker root) so it still
     applies once the menu portals to <body>. */
  .ctx-menu.compact {
    width: 280px;
  }

  /* --- Drill-in shell: head / body / clear (ADR-0074 slice 7b) ------ */
  .ctx-pop-head {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px;
    border-bottom: 1px solid var(--border);
  }
  .ctx-pop-head .ctx-search-wrap {
    flex: 1;
    min-width: 0;
  }
  .ctx-back {
    flex: none;
    width: 30px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--accent);
    border-radius: var(--r-md);
    cursor: pointer;
    font-size: var(--fs-lg);
  }
  .ctx-back:hover {
    background: var(--inset);
  }
  .ctx-panel-title {
    flex: none;
    font-family: var(--serif);
    font-size: var(--fs-lg);
    white-space: nowrap;
    padding-right: 2px;
  }
  .ctx-pop-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .ctx-axis-row {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 10px;
    border: none;
    background: transparent;
    border-radius: var(--r-md);
    cursor: pointer;
    text-align: left;
    color: var(--text);
    font: inherit;
  }
  .ctx-axis-row:hover {
    background: var(--inset);
  }
  .ctx-axis-name {
    flex: 1;
    min-width: 0;
  }
  .ctx-axis-count {
    flex: none;
    font-size: var(--fs-sm);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .ctx-result-head {
    font-family: var(--serif);
    font-size: var(--fs-lg);
    color: var(--text-2);
    padding: 8px 8px 2px;
  }

  /* "Create ‹x›" (ADR-0082 §2 / F1) — mirrors TagRosterPopover's .trp-create. */
  .ctx-create-row {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    margin-bottom: 2px;
    padding: 7px 9px;
    border: 1px dashed var(--accent);
    border-radius: var(--r-md);
    background: transparent;
    color: var(--accent-strong);
    font-size: var(--fs-sm);
    font-family: inherit;
    text-align: left;
    cursor: pointer;
  }
  .ctx-create-row:hover {
    background: var(--accent-soft);
  }
  .ctx-create-plus {
    font-size: var(--fs-md);
    line-height: 1;
  }
  .ctx-clear {
    flex: none;
    width: 100%;
    border: none;
    border-top: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
    padding: 8px 10px;
    text-align: left;
    cursor: pointer;
    font-size: var(--fs-sm);
    font-family: inherit;
  }
  .ctx-clear:hover {
    color: var(--text);
    background: var(--inset);
  }

  /* Search input — pill with leading icon + trailing count/clear. */
  .ctx-search-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 11px;
    border: 1px solid var(--border-strong);
    border-radius: 9px;
    background: var(--surface);
    transition: border-color 80ms linear, border-width 0s;
  }

  .ctx-search-wrap:focus-within,
  .ctx-search-wrap.has-query {
    border-color: var(--accent);
  }

  .ctx-search-icon {
    color: var(--text-3);
    flex: none;
  }

  .ctx-search-wrap:focus-within .ctx-search-icon,
  .ctx-search-wrap.has-query .ctx-search-icon {
    color: var(--accent);
  }

  .ctx-search {
    flex: 1;
    min-width: 0;
    appearance: none;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-md);
    padding: 0;
    font-family: inherit;
  }

  .ctx-search:focus {
    outline: none;
  }

  .ctx-search::placeholder {
    color: var(--text-3);
  }

  .ctx-search-count {
    flex: none;
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--text-3);
  }

  .ctx-search-clear {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
    border-radius: 3px;
    flex: none;
  }

  .ctx-search-clear:hover {
    background: var(--inset);
    color: var(--text);
  }

  /* --- Empty states ------------------------------------------------ */

  .ctx-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 30px 22px;
    text-align: center;
  }

  .ctx-empty-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: var(--inset);
    border: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-3);
    font-size: var(--fs-xl);
    line-height: 1;
  }

  .ctx-empty-icon-svg {
    color: var(--text-3);
    opacity: 0.6;
  }

  .ctx-empty-title {
    font-size: var(--fs-md);
    color: var(--text-2);
  }

  .ctx-empty-title strong {
    color: var(--text);
    font-weight: 600;
  }

  .ctx-empty-hint {
    font-size: var(--fs-sm);
    color: var(--text-3);
    line-height: 1.45;
  }
</style>
