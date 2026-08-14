<!--
  PlotBoardPane — owns the plot board's DATA lifecycle so PlotEditor stays a pure
  projection→canvas renderer (prop-driven, unit-/mount-tested in isolation). It
  reads the plotBoard store and refreshes on mount, which covers the restore case:
  now that `plotEditor` is a known region (homed to the central editor group), a
  persisted board tab is re-created on reload with a null store and no menu opener
  to fetch for it. The store's in-flight guard collapses this refresh and the
  opener's into a single request on a normal menu open.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import PlotEditor from "./PlotEditor.svelte";
  import { plotBoardStore, plotBoardError, refreshPlotBoard } from "@/lib/stores/plotBoard";
  import { structureStore } from "@/lib/stores/structure";
  import { realizeLocations } from "@/lib/plot/realizeLocations";
  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
  import { promptEntriesStore } from "@/lib/stores/prompts";

  onMount(() => {
    void refreshPlotBoard();
  });

  // The whole-board AI diagnostic (ADR-0048 S7b): a board-level launch (not a
  // subject's ＋New menu — the board isn't an offer_on host), resolved by id like
  // Lore's brainstorm launcher and started with no subject binding — the prompt
  // reads the entire board via the `plot_context()` Jinja helper. Resolved from the
  // full roster (not the hidden-filtered discovery one) so a writer who hid the
  // built-in can still reach it from the board; null only if it's genuinely absent,
  // which hides the toolbar button.
  const DIAGNOSE_PLOT_PROMPT_ID = "builtin-diagnose-plot";
  let diagnosePrompt = $derived(
    $promptEntriesStore.find((p) => p.id === DIAGNOSE_PLOT_PROMPT_ID) ?? null,
  );
  function launchDiagnosis(): void {
    if (!diagnosePrompt) return;
    void chatSessions.openChatFromPromptEntry(diagnosePrompt, {}, null);
  }

  // Keep the board truthful when the manuscript structure changes while it's open
  // (#834). Card `sequence` (reveal order) and the container boxes are backend-DERIVED
  // from the manuscript, so a scene reorder/add/remove must refetch the projection —
  // otherwise the manuscript-order spine and the out-of-order causal warnings (Slice 7)
  // render against a stale reading order and never update. Scoped to while-open (this
  // pane only mounts then), matching the board's on-demand design. `primed` skips the
  // initial read so this fires only on a real change; the store's in-flight guard
  // collapses any overlap with the mount fetch above.
  let primed = false;
  $effect(() => {
    void $structureStore; // track manuscript changes
    if (!primed) {
      primed = true;
      return;
    }
    void refreshPlotBoard();
  });

  // The manuscript containers a card can be realized into (#879) — the "Realize scene"
  // location picker's roster. Derived here (this pane owns the structure store) so
  // PlotEditor stays a pure prop-driven renderer; tracks the same store the refetch
  // effect above watches, so a container added while the board is open appears at once.
  let locations = $derived(realizeLocations($structureStore));
</script>

<PlotEditor
  projection={$plotBoardStore}
  error={$plotBoardError}
  {locations}
  onRetry={() => void refreshPlotBoard()}
  onDiagnose={diagnosePrompt ? launchDiagnosis : undefined}
/>
