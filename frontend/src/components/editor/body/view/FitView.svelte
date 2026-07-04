<!--
  Reframes the Svelte Flow viewport when the node set changes so every node
  stays inside the canvas (0.5.0 step 3, #80). Must live INSIDE <SvelteFlow> —
  useSvelteFlow reads the flow context. Without this, the initial fitView runs
  against a not-yet-sized canvas and nodes can land over the toolbar.

  fitView writes flow-store state; calling it directly inside the tracking
  $effect is an unsafe mutation (Svelte errors and aborts the update, which also
  broke node-adds). Defer it to a macrotask so it runs outside the reactive scope
  — the timeout also debounces rapid graph edits.
-->
<script lang="ts">
  import { useSvelteFlow } from "@xyflow/svelte";

  // `trigger` is a value the parent changes (opened view id + node count) to
  // request a reframe.
  let { trigger }: { trigger: unknown } = $props();
  const { fitView } = useSvelteFlow();

  let timer: ReturnType<typeof setTimeout> | null = null;
  $effect(() => {
    void trigger; // track
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void fitView({ padding: 0.2, maxZoom: 1 });
    }, 80);
    return () => {
      if (timer) clearTimeout(timer);
    };
  });
</script>
