<!--
  Registers a component's regions into the panel registry (#32). Snippets are
  only in scope inside markup, not <script>, so a component that owns region
  content passes it here as a prop map (built in markup) and this helper syncs it
  into the global registry for the tiled shell to render — and unregisters on
  destroy. Renders nothing.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { panelRegistry, type RegionEntry } from "@/lib/stores/panelRegistry.svelte";

  let { regions }: { regions: Record<string, RegionEntry> } = $props();

  // Register once on mount: the snippet refs and handler closures are stable for
  // the owner's lifetime (content reactivity happens inside the snippets), so we
  // don't re-register when the parent re-renders and rebuilds the map literal.
  onMount(() => {
    for (const [id, entry] of Object.entries(regions)) panelRegistry.register(id, entry);
    return () => {
      for (const id of Object.keys(regions)) panelRegistry.unregister(id);
    };
  });
</script>
