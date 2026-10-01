<!--
  PlotContainerNode — a manuscript container's box on the plot board (ADR-0048 S7
  Slice 4), one per level (ADR-0094 §9), and the "Loose cards" box (ADR-0097 §8). A
  non-interactive backdrop the cards flow inside: it shows the title and its card count,
  sized by plotBoardLayout to its contents (a chapter box nests inside its act box via
  `level`). No @xyflow/svelte imports (same reason as PlotCardNode) — drawn by Svelte Flow
  via the `plotContainer` node type and mountable in happy-dom. It DOES read the structure + schema stores to resolve the
  container's live display title (with its reorder-live number), falling back to the raw
  projection title; the stores have inert defaults, so it stays happy-dom-mountable.

  The whole box is `pointer-events: none` so it never intercepts a card drag/click —
  it is structure, not a control. Structure carries no colour (plotline is the card's
  colour axis), so the box is a quiet neutral tint, an act reading a touch stronger.

  A container a deck is realized as (ADR-0097 §7) stands for that deck: it gets the deck's ⋯ menu
  in its header, from the same context the deck box uses.
-->
<script lang="ts">
  import { getContext, tick } from "svelte";
  import { PLOT_DECK_ACTIONS, type PlotDeckActions } from "./plotDeckActions";
  import { CONTAINER_DRAG_HANDLE_CLASS, type PlotContainerData } from "@/lib/plot/plotBoardLayout";
  import { structureStore } from "@/lib/stores/structure";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { findStructureNodeById } from "@/lib/utils/treeHelpers";
  import { structureNodeTitle } from "@/lib/utils/nodeTitle";

  let { data }: { id?: string; data: PlotContainerData; selected?: boolean } = $props();

  // One box per level (ADR-0094 §9): the top level is the outer frame, the next
  // the hairline default, and anything deeper a dashed edge, so three nested
  // boxes (act, chapter, sequence) stay tellable apart without any fill.
  let isAct = $derived(data.level === 0);
  let isDeep = $derived(data.level >= 2);
  // The loose box holds what belongs to no chapter or deck: dashed like a deck, no manuscript.
  let isLoose = $derived(data.boxKind === "loose");

  // A board column IS a manuscript act/chapter, so resolve its label through the
  // shared display-title resolver — the reorder-live {number} shows here the same
  // way it does in the tree. Reading the structure store keeps it live when the
  // manuscript is reordered; falls back to the raw projection title if the node
  // isn't loaded (e.g. store not yet hydrated).
  let displayTitle = $derived.by(() => {
    const root = $structureStore?.root;
    const node = root ? findStructureNodeById(root, data.containerId) : null;
    return node ? structureNodeTitle(node, $metadataSchemaStore) : data.title;
  });

  // A container a deck is realized as (ADR-0097 §7) is that deck's box: it carries the deck's
  // menu, and its rename edits the displayed text through the deck. The actions come from
  // context — absent in the mount test, so the box stays a plain backdrop.
  const actions = getContext<PlotDeckActions | undefined>(PLOT_DECK_ACTIONS);
  let deckId = $derived(data.deckId ?? null);
  let editing = $derived(!!actions && !!deckId && actions.editingId === deckId);
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
    actions?.finishRename(deckId ?? "", next && next !== data.title ? next : null);
  }

  let menuOpen = $state(false);
  let rootEl = $state<HTMLElement | null>(null);
  function run(op: ((deckId: string) => void) | undefined): void {
    menuOpen = false;
    if (deckId) op?.(deckId);
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

<div class="plot-container" bind:this={rootEl} class:act={isAct} class:deep={isDeep} class:loose={isLoose} data-level={data.level}>
  <!-- The header is the drag handle (#877): SvelteFlow's `dragHandle` targets this
       class, so the box moves ONLY when grabbed here — a window-titlebar affordance —
       and the transparent interior stays inert (card drags + edges pass through). -->
  <div class="container-head {CONTAINER_DRAG_HANDLE_CLASS}">
    {#if editing}
      <input
        bind:this={titleInput}
        bind:value={titleDraft}
        class="container-title-edit nodrag nopan"
        aria-label="Name"
        placeholder="Name"
        onblur={commitTitle}
        onkeydown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            e.currentTarget.blur();
          } else if (e.key === "Escape") {
            actions?.finishRename(deckId ?? "", null);
          }
        }}
      />
    {:else}
      <span class="container-title" title={displayTitle}>{displayTitle}</span>
    {/if}
    <span class="container-count">{data.count}</span>
    {#if deckId && actions}
      <button
        class="container-kebab nodrag nopan"
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
  {#if isLoose && data.count === 0}
    <p class="loose-hint">Drag a card here to take it out of its deck or chapter</p>
  {/if}
  {#if menuOpen && deckId && actions}
    <div class="deck-menu nodrag nopan" role="menu" aria-label="Deck actions">
      <button role="menuitem" class="menu-item" onclick={() => run(actions.onNewCard)}>
        <i class="ti ti-plus" aria-hidden="true"></i> New card
      </button>
      <button role="menuitem" class="menu-item" onclick={() => run(actions.onNewDeckInside)}>
        <i class="ti ti-stack-2" aria-hidden="true"></i> New deck inside
      </button>
      <button role="menuitem" class="menu-item" onclick={() => run(actions.startRename)}>
        <i class="ti ti-pencil" aria-hidden="true"></i> Rename
      </button>
      <button role="menuitem" class="menu-item" onclick={() => run(actions.onOpen)}>
        <i class="ti ti-eye" aria-hidden="true"></i> Open deck
      </button>
      <button role="menuitem" class="menu-item" onclick={() => run(actions.onDetach)}>
        <i class="ti ti-unlink" aria-hidden="true"></i> Detach from deck
      </button>
      <button role="menuitem" class="menu-item menu-danger" onclick={() => run(actions.onDelete)}>
        <i class="ti ti-trash" aria-hidden="true"></i> Delete deck
      </button>
    </div>
  {/if}
</div>

<style>
  .plot-container {
    box-sizing: border-box;
    /* Size comes from the node box (set in plotBoardLayout from the geometry
       constants); fill it so positions and rendered size share one source. */
    width: 100%;
    height: 100%;
    /* Structure, not a control — never intercept a card's drag/click. */
    pointer-events: none;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    /* NO fill — a container is structural scaffolding, and an opaque box would paint
       over the edge layers (manuscript / beat / causal) that pass behind it, hiding
       the very connections the board exists to show (#833). Both act and chapter
       interiors stay transparent so edges beneath read through. */
    background: transparent;
  }
  /* A top-level act reads as the outer frame the chapter boxes sit inside by its
     firmer edge alone (no fill); a nested chapter by the hairline default border. */
  .plot-container.act {
    border-color: var(--border-strong);
  }
  .plot-container.deep,
  .plot-container.loose {
    border-style: dashed;
  }
  .plot-container.loose .container-title {
    color: var(--text-3);
  }
  .container-head {
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 8px;
    /* Match CONTAINER_HEADER (32px) in plotBoardLayout so the title band lines up
       with the padding the cards start below. */
    height: 32px;
    padding: 0 12px;
    /* Re-enable pointer events on JUST the header (the box body stays `none`) so it can
       be the SvelteFlow drag handle (#877); the grab cursor advertises it. The interior
       remains inert, so card drags and the edge layers still pass through it (#833). */
    pointer-events: auto;
    cursor: grab;
  }
  .container-head:active {
    cursor: grabbing;
  }
  .container-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .plot-container.act:not(.loose) .container-title {
    color: var(--text);
  }
  .loose-hint {
    margin: 0;
    padding: 0 12px;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .container-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .container-title-edit {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    padding: 1px 4px;
  }
  /* The realized deck's menu — the same look as a deck box's (PlotDeckNode). */
  .container-kebab {
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
  .plot-container:hover .container-kebab,
  .container-kebab:focus-visible,
  .container-kebab.open {
    opacity: 1;
  }
  .container-kebab:hover {
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
