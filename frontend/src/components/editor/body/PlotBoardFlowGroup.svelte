<script lang="ts">
  import { NodeResizer } from "@xyflow/svelte";
  import { usePlotBoardContext } from "./plotBoardContext";

  let {
    data,
  }: {
    data: {
      columnId: string;
      title: string;
      count: number;
      columnType: string;
      parentColumnId: string | null;
      minWidth: number;
      minHeight: number;
    };
  } = $props();

  const getCtx = usePlotBoardContext();
  let ctx = $derived(getCtx());
  let label = $derived(data.columnType === "scene:act" ? "Act" : data.columnType === "scene:chapter" ? "Chapter" : "Group");
  let isAct = $derived(data.columnType === "scene:act");
  let resizerVisible = $derived(isAct && ctx.selectedColumnId === data.columnId);
</script>

<section
  class="plot-flow-group"
  class:act-group={data.columnType === "scene:act"}
  class:chapter-group={data.columnType === "scene:chapter"}
  class:active={ctx.selectedColumnId === data.columnId}
>
  {#if isAct}
    <NodeResizer
      isVisible={resizerVisible}
      minWidth={data.minWidth}
      minHeight={data.minHeight}
      color="var(--accent)"
      onResizeEnd={() => void ctx.persistCanvas()}
    />
  {/if}
  <header>
    <button type="button" class="group-title group-drag-handle" title={`${data.title} - drag to move`} onclick={() => ctx.selectColumn(data.columnId)}>
      <i class="ti ti-grip-vertical" aria-hidden="true"></i>
      <span>{data.title}</span>
      <em>{label}</em>
      <small>{data.count}</small>
    </button>
    <button
      type="button"
      class="group-add nodrag"
      title={`Add card to ${data.title}`}
      aria-label={`Add card to ${data.title}`}
      disabled={ctx.saving}
      onclick={() => ctx.addCardToColumn(data.columnId)}
    >
      <i class="ti ti-plus" aria-hidden="true"></i>
    </button>
  </header>
</section>
