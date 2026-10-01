<!--
  PlotStoryTimeView — the board's second view (ADR-0097 §8): every card in one wrapping
  sequence in story time, the order things HAPPEN (the manuscript carries the order they
  are told). Plain DOM, not SvelteFlow — it is a list, and it stays mountable in happy-dom.

  Dragging a card between two others changes only its story time: the left or right half
  of the target decides before / after, and an insertion bar shows where it lands. Drag is
  never the only way — each card's menu has Earlier / Later / Place after…, and its title
  opens the card. A card the open layer does not own (inherited) cannot be moved or
  anchored on, so it is neither draggable nor a drop target. The handlers arrive through
  the same context as the board's cards (PlotEditor provides it).
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";
  import type { StoryAnchor } from "@/lib/api/plot";
  import { inStoryOrder, lateCauseTitle, lateCausesByEffect, storySwapAnchors } from "@/lib/plot/storyTime";
  import { PLOT_CARD_ACTIONS, type PlotCardActions } from "./plotCardActions";

  let { projection }: { projection: PlotBoardProjection } = $props();

  const actions = getContext<PlotCardActions | undefined>(PLOT_CARD_ACTIONS);

  let ordered = $derived(inStoryOrder(projection.cards));
  let lateCauses = $derived(lateCausesByEffect(projection.cards));
  let lineColor = $derived(new Map(projection.plotlines.map((l) => [l.id, getSwatch(l.color)?.hex ?? null])));

  const placeLabel = (card: PlotBoardCard): string =>
    card.sequence != null ? `Scene ${card.sequence + 1}` : "Unwritten";

  // --- Drag: which card is in flight, and where its insertion bar shows.
  let dragId = $state<string | null>(null);
  let insert = $state<{ id: string; side: "before" | "after" } | null>(null);

  function onDragStart(e: DragEvent, card: PlotBoardCard) {
    dragId = card.id;
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", card.title); // Firefox starts no drag without data
      // Drag the whole card's picture, not just the grip it started on.
      const cardEl = (e.currentTarget as HTMLElement | null)?.closest("li");
      if (cardEl) e.dataTransfer.setDragImage(cardEl, 16, 16);
    }
  }
  function endDrag() {
    dragId = null;
    insert = null;
  }
  const canDropOn = (card: PlotBoardCard): boolean => dragId !== null && dragId !== card.id && card.story_movable;
  function sideOf(e: DragEvent): "before" | "after" {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    return e.clientX < rect.left + rect.width / 2 ? "before" : "after";
  }
  function onDragOver(e: DragEvent, card: PlotBoardCard) {
    if (!canDropOn(card)) return;
    e.preventDefault(); // allow the drop
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    insert = { id: card.id, side: sideOf(e) };
  }
  function onDragLeave(e: DragEvent, card: PlotBoardCard) {
    if ((e.currentTarget as Node).contains(e.relatedTarget as Node | null)) return;
    if (insert?.id === card.id) insert = null;
  }
  function onDrop(e: DragEvent, card: PlotBoardCard) {
    if (!canDropOn(card)) return;
    e.preventDefault();
    const moving = dragId!;
    const anchor: StoryAnchor = sideOf(e) === "before" ? { before_id: card.id } : { after_id: card.id };
    endDrag();
    actions?.onStoryMove(moving, anchor);
  }

  // --- The per-card menu (keyboard path): Earlier / Later / Place after…
  let menuFor = $state<string | null>(null);
  let menuView = $state<"main" | "place">("main");
  let placeFilter = $state("");
  let rootEl = $state<HTMLElement | null>(null);

  function closeMenu() {
    menuFor = null;
    menuView = "main";
    placeFilter = "";
  }
  function toggleMenu(id: string) {
    if (menuFor === id) return closeMenu();
    menuFor = id;
    menuView = "main";
    placeFilter = "";
  }
  function move(id: string, anchor: StoryAnchor) {
    closeMenu();
    actions?.onStoryMove(id, anchor);
  }
  let placeChoices = $derived(
    (actions?.storyAnchors ?? []).filter(
      (c) => c.id !== menuFor && c.title.toLowerCase().includes(placeFilter.trim().toLowerCase()),
    ),
  );

  // Close on an outside press or Escape, only while a menu is open.
  $effect(() => {
    if (menuFor === null) return;
    const onDown = (e: PointerEvent) => {
      if (rootEl && !rootEl.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMenu();
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  });
</script>

<div class="story-view" bind:this={rootEl}>
  {#if ordered.length === 0}
    <p class="story-empty">No cards yet.</p>
  {:else}
    <div class="axis" aria-hidden="true"><span>Earliest</span><span>Latest</span></div>
    <ol class="story-flow" aria-label="Cards in story time">
      {#each ordered as card (card.id)}
        {@const accent = card.plotline ? (lineColor.get(card.plotline) ?? null) : null}
        {@const late = lateCauses.get(card.id)}
        {@const swap = storySwapAnchors(ordered, card.id)}
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -- the card is an HTML5
             drag source / drop target; the keyboard path is its menu. -->
        <li
          class="story-card"
          class:accented={accent}
          class:dragging={dragId === card.id}
          class:ins-before={insert?.id === card.id && insert.side === "before"}
          class:ins-after={insert?.id === card.id && insert.side === "after"}
          style={accent ? `--card-accent: ${accent}` : undefined}
          data-card-id={card.id}
          ondragend={endDrag}
          ondragover={(e) => onDragOver(e, card)}
          ondragleave={(e) => onDragLeave(e, card)}
          ondrop={(e) => onDrop(e, card)}
        >
          <div class="story-head">
            {#if card.story_movable}
              <!-- The card drags by this grip only, as on the board (#876), so the title
                   and menu stay plain clicks. -->
              <span
                class="story-grip"
                draggable="true"
                title="Drag to reorder in story time"
                aria-hidden="true"
                data-grip-for={card.id}
                ondragstart={(e) => onDragStart(e, card)}
              >
                <i class="ti ti-grip-vertical"></i>
              </span>
            {/if}
            <button class="story-title" title="Open card" onclick={() => actions?.onOpen(card.id)}>
              {card.title || "Untitled card"}
            </button>
            {#if actions && card.story_movable}
              <button
                class="story-kebab"
                aria-label={`Story time actions for ${card.title || "Untitled card"}`}
                aria-haspopup="menu"
                aria-expanded={menuFor === card.id}
                onclick={() => toggleMenu(card.id)}
              >
                <i class="ti ti-dots-vertical" aria-hidden="true"></i>
              </button>
            {/if}
          </div>
          {#if card.synopsis}<p class="story-synopsis">{card.synopsis}</p>{/if}
          <div class="story-foot">
            <span class="story-pill" class:scene={card.sequence != null}>{placeLabel(card)}</span>
            {#if late}
              <span class="story-pill warn" title={lateCauseTitle(late)}>Cause is later</span>
            {/if}
            {#if card.plotline}
              <span class="story-dot" class:uncoloured={!accent} aria-hidden="true"></span>
            {/if}
          </div>
          {#if menuFor === card.id && actions}
            <div class="story-menu" role="menu" aria-label="Story time">
              {#if menuView === "main"}
                {#if swap.earlier}
                  <button role="menuitem" class="menu-item" onclick={() => move(card.id, swap.earlier!)}>
                    Earlier in story time
                  </button>
                {/if}
                {#if swap.later}
                  <button role="menuitem" class="menu-item" onclick={() => move(card.id, swap.later!)}>
                    Later in story time
                  </button>
                {/if}
                {#if actions.storyAnchors.some((c) => c.id !== card.id)}
                  <button role="menuitem" class="menu-item" onclick={() => (menuView = "place")}>Place after…</button>
                {/if}
              {:else}
                <button class="menu-item menu-back" onclick={() => (menuView = "main")}>Place after…</button>
                <input class="menu-filter" placeholder="Filter cards" aria-label="Filter cards" bind:value={placeFilter} />
                <div class="menu-scroll" role="group" aria-label="Cards in story time">
                  {#each placeChoices as choice (choice.id)}
                    <button role="menuitem" class="menu-item" onclick={() => move(card.id, { after_id: choice.id })}>
                      {choice.title || "Untitled card"}
                    </button>
                  {:else}
                    <span class="menu-empty">No matching cards</span>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</div>

<style>
  .story-view {
    height: 100%;
    overflow-y: auto;
    padding: var(--sp-3) var(--sp-4);
  }
  .story-empty {
    margin: 0;
    font-size: var(--fs-md);
    color: var(--text-3);
  }
  .axis {
    display: flex;
    justify-content: space-between;
    margin: 0 2px 6px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .story-flow {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin: 0;
    padding: var(--sp-3);
    list-style: none;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
  }
  .story-card {
    position: relative;
    box-sizing: border-box;
    width: 180px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 10px 8px 12px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--elev-1);
    color: var(--text);
  }
  /* The board card's grip (PlotCardNode `.card-drag-handle`), at story-card size. */
  .story-grip {
    flex: none;
    display: inline-flex;
    align-items: center;
    margin-left: -4px;
    padding: 1px 2px 0;
    color: var(--text-3);
    font-size: var(--fs-lg);
    line-height: 1;
    cursor: grab;
    transition: color 120ms ease;
  }
  .story-card:hover .story-grip {
    color: var(--text);
  }
  .story-grip:active {
    cursor: grabbing;
  }
  /* The plotline stripe down the left edge, as the board's card draws it. */
  .story-card.accented {
    box-shadow: inset 4px 0 0 0 var(--card-accent), var(--elev-1);
  }
  .story-card.dragging {
    opacity: 0.4;
  }
  /* The insertion bar (the mockup's): a 3px accent bar in the gap before / after the target. */
  .story-card.ins-before::before,
  .story-card.ins-after::after {
    content: "";
    position: absolute;
    top: 2px;
    bottom: 2px;
    width: 3px;
    border-radius: 2px;
    background: var(--accent);
  }
  .story-card.ins-before::before {
    left: -8px;
  }
  .story-card.ins-after::after {
    right: -8px;
  }
  .story-head {
    display: flex;
    align-items: flex-start;
    gap: 4px;
  }
  .story-title {
    flex: 1;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--text);
    font-family: var(--serif);
    font-size: var(--fs-lg);
    line-height: 1.3;
    text-align: left;
    cursor: pointer;
  }
  .story-title:hover {
    text-decoration: underline;
  }
  .story-kebab {
    flex: none;
    padding: 0 2px;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .story-kebab:hover {
    color: var(--text);
  }
  .story-synopsis {
    margin: 0;
    font-size: var(--fs-sm);
    line-height: 1.4;
    color: var(--text-2);
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .story-foot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    margin-top: auto;
  }
  .story-pill {
    padding: 0 7px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: 999px;
  }
  .story-pill.scene {
    color: var(--accent);
    background: var(--accent-soft);
    border-color: var(--accent);
  }
  .story-pill.warn {
    color: var(--warn);
    background: var(--warn-soft);
    border-color: var(--warn-border);
  }
  .story-dot {
    width: 7px;
    height: 7px;
    margin-left: auto;
    border-radius: 50%;
    background: var(--card-accent, var(--text-3));
  }
  .story-dot.uncoloured {
    background: transparent;
    border: 1px solid var(--text-3);
  }
  .story-menu {
    position: absolute;
    top: 26px;
    right: 6px;
    z-index: 5;
    min-width: 160px;
    display: flex;
    flex-direction: column;
    padding: 4px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--elev-2);
  }
  .menu-item {
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
  .menu-item:hover {
    background: var(--surface);
  }
  .menu-back {
    color: var(--text-2);
    font-weight: 600;
  }
  .menu-filter {
    margin: 2px 4px 4px;
    padding: 4px 6px;
    font-size: var(--fs-sm);
    color: var(--text);
    background: var(--inset);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
  }
  .menu-scroll {
    display: flex;
    flex-direction: column;
    max-height: 180px;
    overflow-y: auto;
  }
  .menu-empty {
    padding: 6px 8px;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
</style>
