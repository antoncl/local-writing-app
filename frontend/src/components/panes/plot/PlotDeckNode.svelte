<!--
  PlotDeckNode — a deck's box on the plot board (ADR-0097 §2, §8): a plot-only container of
  cards that has no scene and no place in the manuscript. A dashed border (a deck is not
  structure, so it reads apart from the solid chapter boxes), the title in the serif, the
  first two lines of its synopsis, a card count, and a ⋯ menu — New card, New deck inside,
  Rename, Realize as a level (when the level list allows one here), Open, Delete. An inherited deck (`movable` false) offers Open alone.

  Like PlotContainerNode it imports nothing from @xyflow/svelte and the box body is
  `pointer-events: none`, so a card drag or board pan passes through the interior; only the
  header re-enables them (it is the drag handle of a top-level box, #877). The actions come
  from context — absent in the mount test, so the box is a read-only backdrop with no menu.
-->
<script lang="ts">
  import { getContext, tick } from "svelte";
  import { CONTAINER_DRAG_HANDLE_CLASS, type PlotDeckData } from "@/lib/plot/plotBoardLayout";
  import { deckSynopsisLines } from "@/lib/plot/boxLayout";
  import { PLOT_DECK_ACTIONS, type PlotDeckActions } from "./plotDeckActions";

  let { data }: { id?: string; data: PlotDeckData; selected?: boolean } = $props();

  const actions = getContext<PlotDeckActions | undefined>(PLOT_DECK_ACTIONS);

  let synopsisLines = $derived(deckSynopsisLines(data.synopsis));
  // An inherited deck can be opened, not edited, nested into, or deleted.
  let editable = $derived(!!actions && data.movable);

  // The title edit is the board's state (a fresh deck opens straight into it).
  let editing = $derived(!!actions && data.movable && actions.editingId === data.deckId);
  let titleDraft = $state("");
  let titleInput = $state<HTMLInputElement | null>(null);
  $effect(() => {
    if (!editing) return;
    titleDraft = data.title;
    void tick().then(() => {
      titleInput?.focus();
      titleInput?.select();
    });
  });
  function commitTitle(): void {
    if (!editing) return; // Escape already abandoned it
    const next = titleDraft.trim();
    actions?.finishRename(data.deckId, next && next !== data.title ? next : null);
  }

  let menuOpen = $state(false);
  let rootEl = $state<HTMLElement | null>(null);
  function run(op: ((deckId: string) => void) | undefined): void {
    menuOpen = false;
    op?.(data.deckId);
  }
  $effect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => {
      if (rootEl && !rootEl.contains(e.target as Node)) menuOpen = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") menuOpen = false;
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  });
</script>

<div class="plot-deck" bind:this={rootEl} data-testid="plot-deck">
  <!-- The header is the drag handle of a top-level box (#877): SvelteFlow's `dragHandle`
       targets this class, so the box moves ONLY when grabbed here. -->
  <div class="deck-head {CONTAINER_DRAG_HANDLE_CLASS}">
    <div class="deck-title-row">
      {#if editing}
        <input
          bind:this={titleInput}
          bind:value={titleDraft}
          class="deck-title-edit nodrag nopan"
          aria-label="Deck name"
          placeholder="Deck name"
          onblur={commitTitle}
          onkeydown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              e.currentTarget.blur();
            } else if (e.key === "Escape") {
              actions?.finishRename(data.deckId, null);
            }
          }}
        />
      {:else}
        <span class="deck-title" title={data.title}>{data.title || "Untitled deck"}</span>
      {/if}
      <span class="deck-meta">deck · {data.count}</span>
      {#if actions}
        <button
          class="deck-kebab nodrag nopan"
          class:open={menuOpen}
          aria-label="Deck actions"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onclick={() => (menuOpen = !menuOpen)}
        >
          <i class="ti ti-dots-vertical" aria-hidden="true"></i>
        </button>
      {/if}
    </div>
    {#each synopsisLines as line, i (i)}
      <p class="deck-synopsis" title={line}>{line}</p>
    {/each}
  </div>

  {#if menuOpen && actions}
    <div class="deck-menu nodrag nopan" role="menu" aria-label="Deck actions">
      {#if editable}
        <button role="menuitem" class="menu-item" onclick={() => run(actions.onNewCard)}>
          <i class="ti ti-plus" aria-hidden="true"></i> New card
        </button>
        <button role="menuitem" class="menu-item" onclick={() => run(actions.onNewDeckInside)}>
          <i class="ti ti-stack-2" aria-hidden="true"></i> New deck inside
        </button>
        <button role="menuitem" class="menu-item" onclick={() => run(actions.startRename)}>
          <i class="ti ti-pencil" aria-hidden="true"></i> Rename
        </button>
      {/if}
      {#if editable && data.realizeLevel}
        <button role="menuitem" class="menu-item" onclick={() => run(actions.onRealize)}>
          <i class="ti ti-wand" aria-hidden="true"></i> Realize as {data.realizeLevel}
        </button>
      {/if}
      <button role="menuitem" class="menu-item" onclick={() => run(actions.onOpen)}>
        <i class="ti ti-eye" aria-hidden="true"></i> Open
      </button>
      {#if editable}
        <button role="menuitem" class="menu-item menu-danger" onclick={() => run(actions.onDelete)}>
          <i class="ti ti-trash" aria-hidden="true"></i> Delete
        </button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .plot-deck {
    position: relative;
    box-sizing: border-box;
    /* Size comes from the node box (set in plotBoardLayout from the geometry constants);
       fill it so positions and rendered size share one source. */
    width: 100%;
    height: 100%;
    /* The interior never intercepts a card's drag/click; the header re-enables it. */
    pointer-events: none;
    border: 1px dashed var(--border-strong);
    border-radius: var(--r-lg);
    background: transparent;
  }
  .deck-head {
    box-sizing: border-box;
    padding: 0 12px;
    pointer-events: auto;
    cursor: grab;
  }
  .deck-head:active {
    cursor: grabbing;
  }
  /* Match CONTAINER_HEADER (32px) in boardGeometry so the title row lines up with the band
     the cards start below; each synopsis line is DECK_SYNOPSIS_LINE_H (18px) under it. */
  .deck-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 32px;
  }
  .deck-title {
    flex: 1;
    min-width: 0;
    font-family: var(--serif);
    font-size: var(--fs-lg);
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .deck-title-edit {
    flex: 1;
    min-width: 0;
    font-family: var(--serif);
    font-size: var(--fs-md);
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    padding: 1px 4px;
  }
  .deck-meta {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .deck-synopsis {
    margin: 0;
    height: 18px;
    line-height: 18px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .deck-kebab {
    appearance: none;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px 4px;
    border: none;
    background: transparent;
    color: var(--text-3);
    border-radius: var(--r-sm);
    cursor: pointer;
    opacity: 0;
    transition: opacity 120ms ease;
  }
  .plot-deck:hover .deck-kebab,
  .deck-kebab:focus-visible,
  .deck-kebab.open {
    opacity: 1;
  }
  .deck-kebab:hover {
    background: var(--surface);
    color: var(--text);
  }
  .deck-menu {
    position: absolute;
    top: 30px;
    right: 8px;
    z-index: 5;
    min-width: 160px;
    display: flex;
    flex-direction: column;
    padding: 4px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--elev-2);
    pointer-events: auto;
  }
  .deck-menu .menu-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    text-align: left;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .deck-menu .menu-item:hover {
    background: var(--surface);
  }
  .deck-menu .menu-danger {
    color: var(--danger);
  }
  .deck-menu .menu-danger:hover {
    background: var(--danger-soft);
  }
  .deck-menu .menu-danger i {
    color: var(--danger);
  }
</style>
