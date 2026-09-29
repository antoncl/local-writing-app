<!--
  Hands the host a "where is the author looking?" function (#2348): the centre of
  the visible canvas, in flow (board) coordinates. Must live INSIDE <SvelteFlow> —
  `useSvelteFlow` reads the flow context — so the board places a new card where the
  view is, not at the end of an ever-growing row. Renders nothing.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { useSvelteFlow } from "@xyflow/svelte";

  let {
    getContainer,
    onReady,
  }: {
    /** The element the canvas fills; its on-screen centre is the view centre. */
    getContainer: () => HTMLElement | null | undefined;
    onReady: (center: () => { x: number; y: number } | null) => void;
  } = $props();

  const { screenToFlowPosition } = useSvelteFlow();

  onMount(() => {
    onReady(() => {
      const rect = getContainer()?.getBoundingClientRect();
      // A hidden / zero-size canvas has no meaningful centre.
      if (!rect || rect.width === 0 || rect.height === 0) return null;
      return screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
    });
  });
</script>
