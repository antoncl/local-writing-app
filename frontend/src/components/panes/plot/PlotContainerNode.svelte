<!--
  PlotContainerNode — a soft, free-flow act/chapter box on the plot board (ADR-0048
  S7 Slice 4). A non-interactive backdrop the cards float over: it shows the
  container's title and its card count, sized by plotBoardLayout to wrap its member
  cards (a chapter box nests inside its act box via `level`). No @xyflow/svelte imports
  (same reason as PlotCardNode) — drawn by Svelte Flow via the `plotContainer` node type
  and mountable in happy-dom. It DOES read the structure + schema stores to resolve the
  container's live display title (with its reorder-live number), falling back to the raw
  projection title; the stores have inert defaults, so it stays happy-dom-mountable.

  The whole box is `pointer-events: none` so it never intercepts a card drag/click —
  it is structure, not a control. Structure carries no colour (plotline is the card's
  colour axis), so the box is a quiet neutral tint, an act reading a touch stronger.
-->
<script lang="ts">
  import { CONTAINER_DRAG_HANDLE_CLASS, type PlotContainerData } from "@/lib/plot/plotBoardLayout";
  import { structureStore } from "@/lib/stores/structure";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { findStructureNodeById } from "@/lib/utils/treeHelpers";
  import { structureNodeTitle } from "@/lib/utils/nodeTitle";

  let { data }: { id?: string; data: PlotContainerData; selected?: boolean } = $props();

  // Level 0 = a top-level act (stronger), 1 = a box nested inside one (quieter).
  let isAct = $derived(data.level === 0);

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
</script>

<div class="plot-container" class:act={isAct}>
  <!-- The header is the drag handle (#877): SvelteFlow's `dragHandle` targets this
       class, so the box moves ONLY when grabbed here — a window-titlebar affordance —
       and the transparent interior stays inert (card drags + edges pass through). -->
  <div class="container-head {CONTAINER_DRAG_HANDLE_CLASS}">
    <span class="container-title" title={displayTitle}>{displayTitle}</span>
    <span class="container-count">{data.count}</span>
  </div>
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
  .plot-container.act .container-title {
    color: var(--text);
  }
  .container-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
</style>
