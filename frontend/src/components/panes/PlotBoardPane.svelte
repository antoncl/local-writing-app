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
  import { plotBoardStore, refreshPlotBoard } from "@/lib/stores/plotBoard";

  onMount(() => {
    void refreshPlotBoard();
  });
</script>

<PlotEditor projection={$plotBoardStore} />
