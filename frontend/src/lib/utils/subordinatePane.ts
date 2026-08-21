// Open / close a *subordinate* workspace pane — a tiled pane that is a live view
// of an open node (a prompt's detached Preview, ADR-0062 S2; the schema_type
// detail editor, #168) rather than a document of its own. The choreography —
// place it, tie its lifetime to a host pane so the editorPanes.tearDown cascade
// closes it, and strip it on teardown — was hand-rolled at each call site; this
// keeps that contract in one place so the two sites can't drift.
//
// Registration of the pane's *content* stays with the owner (a RegionRegistrar /
// panelRegistry entry); these helpers only govern placement + lifetime.
import { subordinatePanes } from "@/lib/stores/subordinatePanes";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import type { PanelId } from "@/lib/types";

type Edge = "left" | "right" | "top" | "bottom";

/**
 * Make `paneId` visible and, when `hostPaneId` is set, subordinate to that host
 * pane (so closing the host cascades to `close`). `beside` tiles the pane on
 * `edge` (default `"right"`) of the group currently holding that panel — omit it
 * to let the pane land in its home group. Pass `hostPaneId = null` for an
 * ownerless pane, which drops any stale subordinate link.
 */
export function openSubordinatePane(
  paneId: PanelId,
  hostPaneId: string | null,
  close: () => void,
  opts: { beside?: PanelId; edge?: Edge } = {},
): void {
  const besideGroup = opts.beside ? workspaceLayout.groupOf(opts.beside) : null;
  if (besideGroup) {
    // Place it directly beside the host's group. `placeBeside` (not
    // `ensureVisible` + `dropOnEdge`) so the pane never transits an unrelated
    // home group and flips that column's active tab (#1258 follow-up).
    workspaceLayout.placeBeside(paneId, besideGroup.id, opts.edge ?? "right");
  } else {
    workspaceLayout.ensureVisible(paneId);
  }
  if (hostPaneId) subordinatePanes.register(paneId, hostPaneId, close);
  else subordinatePanes.unregister(paneId);
}

/** Drop `paneId`'s subordinate link and remove it from the layout. Idempotent. */
export function closeSubordinatePane(paneId: PanelId): void {
  subordinatePanes.unregister(paneId);
  if (workspaceLayout.isPlaced(paneId)) workspaceLayout.removePanel(paneId);
}
