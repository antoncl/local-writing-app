<!--
  RegionActions — the central handle-bar chrome for a registered region (#258,
  ADR-0022 / ADR-0032 §D Amdt 1). It renders the view SELECTOR for an explicit-
  view pane that opts into `view.switcher`, then the pane's own trailing actions.
  Because the selector is rendered HERE (driven by the region's `view.kind`), App
  no longer hand-places `<ViewSwitcher>` per pane — closing the drift seam where a
  pane's selector and its list could diverge. The tiled shell (WorkspaceNode) stays
  view-agnostic and just delegates its actions rail to this outlet.
-->
<script lang="ts">
  import { panelRegistry } from "@/lib/stores/panelRegistry.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import type { PanelId } from "@/lib/types";
  import ViewSwitcher from "@/components/widgets/ViewSwitcher.svelte";

  let { id }: { id: PanelId } = $props();

  let entry = $derived(panelRegistry.get(id));
</script>

{#if entry}
  {#if entry.view?.switcher}
    <ViewSwitcher kind={entry.view.kind} schema={$metadataSchemaStore} />
  {/if}
  {@render entry.actions?.()}
{/if}
