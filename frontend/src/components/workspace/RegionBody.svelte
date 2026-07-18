<!--
  RegionBody — renders a registered region's body (#258). For an explicit-view
  pane (`entry.view` present) it resolves the pane's current spec centrally —
  `paneViews.specFor(kind, schema)` — from the SAME `view.kind` that drives the
  selector, and hands it to the body snippet. So the selected lens and the
  rendered list share one source: no per-pane `specFor` call to drift from the
  switcher. A non-view pane receives `undefined` and ignores it. This keeps the
  spec-resolution out of the geometry shell (WorkspaceNode).
-->
<script lang="ts">
  import { panelRegistry } from "@/lib/stores/panelRegistry.svelte";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import type { PanelId } from "@/lib/types";

  let { id }: { id: PanelId } = $props();

  let entry = $derived(panelRegistry.get(id));
  let spec = $derived(entry?.view ? paneViews.specFor(entry.view.kind, $metadataSchemaStore) : undefined);
</script>

{#if entry}
  {#if entry.view && $metadataSchemaStore == null}
    <!-- A view pane resolves its roster (`descendants_of:<root>`) against the
         metadata schema; until that store loads, the roster under-resolves and a
         default's roots collapse to empty (the schema is always present once
         loaded, so `null` means "not loaded yet"). Show a loading state; the
         `$derived`/store reactivity swaps in the real view the moment it arrives. -->
    <div class="pane-loading">Loading…</div>
  {:else}
    {@render entry.body(spec)}
  {/if}
{/if}

<style>
  .pane-loading {
    padding: 1rem;
    color: var(--text-3);
  }
</style>
