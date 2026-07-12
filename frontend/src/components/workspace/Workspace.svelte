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
</script>

<!-- Tile zoom (#219) is presentation-only: the full split tree always renders,
     so no editor (TipTap et al.) ever remounts on maximize/restore. A zoomed
     group is CSS-promoted (WorkspaceNode: `.ws-group.zoomed`) to fill this
     positioned container, painting over the tiles beneath — which stay mounted,
     so restoring re-tiles exactly. -->
<div class="workspace">
  <WorkspaceNode node={workspaceLayout.root} />
</div>

<style>
  .workspace {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    padding: var(--sp-2);
    background: var(--app-bg);
    overflow: hidden;
    /* Containing block for a CSS-promoted (zoomed) tile. */
    position: relative;
  }
  .workspace > :global(.ws-node-fill) {
    flex: 1 1 auto;
  }
</style>
