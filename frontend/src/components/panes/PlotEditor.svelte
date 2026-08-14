<!--
  PlotEditor — the plot board (ADR-0048 S7). A SvelteFlow canvas that renders the
  projection: cards laid out inside their manuscript container (act/chapter) boxes,
  coloured by plotline (Slice 4 — the free-flow, structure-container layout; the old
  plotline swimlanes are gone). S7b displayed it read-only; S7c (#760) makes the CARD
  layout editable — cards drag, positions persist to the board's opaque `layout`, and
  a drag is undoable via the shared ADR-0050 caretaker (Tier-1: layout only). Container
  boxes are non-interactive and derived (never dragged or stored). Content ops
  (realize/attach/seed = S7d) are intentful mutations OUTSIDE the caretaker per
  ADR-0048 binding decision 1 (an in-memory undo must never reverse a scene mint).

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
    boardIsEmpty,
    buildBoardNodes,
    overriddenNodePositions,
    projectionDataKey,
    readBoardPositions,
    readBoardSizes,
    reconcilePlotlineUiState,
    type PlotBoardNode,
  } from "@/lib/plot/plotBoardLayout";
  import { buildBoardEdges, EDGE_LAYERS, type EdgeLayer } from "@/lib/plot/plotBoardEdges";
  import { loadEdgeLayers, saveEdgeLayers, toggleEdgeLayer } from "@/lib/plot/edgeLayerPrefs";
  import { GraphUndoController } from "@/lib/graph/graphUndoController.svelte";
  import type { GraphPort } from "@/lib/graph/graphCommands";
  import { PlotUndoRecorder, defaultPlotCommandPort } from "@/lib/plot/plotCommands";
  import { keepsOwnFocus } from "@/lib/plot/boardFocus";
  import {
    savePlotBoardLayout,
    detachCardScene,
    saveCardSynopsis,
    reassignCardPlotline,
    linkCardBeat,
    unlinkCardBeat,
    linkCardCausal,
    unlinkCardCausal,
    setCardPageStatus,
    seedCardsFromManuscript,
    createCard,
    renameCard,
    deleteCard,
  } from "@/lib/stores/plotBoard";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import {
    plotlineEntriesStore,
    deletePlotline,
    createPlotlineOnBoard,
    instantiateTemplateOnBoard,
    savePlotlineEntry,
    getPlotlineEntry,
    plotlineReveal,
  } from "@/lib/stores/plotlines";
  import { plotTemplatesStore } from "@/lib/stores/plotTemplates";
  import UndoRedoControls from "@/components/UndoRedoControls.svelte";
  import ViewportFit from "@/components/editor/body/view/ViewportFit.svelte";
  import PlotCardNodeFlow from "./plot/PlotCardNodeFlow.svelte";
  import PlotContainerNodeFlow from "./plot/PlotContainerNodeFlow.svelte";
  import PlotPlotlineNode from "./plot/PlotPlotlineNode.svelte";
  import PlotCausalEdge from "./plot/PlotCausalEdge.svelte";
  import PlotTemplatePalette from "./plot/PlotTemplatePalette.svelte";
  import Popover from "@/components/chrome/Popover.svelte";
  import {
    PLOT_CARD_ACTIONS,
    type PlotCardActions,
    PLOT_EDGE_ACTIONS,
    type PlotEdgeActions,
  } from "./plot/plotCardActions";
  import { PLOT_PLOTLINE_ACTIONS, type PlotPlotlineActions } from "./plot/plotPlotlineActions";
  import { PLOT_CONTAINER_ACTIONS, type PlotContainerActions } from "./plot/plotContainerActions";
  import type { BoardSize, BoardXY, PlotBoardProjection } from "@/lib/types";

  // The board's read model, fetched by the opener / PlotBoardPane into the store.
  // Null until the first refresh resolves. `error` distinguishes a FAILED initial
  // load from a still-loading one (#756) — with a projection null and an error set,
  // the pane shows a retryable error state instead of a permanent "Loading…";
  // `onRetry` re-runs the fetch. Both are inert once a projection is present.
  let {
    projection,
    error = null,
    onRetry,
  }: {
    projection: PlotBoardProjection | null;
    error?: string | null;
    onRetry?: () => void;
  } = $props();

  // Coalesce a drag's position churn into one save on release.
  const SAVE_DEBOUNCE_MS = 600;

  // Svelte Flow's arrays, bound to the canvas. Edges stay empty in S7c (card→
  // scene/plotline wires are S7f, and don't render headless anyway).
  let flowNodes = $state<PlotBoardNode[]>([]);
  let flowEdges = $state<Edge[]>([]);
  // Optimistic base for the next layout save, and a snapshot guard so the persist
  // effect fires only on a real change — never on the just-loaded state. The snapshot
  // covers the WHOLE persisted layout (card/plotline positions + container sizes), so a
  // resize (#878) triggers a save just as a drag does.
  let revision = $state("");
  let lastSavedLayout = $state("");
  // Per-container manual sizes (#878), keyed by container id: seeded from the saved
  // layout on each rebuild, updated when a container's resize handle is released.
  // Reactive so the autosave effect re-runs on a resize, and passed to buildBoardNodes
  // so the box (and its member cards' extent) grows to at least the stored size.
  let containerSizes = $state<Record<string, BoardSize>>({});
  // True while a card is dragging, so the debounce waits for release (one save
  // per gesture), mirroring ViewBodyView's autosave.
  let dragging = $state(false);
  // The projection DATA-key currently hydrated into flowNodes — a plain (non-reactive)
  // local. The rehydrate effect compares the incoming projection's data-key against it:
  // a re-open with identical data (same key) doesn't rebuild the canvas or discard an
  // in-progress layout edit, but a content op (a card field changed → different key)
  // does — so a reassigned card reflows. Keyed on data, not board_id (S7c), because a
  // reassignment keeps the same board.
  let loadedDataKey = "";
  // Which cards carry an explicit position override (the sparse model, S7d reflow):
  // seeded from the saved layout on each rebuild, grown as the writer drags. Plain /
  // non-reactive — read at persist time (the effect already re-runs on flowNodes) and
  // at drag time, never a reactive dep.
  let overriddenIds = new Set<string>();

  // The board's undo history (ADR-0050): the shared caretaker via GraphUndoController,
  // its own instance per §3, replaying through a port over our rune arrays. Drags
  // record through the graph port (in-memory position swaps); content ops record
  // through the recorder below onto the SAME caretaker (ADR-0053 §7) — one stack, one
  // Ctrl+Z, one button, whole-board undo.
  const graphPort: GraphPort<PlotBoardNode, Edge> = {
    getNodes: () => flowNodes,
    setNodes: (n) => (flowNodes = n),
    getEdges: () => flowEdges,
    setEdges: (e) => (flowEdges = e),
  };
  const undoCtl = new GraphUndoController<PlotBoardNode, Edge>(graphPort);
  // Records the async content commands (create/delete/edit of cards + plotlines,
  // seed) onto the shared caretaker. It captures whole-entry before/after snapshots
  // around each forward op and reads the live projection to find a delete's referrers
  // (ADR-0053 §7). Realize is NOT recorded here — its scene-file mint is S6b.
  const undoRecorder = new PlotUndoRecorder(
    defaultPlotCommandPort(),
    (command) => undoCtl.record(command),
    () => projection,
    // Queue a fresh content op behind an in-flight undo/redo (#909) so it can't
    // hit record() mid-replay; near-instant once the batched undo is fast.
    () => undoCtl.whenIdle(),
  );

  // Per-card actions handed to PlotCardNode via context (ADR-0048 S7d). Content ops
  // are intentful backend mutations OUTSIDE the layout caretaker (binding decision 1)
  // — realize/detach never enter the Ctrl+Z history. Each store helper refetches the
  // projection so the board re-projects the changed card (visible reflow is the
  // rehydrate-on-content-op wiring in the reflow slice).
  // Per-plotline FOCUS (ADR-0053 §6): which plotline's thread is lit across the whole
  // board (its beat-sequence edges emphasised, every other edge + non-participating card
  // dimmed), or null. Owned here like `expandedPlotlineId`; toggled from a plotline node,
  // cleared on a canvas-background click. A card reads it through the actions getter to
  // decide whether it recedes (a getter so it tracks this reactive state fresh).
  let focusedPlotlineId = $state<string | null>(null);

  setContext<PlotCardActions>(PLOT_CARD_ACTIONS, {
    onOpen: (cardId) => void editorPanes.openPlotCard(cardId),
    // Realize mints a scene FILE, recorded via the recorder (S6b): undo deletes that
    // scene when the card is its sole referent (suppressible confirm if it holds prose),
    // redo re-mints. Default placement (parentId null → the backend's first container).
    onRealize: (cardId) => void undoRecorder.realize(cardId, null),
    // Every other card op is a whole-card before/after edit recorded onto the shared
    // caretaker (§7). Detach only toggles the `scene` ref (no file touched), so it IS
    // undoable as a plain field edit. Each store helper still refetches the projection,
    // so the board re-projects the changed card.
    onDetach: (cardId) => void undoRecorder.cardEdit(cardId, "detach scene", () => detachCardScene(cardId)),
    onEditTitle: (cardId, title) => void undoRecorder.cardEdit(cardId, "rename card", () => renameCard(cardId, title)),
    onEditSynopsis: (cardId, synopsis) =>
      void undoRecorder.cardEdit(cardId, "edit synopsis", () => saveCardSynopsis(cardId, synopsis)),
    // Reassign the card's plotline ("" → Unassigned). A content op → the projection's
    // data-key changes → the board rebuilds and the card re-colours. A getter so the
    // submenu reads the current plotlines fresh from the projection (the designerContext
    // pattern).
    onSetPlotline: (cardId, plotlineId) =>
      void undoRecorder.cardEdit(cardId, "reassign plotline", () => reassignCardPlotline(cardId, plotlineId)),
    // Link a beat dropped from a plotline node (#824); unlink via the badge ×. A beat
    // drop can also adopt the card's primary (#863), which the whole-card before/after
    // flip reverses along with the link.
    onLinkBeat: (cardId, instance, beatId) =>
      void undoRecorder.cardEdit(cardId, "link beat", () => linkCardBeat(cardId, instance, beatId)),
    onUnlinkBeat: (cardId, instance, beatId) =>
      void undoRecorder.cardEdit(cardId, "unlink beat", () => unlinkCardBeat(cardId, instance, beatId)),
    // Declare an unattached card off_page vs unwritten (Slice 5b). on_page is derived
    // from the scene, so it is never set here.
    onSetPageStatus: (cardId, status) =>
      void undoRecorder.cardEdit(cardId, "set page status", () => setCardPageStatus(cardId, status)),
    onDelete: (cardId) => removeCard(cardId),
    get plotlines() {
      return projection?.plotlines ?? [];
    },
    // The focused plotline (S5b) — a card that is neither on this thread nor fulfilling
    // one of its beats dims. A getter so the card tracks it reactively.
    get focusedPlotlineId() {
      return focusedPlotlineId;
    },
  });

  // On-node plotline editing (ADR-0053 §3). The board owns the ephemeral "which
  // plotline is expanded" — only one at a time, cleared on a canvas-background click
  // (onpaneclick below). NOT cleared on a board rebuild: a save refreshes the board,
  // and collapsing the editor on every save would make editing impossible. A getter so
  // the node reads it fresh (the plotCardActions.plotlines idiom).
  let expandedPlotlineId = $state<string | null>(null);
  setContext<PlotPlotlineActions>(PLOT_PLOTLINE_ACTIONS, {
    get expandedId() {
      return expandedPlotlineId;
    },
    toggleExpanded: (id) => {
      expandedPlotlineId = expandedPlotlineId === id ? null : id;
    },
    get focusedId() {
      return focusedPlotlineId;
    },
    toggleFocus: (id) => {
      focusedPlotlineId = focusedPlotlineId === id ? null : id;
    },
    loadPlotline: (id) => getPlotlineEntry(id),
    // Persist an edit and refresh the board + rail. Surface a failure in the app banner
    // (the node stays usable) AND rethrow so the node resyncs its revision from the
    // server rather than looping 409s.
    save: async (entry) => {
      try {
        // Record a whole-plotline before/after edit onto the shared caretaker (§7);
        // returns the saved entry so the node resyncs its revision.
        return await undoRecorder.plotlineEdit(entry.id, "edit plotline", () => savePlotlineEntry(entry));
      } catch (e) {
        editorPanes.setError(e instanceof Error ? e.message : "Couldn't save the plotline.");
        throw e;
      }
    },
    onDelete: (id) => removePlotline(id),
    // The escape hatch (ADR-0053 §3): open the plotline in a full NodeEditor pane for
    // roomy beat work. Mirrors the card provider's `onOpen`/`openPlotCard` (line above).
    // On-node inline editing stays the default surface.
    onOpenInEditor: (id) => void editorPanes.openPlotline(id),
  });

  // Container resize (#878). A container box carries no position (its origin is always
  // derived), but a resize handle gives it a manual SIZE, pinned in `containerSizes`
  // keyed by container id. A new-object assign (not a mutate) triggers the reactive
  // autosave effect; the next rebuild reads it back through buildBoardNodes so the box
  // holds the size. Deliberately outside the undo caretaker (drags are Tier-1, a resize
  // is a coarser layout tweak) — the same call is the store's only writer of `sizes`.
  setContext<PlotContainerActions>(PLOT_CONTAINER_ACTIONS, {
    onResize: (containerId, size) => {
      containerSizes = { ...containerSizes, [containerId]: size };
    },
  });

  // A card's `plotline` backlink no longer opens an editor pane — it reveals the
  // plotline on the board (plotlineReveal signal). When one arrives, expand that node
  // if it's on this board, then clear the one-shot. Reading the signal first means a
  // drag frame (flowNodes churn) can't retrigger this once the signal is null.
  $effect(() => {
    const revealId = $plotlineReveal;
    if (!revealId) return;
    // Wait for the board to load before deciding — a reveal that arrives while the
    // board is still opening (its pane was closed) must not be dropped. Once the
    // projection is in, expand the node if it's here; either way the one-shot clears
    // (a stale id — a plotline on another project — is simply not on this board).
    if (!projection) return;
    if (flowNodes.some((n) => n.type === "plotPlotline" && n.id === revealId)) {
      expandedPlotlineId = revealId;
    }
    plotlineReveal.set(null);
  });

  // Self-heal the ephemeral focus/expand state against the live board (#928). A plotline
  // can be deleted from its node's Delete OR the full-pane escape hatch's tab; only the
  // node path clears these ids directly, so a pane delete could leave a focused/expanded
  // id dangling on a thread that's gone — the board stays dimmed with no eye left to clear
  // it. Reconcile against the refreshed projection (which changes per refetch, not per
  // drag frame like flowNodes); a null (loading) projection is left untouched.
  $effect(() => {
    const healed = reconcilePlotlineUiState(projection, { focusedPlotlineId, expandedPlotlineId });
    if (healed.focusedPlotlineId !== focusedPlotlineId) focusedPlotlineId = healed.focusedPlotlineId;
    if (healed.expandedPlotlineId !== expandedPlotlineId) expandedPlotlineId = healed.expandedPlotlineId;
  });

  // Delete a card from the board (#860). Confirmed (destructive, app dialog) — the
  // card is gone from the project; its scene, if any, is left untouched (a scene can
  // outlive its card). Distinct from Detach, which only clears the scene ref.
  function removeCard(id: string): void {
    const card = projection?.cards.find((c) => c.id === id);
    confirmService.request({
      title: "Delete card",
      message: `Delete ${card?.title ? `“${card.title}”` : "this card"}? This removes the card from the project. Its scene, if any, is left untouched.`,
      confirmLabel: "Delete card",
      destructive: true,
      onConfirm: async () => {
        // Recorded onto the caretaker (§7): captures the card + its inbound causal
        // referrers, deletes, so Ctrl+Z restores the card and reconnects those edges.
        await undoRecorder.deleteCard(id, () => deleteCard(id));
        // Close a NodeEditor pane open on this card ("Open card"): the node is gone,
        // so the pane would 404 on its next save. Mirrors editorPaneDelete's own
        // post-delete tearDown — find by document id, force-close (no save prompt).
        const openPane = editorPanes.panes.find((p) => p.document?.id === id);
        if (openPane) editorPanes.tearDown(openPane.id);
      },
    });
  }

  // New card (#793): the board's direct-authoring entry point — create an unattached
  // card that appears on the board (homeless) where the writer names + describes it
  // inline. Deliberately does NOT open the NodeEditor (#798): staying on the board is
  // the point; the full editor is a choice (the card's ⋮ → "Open card"). No confirm: a
  // single card is cheap and reversible (delete). `creating` guards against a
  // double-click minting two cards, and surfaces a create failure in the app error
  // banner instead of a silent unhandled rejection.
  let creating = $state(false);
  async function newCard(): Promise<void> {
    if (creating) return;
    creating = true;
    try {
      await undoRecorder.createCard(() => createCard("New card"));
    } catch (e) {
      editorPanes.setError(e instanceof Error ? e.message : "Could not create the card.");
    } finally {
      creating = false;
    }
  }

  // Board-native plotline create (ADR-0053 §3): mint an empty plotline and expand its
  // new node so the writer names + beats it out in place — no editor pane. `creatingPlotline`
  // guards a double-click, and surfaces a failure in the banner.
  let creatingPlotline = $state(false);
  async function newPlotline(): Promise<void> {
    if (creatingPlotline) return;
    creatingPlotline = true;
    try {
      expandedPlotlineId = await undoRecorder.createPlotline(() => createPlotlineOnBoard());
      // Confirm the create — the new node may land off-screen (viewport unchanged),
      // where the expand alone would read as nothing happening.
      editorPanes.setStatus("Created plotline");
    } catch (e) {
      editorPanes.setError(e instanceof Error ? e.message : "Could not create the plotline.");
    } finally {
      creatingPlotline = false;
    }
  }

  // The template palette (ADR-0053 §2) — the board's rail is now the SOURCE you spawn
  // plotlines from (the Plotlines rail is retired: a plotline is a node on the canvas).
  // `plotTemplatesStore` is loaded on project open (the fan-out), so the palette has its
  // roster whether or not the TopBar Plot-templates pane was ever opened.
  let paletteOpen = $state(false);
  let templates = $derived($plotTemplatesStore);
  let plotlines = $derived($plotlineEntriesStore);

  // Instantiate a template → a plotline node, expanded for editing (the createPlotlineOnBoard
  // shape). The Empty tile is `newPlotline` (an ad-hoc, beat-less plotline).
  async function instantiateTemplate(id: string): Promise<void> {
    if (creatingPlotline) return; // shares newPlotline's guard — one mint per gesture
    creatingPlotline = true;
    try {
      expandedPlotlineId = await undoRecorder.createPlotline(() => instantiateTemplateOnBoard(id));
      editorPanes.setStatus("Created plotline from template");
    } catch (e) {
      editorPanes.setError(e instanceof Error ? e.message : "Could not instantiate the template.");
    } finally {
      creatingPlotline = false;
    }
  }

  // Cloning a Library template, and editing / deleting an owned clone, live on the Plot
  // Templates pane (#916), not the board palette — the palette is a spawn source. Its
  // former cloneTemplate / removeTemplate handlers went with that chrome.

  // Delete a plotline — the node's "Delete plotline" (the retired rail used to own this).
  // Confirmed; cards on the thread revert to Unassigned. Collapse the editor if it was open.
  function removePlotline(id: string): void {
    const line = plotlines.find((p) => p.id === id);
    confirmService.request({
      title: "Remove plotline",
      message: `Remove ${line?.title ? `“${line.title}”` : "this plotline"}? Cards on it become Unassigned (their tint clears); their prose is untouched.`,
      confirmLabel: "Remove plotline",
      destructive: true,
      onConfirm: async () => {
        if (expandedPlotlineId === id) expandedPlotlineId = null;
        // Clear focus too if this was the focused thread — else focus strands on a dead
        // id and the whole board dims (no beat:<id>: edges, its cards now Unassigned)
        // with the eye that would toggle it off gone with the node.
        if (focusedPlotlineId === id) focusedPlotlineId = null;
        // Recorded (§7): captures the plotline + every card on its thread (primary or a
        // beat), deletes, so Ctrl+Z restores it "with its beats and every card badge
        // that pointed at it."
        await undoRecorder.deletePlotline(id, () => deletePlotline(id));
      },
    });
  }

  // Edge layers (ADR-0048 S7 Slice 6a): the board's other dimensions, drawn as
  // toggleable card→card edges. Which layers are on is a viewing mode → localStorage
  // (loaded once here), default empty so the board stays quiet until a writer opens
  // one. `layersOpen` drives the toolbar popover; `layersTrigger` is its refocus
  // anchor. Labels + hints live here (presentation); the canonical layer list and
  // the pure edge-builder live in `lib/plot`.
  let activeLayers = $state<Set<EdgeLayer>>(loadEdgeLayers());
  let layersOpen = $state(false);
  let layersTrigger = $state<HTMLElement | null>(null);
  const LAYER_META: Record<EdgeLayer, { label: string; hint: string }> = {
    manuscript: { label: "Manuscript order", hint: "The reveal-order spine — cards in the order their scenes are read." },
    beats: { label: "Beat sequence", hint: "Cards that share a beat, in the order they advance through it." },
    causal: { label: "Causal", hint: "The “leads to” edges you draw — one card causing another." },
  };

  function toggleLayer(layer: EdgeLayer): void {
    activeLayers = toggleEdgeLayer(activeLayers, layer);
    saveEdgeLayers(activeLayers);
  }

  // Seed-from-manuscript (ADR-0048 §S5): bulk, idempotent. Confirmed because it can
  // mint many cards at once, though re-running it is safe (already-carded scenes skip).
  function seed(): void {
    confirmService.request({
      title: "Seed from manuscript",
      message: "Create one card per scene that isn't carded yet, each attached to its scene. Safe to run again — already-carded scenes are skipped.",
      confirmLabel: "Seed cards",
      destructive: false,
      onConfirm: async () => {
        // Recorded as one step (§7): undo deletes the whole seeded batch, redo re-mints
        // it under the same ids. Re-running seed with nothing new records nothing.
        await undoRecorder.seed(() => seedCardsFromManuscript());
      },
    });
  }

  const nodeTypes = { plotCard: PlotCardNodeFlow, plotContainer: PlotContainerNodeFlow, plotPlotline: PlotPlotlineNode };
  // Authored causal edges render via PlotCausalEdge (a hover-× to remove the link);
  // derived edges keep the default renderer.
  const edgeTypes = { causal: PlotCausalEdge };
  setContext<PlotEdgeActions>(PLOT_EDGE_ACTIONS, {
    onUnlinkCausal: (source, target) =>
      void undoRecorder.cardEdit(source, "unlink causal", () => unlinkCardCausal(source, target)),
  });
  // Svelte Flow ships light-only chrome; drive its theme from the app's.
  let colorMode = $derived($themePreference as ColorMode);

  // Empty (show the hint, hide the canvas) only when the board has neither cards nor
  // plotlines — a plotline is a first-class node now (ADR-0053), so a plotline-only board
  // must still render. Pure predicate (unit-tested) since the canvas isn't headless.
  let isEmpty = $derived(!!projection && boardIsEmpty(projection));

  // (Re)hydrate from a fetched projection. Guarded on the DATA-key so it fires once
  // per data change, not per projection reference: a layout save doesn't touch the
  // store, but the opener / PlotBoardPane can re-set an equal projection (same key →
  // skip, so an in-progress edit survives), while a content op changes a card field
  // (different key → rebuild, so a re-homed un-pinned card reflows into its new
  // container). `overriddenIds` reseeds from the saved layout each rebuild — the sparse
  // set an un-pinned card is absent from, so buildBoardNodes derives its slot.
  // The snapshot reads the LOCAL built array, never the reactive `flowNodes` — reading
  // flowNodes back would subscribe this effect to xyflow's in-place position mutations,
  // so every drag would re-run it and snap the card back. $effect.PRE so nodes are
  // present before <SvelteFlow> mounts (projection null→set).
  $effect.pre(() => {
    if (!projection) {
      loadedDataKey = "";
      overriddenIds = new Set();
      flowNodes = [];
      dragging = false;
      return;
    }
    const key = projectionDataKey(projection);
    if (key === loadedDataKey) return;
    loadedDataKey = key;
    const saved = readBoardPositions(projection.layout);
    overriddenIds = new Set(Object.keys(saved));
    // Seed container sizes from a LOCAL const and pass it straight to buildBoardNodes:
    // the assign to `containerSizes` doesn't read it back, so this effect never
    // subscribes to its own resize writes (which would re-run and, guarded by the
    // data-key, no-op anyway).
    const savedSizes = readBoardSizes(projection.layout);
    containerSizes = savedSizes;
    const nodes = buildBoardNodes(projection, saved, savedSizes);
    flowNodes = nodes;
    revision = projection.board_revision;
    // Snapshot from the local `nodes` (not reactive flowNodes) so a never-touched
    // board doesn't save on open and this effect stays subscribed to `projection` only.
    lastSavedLayout = JSON.stringify({ positions: overriddenNodePositions(nodes, overriddenIds), sizes: savedSizes });
    dragging = false;
    undoCtl.reset();
  });

  // Rebuild the edge layers whenever the projection or the active layer set changes
  // (Slice 6a). Edges are DERIVED and read-only (the board is not connectable), so
  // this just reassigns `flowEdges` — they never enter the layout persistence or the
  // undo caretaker (only card drags do). Reads projection + activeLayers only (never
  // flowEdges back), so it can't loop with SvelteFlow's own writes.
  $effect(() => {
    flowEdges = projection ? buildBoardEdges(projection, activeLayers, focusedPlotlineId) : [];
  });

  // Which beats are already placed on some card — the beat palette marks these (#824).
  let usedBeatKeys = $derived(
    new Set((projection?.cards ?? []).flatMap((c) => c.beats.map((b) => `${b.plotline_id}:${b.beat_id}`))),
  );

  // Causal ("leads to") edges are authored by dragging a wire between card handles
  // (#824). onconnect adds the link (source leads to target); refetch → the derived
  // edge $effect above redraws it. Only causal edges are selectable/deletable
  // (buildBoardEdges marks them), so a Delete on a selected edge removes just that link.
  // Keyboard-reach fix (ADR-0053 §7): plot cards are `selectable:false`, so a drag or
  // a card click lands focus on <body>, never inside `.plot-board`, and the board's
  // bubbling Ctrl+Z (below) never fires (the Undo BUTTON, calling undo() directly, has
  // always worked). `tabindex="-1"` makes the section programmatically focusable; we
  // focus it on a board pointerdown and on drag release — SKIPPING pointerdowns on an
  // editable / interactive target so an inline title / synopsis / plotline input keeps
  // focus for typing (and native Ctrl+Z stays with that input).
  let boardEl = $state<HTMLElement | null>(null);
  function focusBoardForUndo(event: PointerEvent): void {
    if (keepsOwnFocus(event.target)) return; // an input/control keeps focus for typing
    boardEl?.focus({ preventScroll: true });
  }

  function onConnectCausal(connection: { source: string; target: string }): void {
    if (connection.source && connection.target)
      void undoRecorder.cardEdit(connection.source, "link causal", () =>
        linkCardCausal(connection.source, connection.target),
      );
  }
  function onDeleteCausal(params: { edges: Edge[] }): void {
    for (const edge of params.edges) {
      if (edge.source && edge.target)
        void undoRecorder.cardEdit(edge.source, "unlink causal", () => unlinkCardCausal(edge.source, edge.target));
    }
  }

  // Autosave the layout: skip while dragging (coalesce the gesture) and when nothing
  // changed, else debounce a PUT. The projection/dragging guard runs FIRST so a drag
  // doesn't re-serialize the whole board every frame (ViewBodyView's pattern). Only
  // overridden (dragged/pinned) cards persist — the sparse model — alongside the
  // container sizes (#878; a resize updates `containerSizes`, re-running this effect).
  // Undo/redo mutate the same positions and persist through here too; a load matches
  // the snapshot, so it never writes. A resize is not `dragging` (that flag is the node
  // drag), so it flushes without the coalesce wait — one save on handle release.
  $effect(() => {
    if (!projection || dragging) return;
    const positions = overriddenNodePositions(flowNodes, overriddenIds);
    const sizes = containerSizes;
    const serialized = JSON.stringify({ positions, sizes });
    if (serialized === lastSavedLayout) return;
    const handle = setTimeout(() => void persist(positions, sizes, serialized), SAVE_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  });

  // Flush a pending (debounced) layout change when the pane unmounts, so closing the
  // board right after a drag / resize doesn't lose it. Best-effort: the PUT is fired,
  // not awaited (the fetch outlives the component). Project-switch / reload flushing is
  // the deferred save-state machine (#756).
  onDestroy(() => {
    if (!projection || dragging) return;
    const positions = overriddenNodePositions(flowNodes, overriddenIds);
    const sizes = containerSizes;
    const serialized = JSON.stringify({ positions, sizes });
    if (serialized !== lastSavedLayout) void persist(positions, sizes, serialized);
  });

  async function persist(
    positions: Record<string, BoardXY>,
    sizes: Record<string, BoardSize>,
    serialized: string,
  ): Promise<void> {
    try {
      revision = await savePlotBoardLayout({ positions, sizes }, revision);
      lastSavedLayout = serialized;
    } catch {
      // Leave the guard unadvanced so the next change retries. The surfaced
      // load/error state machine (409 rebase, in-flight guard) is #756.
    }
  }
</script>

<!-- The keydown is board-scoped (ADR-0050 §3): it rides BUBBLING from whatever
     focusable element inside has focus (canvas, controls, the section itself), so a
     chord in another pane can never reach this caretaker. `tabindex="-1"` (ADR-0053
     §7) makes the section a programmatic focus target — NOT a tab stop (negative
     index), so no ghost stop — reached via focusBoardForUndo on pointerdown + on
     drag release, since cards are `selectable:false` and never focus the board
     themselves. -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section
  class="plot-board"
  aria-label="Plot board"
  tabindex="-1"
  bind:this={boardEl}
  onkeydown={undoCtl.handleKeydown}
  onpointerdown={focusBoardForUndo}
>
  {#if !projection}
    {#if error}
      <!-- A failed initial load / restore. Distinct from the loading blank so a
           fetch error isn't a permanent "Loading…" (#756); Retry re-runs it. -->
      <div class="board-status" role="alert">
        <p class="board-hint muted">Couldn't load the board.</p>
        <p class="board-error-detail">{error}</p>
        {#if onRetry}
          <button class="board-btn" onclick={onRetry}>Retry</button>
        {/if}
      </div>
    {:else}
      <p class="board-hint muted">Loading the board…</p>
    {/if}
  {:else}
    {#if error}
      <!-- A background / post-mutation refresh failed while the board is already
           shown (#756). Don't blank the board — keep the (possibly stale) view — but
           don't leave the failure silent either: a slim strip surfaces it with Retry.
           `refreshPlotBoard` clears the error on its next attempt, so a successful
           Retry (or any later refresh) removes this. -->
      <div class="board-refresh-error" role="alert">
        <span>Couldn't refresh the board — it may be out of date.</span>
        {#if onRetry}
          <button class="board-btn" onclick={onRetry}>Retry</button>
        {/if}
      </div>
    {/if}
    <div class="board-toolbar">
      <!-- Both stay reachable on an empty board — they are how you populate one:
           New card authors one directly; Seed bulk-mints from the manuscript. -->
      <div class="toolbar-actions">
        <button
          class="board-btn"
          class:active={paletteOpen}
          aria-pressed={paletteOpen}
          onclick={() => (paletteOpen = !paletteOpen)}
        >
          <i class="ti ti-palette" aria-hidden="true"></i>
          Templates{templates.length ? ` (${templates.length})` : ""}
        </button>
        <!-- Edge layers (Slice 6a): a popover of the board's toggleable dimensions.
             `layers-wrap` is the position:relative anchor Popover drops from. -->
        <div class="layers-wrap">
          <button
            class="board-btn"
            class:active={activeLayers.size > 0}
            aria-haspopup="menu"
            aria-expanded={layersOpen}
            bind:this={layersTrigger}
            onclick={() => (layersOpen = !layersOpen)}
          >
            <i class="ti ti-versions" aria-hidden="true"></i>
            Layers{activeLayers.size ? ` (${activeLayers.size})` : ""}
          </button>
          <Popover
            bind:open={layersOpen}
            triggerEl={layersTrigger}
            label="Edge layers"
            minWidth="260px"
            padding="6px"
            gap="2px"
          >
            {#each EDGE_LAYERS as layer (layer)}
              <button
                class="layer-item"
                role="menuitemcheckbox"
                aria-checked={activeLayers.has(layer)}
                onclick={() => toggleLayer(layer)}
              >
                <i
                  class="ti layer-check {activeLayers.has(layer) ? 'ti-check' : ''}"
                  aria-hidden="true"
                ></i>
                <span class="layer-text">
                  <span class="layer-label">{LAYER_META[layer].label}</span>
                  <span class="layer-hint">{LAYER_META[layer].hint}</span>
                </span>
              </button>
            {/each}
          </Popover>
        </div>
        <button class="board-btn" onclick={newCard} disabled={creating}>
          <i class="ti ti-plus" aria-hidden="true"></i>
          New card
        </button>
        <button class="board-btn" onclick={seed}>
          <i class="ti ti-seedling" aria-hidden="true"></i>
          Seed from manuscript
        </button>
      </div>
      {#if !isEmpty}
        <!-- Whole-board undo (ADR-0053 §7): the caretaker now covers content ops as
             well as drags, so the layout-only scope label is gone — it is a plain
             "Undo". Disabled while an async inverse call is in flight (busy) so a
             mashed control can't race two reversals. -->
        <div class="undo-group">
          <UndoRedoControls
            canUndo={undoCtl.canUndo && !undoCtl.busy}
            canRedo={undoCtl.canRedo && !undoCtl.busy}
            undoTitle={undoCtl.undoTitle}
            redoTitle={undoCtl.redoTitle}
            announcement={undoCtl.announcement}
            onUndo={() => undoCtl.undo()}
            onRedo={() => undoCtl.redo()}
          />
        </div>
      {/if}
    </div>
    <div class="board-main">
      {#if paletteOpen}
        <PlotTemplatePalette
          entries={templates}
          onInstantiate={(id) => void instantiateTemplate(id)}
          onEmpty={() => void newPlotline()}
        />
      {/if}
      <div class="board-body">
    {#if isEmpty}
      <p class="board-hint muted">Nothing here yet. Seed cards from the manuscript or add one, or open Templates to start a plotline.</p>
    {:else}
      <div class="board-canvas">
      <SvelteFlow
        bind:nodes={flowNodes}
        bind:edges={flowEdges}
        {nodeTypes}
        {edgeTypes}
        {colorMode}
        nodesConnectable={true}
        elementsSelectable={true}
        onconnect={onConnectCausal}
        ondelete={onDeleteCausal}
        onpaneclick={() => {
          expandedPlotlineId = null;
          focusedPlotlineId = null;
        }}
        onnodedragstart={({ nodes }) => {
          dragging = true;
          undoCtl.dragStart(nodes);
        }}
        onnodedragstop={({ nodes }) => {
          dragging = false;
          undoCtl.dragStop(nodes);
          // Return focus to the board (§7): the drag landed it on <body> (cards are
          // selectable:false), so without this the very Ctrl+Z that would undo the
          // drag wouldn't reach the caretaker.
          boardEl?.focus({ preventScroll: true });
          // A dragged card or plotline node becomes overridden (pinned): it now
          // persists and keeps its spot instead of reflowing to its derived slot.
          for (const node of nodes) {
            if (node.type === "plotCard" || node.type === "plotPlotline") overriddenIds.add(node.id);
          }
        }}
        minZoom={0.2}
      >
        <!-- §G (design language): a flat --board surface, no dotted <Background/>. -->
        <Controls showLock={false} />
        <!-- Frame the board ONCE, when it first loads (#798). Triggering on `board_id`
             (stable across refetches) rather than the whole `projection` means a content
             op — adding/editing a card — no longer reframes the canvas out from under the
             writer; the viewport stays where they left it. `minZoom` clamps the initial
             fit so a spread-out board can't shrink to the canvas floor and read as empty. -->
        <ViewportFit trigger={projection?.board_id} options={{ padding: 0.2, maxZoom: 1, minZoom: 0.5 }} />
      </SvelteFlow>
      </div>
    {/if}
      </div>
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
  /* The section is a programmatic focus target for keyboard undo (§7), not a
     user-operable control — so no focus ring around the whole board. */
  .plot-board:focus {
    outline: none;
  }
  .board-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-2);
  }
  .toolbar-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .undo-group {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .board-btn {
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
  .board-btn:hover:not(:disabled) {
    background: var(--surface);
  }
  .board-btn.active {
    background: var(--surface);
    border-color: var(--accent);
    color: var(--text);
  }
  .board-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .board-btn i {
    color: var(--text-3);
  }
  /* Rail + canvas sit in a row below the toolbar; the rail is a fixed-width column,
     the body takes the rest (canvas or the empty-cards hint). */
  .board-main {
    flex: 1;
    min-height: 0;
    display: flex;
    align-items: stretch;
  }
  .board-body {
    flex: 1;
    min-width: 0;
    min-height: 0;
  }
  .board-canvas {
    width: 100%;
    height: 100%;
  }
  .board-hint {
    padding: 16px;
  }
  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
  /* The failed-load state (#756): the hint, the error detail, and a Retry button
     stacked at the top-left, matching the loading blank's placement. */
  .board-status {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding: 16px;
  }
  .board-status .board-hint {
    padding: 0;
  }
  .board-error-detail {
    margin: 0;
    max-width: 60ch;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  /* The stale-refresh strip (#756): a quiet full-width bar above a still-shown board
     when a background / post-mutation refresh failed. Neutral, not alarming — the
     board is usable, just possibly out of date. */
  .board-refresh-error {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 12px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    color: var(--text-2);
    font-size: var(--fs-sm);
  }

  /* The Layers popover (Slice 6a). `layers-wrap` is the position:relative anchor
     the in-flow Popover drops from; the rows carry their own scope here (Popover
     owns only the shell). */
  .layers-wrap {
    position: relative;
  }
  .layer-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    width: 100%;
    padding: 6px 8px;
    text-align: left;
    color: var(--text);
    background: none;
    border: none;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .layer-item:hover {
    background: var(--panel);
  }
  .layer-check {
    flex: 0 0 auto;
    width: 16px;
    margin-top: 2px;
    font-size: var(--fs-sm);
    color: var(--accent);
  }
  .layer-text {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .layer-label {
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .layer-hint {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  /* Edge layers (Slice 6a/6b). DERIVED edges read QUIET — thin, low-opacity, dashed,
     no arrowhead (the layout already carries reading direction). Two neutral greys
     told apart by dash density. The AUTHORED causal layer (6b) reads STRONGER: a
     solid accent stroke at full opacity + an arrowhead (the marker, coloured accent
     in the edge builder), because its direction is the writer's assertion, not an
     artefact of layout. Token colours only, so the style-token guard stays green.
     Scoped :global because SvelteFlow owns the edge DOM. */
  .plot-board :global(.svelte-flow__edge-path) {
    stroke-width: 1.5;
    stroke-opacity: 0.55;
  }
  .plot-board :global(.svelte-flow__edge.manuscript-edge .svelte-flow__edge-path) {
    stroke: var(--text-3);
    stroke-dasharray: 2 4;
  }
  .plot-board :global(.svelte-flow__edge.beat-edge .svelte-flow__edge-path) {
    stroke: var(--text-2);
    stroke-dasharray: 7 4;
  }
  .plot-board :global(.svelte-flow__edge.causal-edge .svelte-flow__edge-path) {
    stroke: var(--accent);
    stroke-opacity: 1;
  }
  /* Slice 7 diagnostic — a causal edge whose cause is revealed AFTER its effect
     (`buildBoardEdges` tags it `.causal-warn`) recolours to the `--warn` amber; the
     arrowhead is recoloured to match in the edge builder, and PlotCausalEdge adds a
     ⚠ with the why/what-to-do tooltip. Declared after `.causal-edge` so it wins. */
  .plot-board :global(.svelte-flow__edge.causal-warn .svelte-flow__edge-path) {
    stroke: var(--warn);
  }

  /* Per-plotline FOCUS (ADR-0053 §6, S5b; #911). Focus is a CARD treatment — the
     thread's cards are outlined (lit) in PlotCardNode and the rest dimmed; every EDGE
     just recedes so the outlined thread pops. buildBoardEdges tags every edge
     `edge-dimmed` when a plotline is focused. Declared AFTER the layer rules so the
     same-specificity dim wins by source order. Token colours only. */
  .plot-board :global(.svelte-flow__edge.edge-dimmed .svelte-flow__edge-path) {
    stroke-opacity: 0.12;
  }
</style>
