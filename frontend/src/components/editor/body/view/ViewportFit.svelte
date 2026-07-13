<!--
  Reframes the Svelte Flow viewport by deferring a fitView to a macrotask. Must
  live INSIDE <SvelteFlow> — `useSvelteFlow` reads the flow context, which a
  sibling of <SvelteFlow> (the canvas wrapper) cannot. fitView writes flow-store
  state, so calling it directly inside the tracking $effect is an unsafe mutation
  (Svelte errors and aborts the update, which also broke node-adds). The 80ms
  defer runs it outside the reactive scope AND gives Svelte Flow time to re-measure
  a just-changed node (a fresh add, or the §D rail expanding its target) before we
  frame against its bounds — fitting sooner frames stale bounds. It also debounces
  rapid triggers (last wins).

  `trigger` is the value whose CHANGE requests a reframe — the opened view id (fit
  all nodes on load), or a fresh `{id}` navigate request (center one node). Pass a
  NEW reference each time to re-fire on the same target. A null/undefined trigger
  is inert (no reframe of an empty canvas / a pending request). `options` is the
  fitView payload — defaults to all nodes; pass `{ nodes: [{ id }] }` to centre one.
-->
<script lang="ts">
  import { useSvelteFlow, type FitViewOptions } from "@xyflow/svelte";

  let { trigger, options = {} }: { trigger: unknown; options?: FitViewOptions } = $props();
  const { fitView } = useSvelteFlow();

  let timer: ReturnType<typeof setTimeout> | null = null;
  $effect(() => {
    void trigger; // track — a change (new value / new reference) requests a reframe
    if (trigger == null) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void fitView(options);
    }, 80);
    return () => {
      if (timer) clearTimeout(timer);
    };
  });
</script>
