<!--
  Hands the host two flow-context functions. "Where is the author looking?" (#2348): the
  centre of the visible canvas, in flow (board) coordinates — so the board places a new
  box where the view is, not at the end of an ever-growing row. And a screen → flow
  converter, so a card drag can ask which box the pointer is over (ADR-0097 §8). Must live
  INSIDE <SvelteFlow> — `useSvelteFlow` reads the flow context. Renders nothing.
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
    onReady: (
      center: () => { x: number; y: number } | null,
      toFlow: (screen: { x: number; y: number }) => { x: number; y: number },
    ) => void;
  } = $props();

  const { screenToFlowPosition } = useSvelteFlow();

  onMount(() => {
    onReady(
      () => {
        const rect = getContainer()?.getBoundingClientRect();
        // A hidden / zero-size canvas has no meaningful centre.
        if (!rect || rect.width === 0 || rect.height === 0) return null;
        return screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
      },
      (screen) => screenToFlowPosition(screen),
    );
  });
</script>
