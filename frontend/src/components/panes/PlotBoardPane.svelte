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

  onMount(() => {
    void refreshPlotBoard();
  });

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
</script>

<PlotEditor projection={$plotBoardStore} error={$plotBoardError} onRetry={() => void refreshPlotBoard()} />
