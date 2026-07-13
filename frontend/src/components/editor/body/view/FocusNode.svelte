<!--
  Centers the Svelte Flow viewport on ONE node when the §D Parameters rail asks
  to navigate to a formal's owning node (ADR-0038 §D, #222). Like FitView it must
  live INSIDE <SvelteFlow> — `useSvelteFlow` reads the flow context, which a
  sibling of <SvelteFlow> (the canvas wrapper) cannot. fitView writes flow-store
  state, so the call is deferred to a macrotask (an unsafe mutation inside the
  tracking $effect otherwise aborts the update — the same reason FitView defers).
-->
<script lang="ts">
  import { useSvelteFlow } from "@xyflow/svelte";

  // A fresh object per request (not a bare id) so clicking the SAME row again
  // re-centers — the $effect tracks the reference, which changes every click.
  let { request }: { request: { id: string } | null } = $props();
  const { fitView } = useSvelteFlow();

  let timer: ReturnType<typeof setTimeout> | null = null;
  $effect(() => {
    const id = request?.id;
    if (!id) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void fitView({ nodes: [{ id }], maxZoom: 1.1, minZoom: 0.5, padding: 0.5, duration: 200 });
    }, 20);
    return () => {
      if (timer) clearTimeout(timer);
    };
  });
</script>
