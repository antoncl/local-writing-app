// Quote links (#2498): show a quoted passage in its scene, beside the chat.
//
// Visible = the scene's pane is the ACTIVE tab of its group, and (under tile
// zoom) that group is the zoomed one. A visible pane just gets the reveal.
// Otherwise the scene is opened, and once the App's layout effect has placed it
// (it does so after the content loads) it is moved out of the chat's group:
// into another editor group if there is one, else to the right of the chat's
// group — or, if it landed in another group, that group's tab is activated.
// Tile zoom is NOT undone: a scene hidden by a zoom on some other group stays
// hidden until the reader unzooms (the reveal still runs, queued in the pane).

import { tick } from "svelte";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { isEditorPanelId, workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { G_EDITOR } from "@/lib/stores/workspaceLayout.serialize";
import type { SearchReveal } from "@/lib/editor-core/searchMatchHighlight";

const PLACE_TIMEOUT_MS = 3000;

function scenePane(sceneId: string) {
  return editorPanes.panes.find((p) => p.document?.type === "manuscript" && p.document.id === sceneId);
}

function isVisible(paneId: string): boolean {
  const group = workspaceLayout.groupOf(paneId);
  if (!group || group.active !== paneId) return false;
  return !workspaceLayout.zoomedGroupId || workspaceLayout.zoomedGroupId === group.id;
}

// Moving a tab into another group remounts its editor: a reveal sent to the old
// instance dies with it. Wait for the pane's handle to be replaced (the new
// instance registers itself), then reveal into that one — it queues the reveal
// until its content has loaded. If no remount happens, reveal after the wait.
const REMOUNT_TIMEOUT_MS = 1500;

async function waitForRemount(paneId: string, before: unknown): Promise<void> {
  const deadline = Date.now() + REMOUNT_TIMEOUT_MS;
  for (;;) {
    const now = editorPanes.editorPaneComponents[paneId];
    if (now && now !== before) return;
    if (Date.now() > deadline) return;
    await tick();
    await new Promise((resolve) => setTimeout(resolve, 16));
  }
}

/** An editor group other than the chat's: the main editor group, or any group
 *  holding an editor tab. Side and tool groups never take the scene. */
function otherEditorGroup(chatGroupId: string) {
  return workspaceLayout
    .allGroups()
    .find((g) => g.id !== chatGroupId && (g.id === G_EDITOR || g.tabs.some(isEditorPanelId)));
}

async function waitUntilPlaced(sceneId: string): Promise<string | null> {
  const deadline = Date.now() + PLACE_TIMEOUT_MS;
  for (;;) {
    const pane = scenePane(sceneId);
    if (pane && workspaceLayout.groupOf(pane.id)) return pane.id;
    if (Date.now() > deadline) return null;
    await tick();
    await new Promise((resolve) => setTimeout(resolve, 16));
  }
}

/** Make the scene's pane visible beside the chat (opening it if need be). Shared
 *  by quote reveal and Place flags (ADR-0100 §4). Resolves once the pane is
 *  shown; its handle queues anything sent to it until its content has loaded. */
export async function showSceneBeside(sceneId: string, besidePanelId: string | null): Promise<void> {
  const existing = scenePane(sceneId);
  if (existing && isVisible(existing.id)) return;
  await editorPanes.openScene(sceneId);
  const paneId = await waitUntilPlaced(sceneId);
  if (paneId) {
    const chatGroup = besidePanelId ? workspaceLayout.groupOf(besidePanelId) : null;
    const sceneGroup = workspaceLayout.groupOf(paneId);
    if (chatGroup && sceneGroup && sceneGroup.id === chatGroup.id) {
      // Out of the chat's group: into another editor group when there is one,
      // else a fresh group on the chat's right edge (dropOnEdge splices the tab
      // out; it is a no-op only for a group's sole tab, which can't be the case
      // here — the chat shares the group).
      const before = editorPanes.editorPaneComponents[paneId];
      const other = otherEditorGroup(chatGroup.id);
      if (other) workspaceLayout.moveTab(paneId, other.id);
      else workspaceLayout.dropOnEdge(paneId, chatGroup.id, "right");
      await waitForRemount(paneId, before);
    } else {
      workspaceLayout.activate(paneId);
    }
  }
  await tick();
}

export async function revealQuoteBeside(opts: {
  sceneId: string;
  quote: string;
  /** The chat's pane; null = no beside-move (the scene just opens). */
  besidePanelId: string | null;
}): Promise<void> {
  const { sceneId, quote, besidePanelId } = opts;
  const reveal: SearchReveal = { query: quote, matchCase: true, wholeWord: false, excerpt: "", ordinal: 0 };
  await showSceneBeside(sceneId, besidePanelId);
  editorPanes.revealSearchMatchInOpenPane(sceneId, reveal);
}
