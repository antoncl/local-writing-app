<!--
  PlotEditor — the plot board (ADR-0048 S7). A SvelteFlow canvas that renders the
  S7a projection: plotlines as horizontal lanes, cards laid out in their lane.
  S7b displayed it read-only; S7c (#760) makes the CARD layout editable — cards
  drag, positions persist to the board's opaque `layout`, and a drag is undoable
  via the shared ADR-0050 caretaker (Tier-1: layout only). Lane headers stay
  fixed. Content ops (realize/attach/seed = S7d) and plotline surfaces (S7e) are
  later sub-slices; per ADR-0048 binding decision 1 they are intentful mutations
  OUTSIDE the caretaker (an in-memory undo must never reverse a scene mint).

  The projection → nodes transform is the pure, unit-tested `buildBoardNodes`; the
  undo logic is the pure GraphUndoController + caretaker — the canvas itself is not
  headless-testable ([[reference_svelteflow_headless_limits]]), so every reversible
  bit lives outside it and the custom nodes carry their own mount tests.
-->
<script lang="ts">
  import "@xyflow/svelte/dist/style.css";
  import { SvelteFlow, Controls, type ColorMode, type Edge } from "@xyflow/svelte";
  import { themePreference } from "@/lib/utils/theme";
  import {
    buildBoardNodes,
    cardPositionsFromNodes,
    readBoardPositions,
    type PlotBoardNode,
  } from "@/lib/plot/plotBoardLayout";
  import { GraphUndoController } from "@/lib/graph/graphUndoController.svelte";
  import type { GraphPort } from "@/lib/graph/graphCommands";
  import { savePlotBoardLayout } from "@/lib/stores/plotBoard";
  import UndoRedoControls from "@/components/UndoRedoControls.svelte";
  import ViewportFit from "@/components/editor/body/view/ViewportFit.svelte";
  import PlotCardNode from "./plot/PlotCardNode.svelte";
  import PlotLaneNode from "./plot/PlotLaneNode.svelte";
  import type { BoardXY, PlotBoardProjection } from "@/lib/types";

  // The board's read model, fetched by the opener / PlotBoardPane into the store.
  // Null until the first refresh resolves; the pane shows a neutral loading blank.
  let { projection }: { projection: PlotBoardProjection | null } = $props();

  // Coalesce a drag's position churn into one save on release.
  const SAVE_DEBOUNCE_MS = 600;

  // Svelte Flow's arrays, bound to the canvas. Edges stay empty in S7c (card→
  // scene/plotline wires are S7f, and don't render headless anyway).
  let flowNodes = $state<PlotBoardNode[]>([]);
  let flowEdges = $state<Edge[]>([]);
  // Optimistic base for the next layout save, and a snapshot guard so the persist
  // effect fires only on a real change — never on the just-loaded state.
  let revision = $state("");
  let lastSavedPositions = $state("");
  // True while a card is dragging, so the debounce waits for release (one save
  // per gesture), mirroring ViewBodyView's autosave.
  let dragging = $state(false);

  // The board's undo history (ADR-0050): the shared caretaker via GraphUndoController,
  // its own instance per §3, replaying through a port over our rune arrays. In S7c
  // it records only drags — content ops are intentful and outside undo.
  const graphPort: GraphPort<PlotBoardNode, Edge> = {
    getNodes: () => flowNodes,
    setNodes: (n) => (flowNodes = n),
    getEdges: () => flowEdges,
    setEdges: (e) => (flowEdges = e),
  };
  const undoCtl = new GraphUndoController<PlotBoardNode, Edge>(graphPort);

  const nodeTypes = { plotCard: PlotCardNode, plotLane: PlotLaneNode };
  // Svelte Flow ships light-only chrome; drive its theme from the app's.
  let colorMode = $derived($themePreference as ColorMode);

  // Empty = the singleton exists but holds no plotlines and no cards yet.
  let isEmpty = $derived(!!projection && projection.plotlines.length === 0 && projection.cards.length === 0);

  // (Re)hydrate from a fetched projection: fresh document → fresh nodes, revision,
  // save-guard, and a cleared history (§3: undo never crosses documents). Runs ONLY
  // when the projection prop itself changes (open / reopen) — a layout save does not
  // update the store, so our own saves never re-enter here and rebuild the canvas
  // from under an edit. $effect.PRE so the nodes are present before <SvelteFlow>
  // mounts (projection null→set), matching S7b.
  $effect.pre(() => {
    if (!projection) {
      flowNodes = [];
      return;
    }
    const saved = readBoardPositions(projection.layout);
    flowNodes = buildBoardNodes(projection, saved);
    revision = projection.board_revision;
    // Snapshot exactly what we rendered (derived + overrides) so a never-touched
    // board doesn't save on open — only a drag / undo diverges from this.
    lastSavedPositions = JSON.stringify(cardPositionsFromNodes(flowNodes));
    undoCtl.reset();
  });

  // Autosave the layout: watch card positions, skip while dragging and when nothing
  // changed, else debounce a PUT. Undo/redo mutate the same positions, so they
  // persist through this path too — no separate save. A load matches the snapshot,
  // so it never triggers a write.
  $effect(() => {
    const positions = cardPositionsFromNodes(flowNodes);
    const serialized = JSON.stringify(positions);
    if (!projection || dragging || serialized === lastSavedPositions) return;
    const handle = setTimeout(() => void persist(positions, serialized), SAVE_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  });

  async function persist(positions: Record<string, BoardXY>, serialized: string): Promise<void> {
    try {
      revision = await savePlotBoardLayout({ positions }, revision);
      lastSavedPositions = serialized;
    } catch {
      // Leave the guard unadvanced so the next change retries. A surfaced
      // load/error state machine is #756.
    }
  }
</script>

<!-- The keydown is board-scoped (ADR-0050 §3): it rides BUBBLING from whatever
     focusable element inside has focus (canvas, controls), so a chord in another
     pane can never reach this caretaker. Same sanctioned delegation exception as
     the view designer — the labelled section is an implicit region, and making it
     a tab stop would add a ghost stop for keyboard users. -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section class="plot-board" aria-label="Plot board" onkeydown={undoCtl.handleKeydown}>
  {#if !projection}
    <p class="board-hint muted">Loading the board…</p>
  {:else if isEmpty}
    <p class="board-hint muted">No plotlines or cards yet. Add a plotline, or seed cards from the manuscript.</p>
  {:else}
    <div class="board-toolbar">
      <UndoRedoControls
        canUndo={undoCtl.canUndo}
        canRedo={undoCtl.canRedo}
        undoTitle={undoCtl.undoTitle}
        redoTitle={undoCtl.redoTitle}
        announcement={undoCtl.announcement}
        onUndo={() => undoCtl.undo()}
        onRedo={() => undoCtl.redo()}
      />
    </div>
    <div class="board-canvas">
      <SvelteFlow
        bind:nodes={flowNodes}
        bind:edges={flowEdges}
        {nodeTypes}
        {colorMode}
        nodesConnectable={false}
        elementsSelectable={false}
        onnodedragstart={({ nodes }) => {
          dragging = true;
          undoCtl.dragStart(nodes);
        }}
        onnodedragstop={({ nodes }) => {
          dragging = false;
          undoCtl.dragStop(nodes);
        }}
        minZoom={0.2}
      >
        <!-- §G (design language): a flat --board surface, no dotted <Background/>. -->
        <Controls showLock={false} />
        <!-- Frame the board on load. The init-only `fitView` PROP frames an empty
             canvas (nodes arrive after mount), so this imperative fit reframes once
             the projection's nodes are measured — the ViewBodyView fix. -->
        <ViewportFit trigger={projection} options={{ padding: 0.2, maxZoom: 1 }} />
      </SvelteFlow>
    </div>
  {/if}
</section>

<style>
  .plot-board {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    background: var(--board);
  }
  .board-toolbar {
    display: flex;
    justify-content: flex-end;
    padding: var(--sp-1) var(--sp-2);
  }
  .board-canvas {
    flex: 1;
    min-height: 0;
  }
  .board-hint {
    padding: 16px;
  }
  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
