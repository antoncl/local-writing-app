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
  import { onDestroy, setContext } from "svelte";
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
  import {
    savePlotBoardLayout,
    realizeCard,
    detachCardScene,
    saveCardSynopsis,
    seedCardsFromManuscript,
  } from "@/lib/stores/plotBoard";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import UndoRedoControls from "@/components/UndoRedoControls.svelte";
  import ViewportFit from "@/components/editor/body/view/ViewportFit.svelte";
  import PlotCardNode from "./plot/PlotCardNode.svelte";
  import PlotLaneNode from "./plot/PlotLaneNode.svelte";
  import { PLOT_CARD_ACTIONS, type PlotCardActions } from "./plot/plotCardActions";
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
  // The board id currently hydrated into flowNodes — a plain (non-reactive) local.
  // The rehydrate effect compares the incoming projection's board_id against it so a
  // refetch of the SAME document (re-opening the menu) doesn't rebuild the canvas and
  // discard an in-progress edit; only a genuinely different board re-hydrates.
  let loadedBoardId = "";

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

  // Per-card actions handed to PlotCardNode via context (ADR-0048 S7d). Content ops
  // are intentful backend mutations OUTSIDE the layout caretaker (binding decision 1)
  // — realize/detach never enter the Ctrl+Z history. Each store helper refetches the
  // projection so the board re-projects the changed card (visible reflow is the
  // rehydrate-on-content-op wiring in the reflow slice).
  setContext<PlotCardActions>(PLOT_CARD_ACTIONS, {
    onOpen: (cardId) => void editorPanes.openPlotCard(cardId),
    onRealize: (cardId) => void realizeCard(cardId),
    onDetach: (cardId) => void detachCardScene(cardId),
    onEditSynopsis: (cardId, synopsis) => void saveCardSynopsis(cardId, synopsis),
  });

  // Seed-from-manuscript (ADR-0048 §S5): bulk, idempotent. Confirmed because it can
  // mint many cards at once, though re-running it is safe (already-carded scenes skip).
  function seed(): void {
    confirmService.request({
      title: "Seed from manuscript",
      message: "Create one card per scene that isn't carded yet, each attached to its scene. Safe to run again — already-carded scenes are skipped.",
      confirmLabel: "Seed cards",
      destructive: false,
      onConfirm: async () => {
        await seedCardsFromManuscript();
      },
    });
  }

  const nodeTypes = { plotCard: PlotCardNode, plotLane: PlotLaneNode };
  // Svelte Flow ships light-only chrome; drive its theme from the app's.
  let colorMode = $derived($themePreference as ColorMode);

  // Empty = the singleton exists but holds no plotlines and no cards yet.
  let isEmpty = $derived(!!projection && projection.plotlines.length === 0 && projection.cards.length === 0);

  // (Re)hydrate from a fetched projection. Guarded on board_id so it fires once per
  // DOCUMENT, not per projection reference: a layout save doesn't touch the store, but
  // the opener / PlotBoardPane can re-set an equal projection, and rebuilding then
  // would discard an in-progress edit and reset undo. The snapshot reads the LOCAL
  // built array, never the reactive `flowNodes` — reading flowNodes back would
  // subscribe this effect to xyflow's in-place position mutations, so every drag would
  // re-run it and snap the card back. $effect.PRE so nodes are present before
  // <SvelteFlow> mounts (projection null→set).
  $effect.pre(() => {
    if (!projection) {
      loadedBoardId = "";
      flowNodes = [];
      dragging = false;
      return;
    }
    if (projection.board_id === loadedBoardId) return;
    loadedBoardId = projection.board_id;
    const saved = readBoardPositions(projection.layout);
    const nodes = buildBoardNodes(projection, saved);
    flowNodes = nodes;
    revision = projection.board_revision;
    // Snapshot from the local `nodes` (not reactive flowNodes) so a never-touched
    // board doesn't save on open and this effect stays subscribed to `projection` only.
    lastSavedPositions = JSON.stringify(cardPositionsFromNodes(nodes));
    dragging = false;
    undoCtl.reset();
  });

  // Autosave the layout: skip while dragging (coalesce the gesture) and when nothing
  // changed, else debounce a PUT. The projection/dragging guard runs FIRST so a drag
  // doesn't re-serialize the whole board every frame (ViewBodyView's pattern). Undo/
  // redo mutate the same positions and persist through here too — no separate save; a
  // load matches the snapshot, so it never writes.
  $effect(() => {
    if (!projection || dragging) return;
    const positions = cardPositionsFromNodes(flowNodes);
    const serialized = JSON.stringify(positions);
    if (serialized === lastSavedPositions) return;
    const handle = setTimeout(() => void persist(positions, serialized), SAVE_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  });

  // Flush a pending (debounced) layout change when the pane unmounts, so closing the
  // board right after a drag doesn't lose it. Best-effort: the PUT is fired, not
  // awaited (the fetch outlives the component). Project-switch / reload flushing is
  // the deferred save-state machine (#756).
  onDestroy(() => {
    if (!projection || dragging) return;
    const positions = cardPositionsFromNodes(flowNodes);
    const serialized = JSON.stringify(positions);
    if (serialized !== lastSavedPositions) void persist(positions, serialized);
  });

  async function persist(positions: Record<string, BoardXY>, serialized: string): Promise<void> {
    try {
      revision = await savePlotBoardLayout({ positions }, revision);
      lastSavedPositions = serialized;
    } catch {
      // Leave the guard unadvanced so the next change retries. The surfaced
      // load/error state machine (409 rebase, in-flight guard) is #756.
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
  {:else}
    <div class="board-toolbar">
      <!-- Seed stays reachable on an empty board — it is how you populate one. -->
      <button class="seed-btn" onclick={seed}>
        <i class="ti ti-seedling" aria-hidden="true"></i>
        Seed from manuscript
      </button>
      {#if !isEmpty}
        <UndoRedoControls
          canUndo={undoCtl.canUndo}
          canRedo={undoCtl.canRedo}
          undoTitle={undoCtl.undoTitle}
          redoTitle={undoCtl.redoTitle}
          announcement={undoCtl.announcement}
          onUndo={() => undoCtl.undo()}
          onRedo={() => undoCtl.redo()}
        />
      {/if}
    </div>
    {#if isEmpty}
      <p class="board-hint muted">No plotlines or cards yet. Seed cards from the manuscript, or add a plotline, to begin.</p>
    {:else}
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
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-2);
  }
  .seed-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    font-size: var(--fs-sm);
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    cursor: pointer;
  }
  .seed-btn:hover {
    background: var(--surface);
  }
  .seed-btn i {
    color: var(--text-3);
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
