// Detach Details into a subordinate pane (ADR-0062 reuse, #1258), split out of
// NodeEditor (#2473). A detached pane copies the prompt sub-tab pattern: the host
// registers its `metaContent` snippet under the ephemeral, host-scoped `paneId`
// and tiles it beside the editor. It needs no per-document store — every metadata
// field emits up into the host's `metadata`, so the pane is a live view, never a
// second owner. Must be constructed during the host's initialization (it
// registers an effect).
import { closeSubordinatePane, openSubordinatePane } from "@/lib/utils/subordinatePane";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";

export class DetailsDetach {
  #deps: { hostPaneId: () => string | null; canDetach: () => boolean; railIsPane: () => boolean };

  readonly paneId = $derived.by(() => {
    const host = this.#deps.hostPaneId();
    return host ? `details:${host}` : null;
  });
  // Detached-ness is DERIVED from the layout, not held as `$state`: dragging the
  // pane can restructure the tree and remount the editor, which would reset a
  // local flag (snapping the rail back + orphaning the pane). The layout survives
  // that remount, so the husk stays and the new instance re-registers the content.
  readonly detached = $derived(!!this.paneId && workspaceLayout.isPlaced(this.paneId));

  constructor(deps: {
    hostPaneId: () => string | null;
    // Offer detach only where there is a host pane AND a rail to tear out.
    canDetach: () => boolean;
    railIsPane: () => boolean;
  }) {
    this.#deps = deps;
    // Fold Details back if the node stops having a rail (a none-shape node renders
    // metadata as the whole pane, which would double-mount the snippet). Teardown
    // on editor close is the subordinatePanes cascade's job, not ours — so a
    // transient remount leaves the pane in place rather than tearing it down.
    $effect(() => {
      if (deps.railIsPane() && this.detached) this.reattach();
    });
  }

  detach = (): void => {
    const hostPaneId = this.#deps.hostPaneId();
    if (!this.paneId || !hostPaneId || this.detached || !this.#deps.canDetach()) return;
    openSubordinatePane(this.paneId, hostPaneId, this.reattach, { beside: hostPaneId, edge: "right" });
  };
  reattach = (): void => {
    if (this.paneId) closeSubordinatePane(this.paneId); // idempotent; also the pane's own onClose
  };
}
