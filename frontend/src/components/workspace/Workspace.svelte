<!--
  The tiled workspace shell (#32). Hosts the split-tree from the workspaceLayout
  store, filling the main area edge to edge. Region content comes from the global
  panelRegistry (regions self-register); editor documents are supplied by App as
  the editor hooks below and threaded to every WorkspaceNode via context.
-->
<script lang="ts">
  import { setContext } from "svelte";
  import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
  import WorkspaceNode from "./WorkspaceNode.svelte";
  import { WORKSPACE_KEY, type WorkspaceEditor } from "./workspaceContext";

  // Expose the editor hooks through context via getters so consumers read live
  // values (and svelte-check doesn't flag a captured initial value).
  const props: WorkspaceEditor = $props();

  setContext<WorkspaceEditor>(WORKSPACE_KEY, {
    get title() {
      return props.title;
    },
    get badge() {
      return props.badge;
    },
    get body() {
      return props.body;
    },
    get actions() {
      return props.actions;
    },
    onClose: (id) => props.onClose(id),
  });

  // Tile zoom (#219): a maximized tile renders full-bleed — we hand the renderer
  // just that group instead of the split tree. The tree stays untouched, so
  // restoring re-tiles exactly. A stale target (its group was pruned mid-zoom)
  // falls back to the whole tree rather than a blank shell.
  const displayNode = $derived.by(() => {
    const id = workspaceLayout.zoomedGroupId;
    return (id ? workspaceLayout.groupById(id) : null) ?? workspaceLayout.root;
  });
</script>

<div class="workspace">
  <WorkspaceNode node={displayNode} />
</div>

<style>
  .workspace {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    padding: var(--sp-2);
    background: var(--app-bg);
    overflow: hidden;
  }
  .workspace > :global(.ws-node-fill) {
    flex: 1 1 auto;
  }
  /* A zoomed tile hands the renderer a bare group (no split wrapper); give it
     the same fill so the maximized pane spans the whole board. */
  .workspace > :global(.ws-group) {
    flex: 1 1 auto;
  }
</style>
