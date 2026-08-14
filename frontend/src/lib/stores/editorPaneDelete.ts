// Delete/confirm flow for editor panes — extracted from editorPanes (the
// controller sat one line under the 1500-line file-size fail-cap). These are the
// confirm-then-delete gestures: a document pane (scene / lore / research /
// prompt / plot template / assistant / chat / view) via its tab, and a saved
// view from a list affordance (e.g. the ViewSwitcher). Free functions over a
// narrow host rather than controller methods, so the controller keeps only thin
// delegates. They touch ONLY its public surface (panes, tearDown, setStatus,
// activeChatId) — never the autosave data-loss machinery next door.

import { get } from "svelte/store";
import { api } from "@/lib/api";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { backlinksFor } from "@/lib/views/backlinks";
import { referenceIndexStore, refreshReferenceIndexInBackground } from "@/lib/stores/references";
import { setLoreEntries } from "@/lib/stores/lore";
import { setPromptEntries } from "@/lib/stores/prompts";
import { setPlotTemplates } from "@/lib/stores/plotTemplates";
import { setPlotlines } from "@/lib/stores/plotlines";
import { refreshPlotBoard } from "@/lib/stores/plotBoard";
import { setAssistantEntries } from "@/lib/stores/assistants";
import { setChatSessions } from "@/lib/stores/chats";
import { researchStructureStore, setResearchStructure, setStructure } from "@/lib/stores/structure";
import { refreshTodos } from "@/lib/stores/todos";
import { findNodeBySceneId } from "@/lib/utils/treeHelpers";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import type { EditorPaneState } from "@/lib/editor-core/editorPaneModel";
import type { Backlink } from "@/lib/types";

// The slice of the editor-pane controller this flow drives. The single
// EditorPanesController instance satisfies it structurally; a narrow interface
// keeps the coupling explicit and this module ignorant of the rest of the
// controller (and of its private autosave/save-chain state).
export interface DeletePaneHost {
  panes: EditorPaneState[];
  activeChatId: string | null;
  tearDown(id: string): void;
  setStatus(message: string): void;
}

export async function requestDeleteScene(host: DeletePaneHost, id: string): Promise<void> {
  const pane = host.panes.find((candidate) => candidate.id === id);
  if (!pane?.scene) return;
  const documentKind = pane.document?.type ?? "scene";
  // The project window must not delete the project's own `project.md` (#750) —
  // refuse it as the guard, not just via the disabled button (a stale ref or
  // future caller would otherwise fall through to deleteScene).
  if (documentKind === "project") return;
  const sceneTitle = pane.scene.title;
  const sceneId = pane.scene.id;
  let backlinks: Backlink[] = [];
  try {
    // The open node's referrers (#194): membership from the in-memory reverse
    // index, rows resolved on demand — same helper the backlinks panel uses.
    backlinks = await backlinksFor(sceneId, get(referenceIndexStore));
  } catch (error) {
    console.warn("Failed to fetch backlinks", error);
  }
  // Confirm-dialog copy per kind (assistant/chat fall through to the prompt
  // wording, as before). Maps rather than nested ternaries so a new kind is one
  // line in each place, not another ternary rung.
  const fileLabel =
    ({ scene: "scene", lore: "entry", research: "note", view: "view", plot_template: "template", plot_card: "card", plotline: "plotline" } as Record<string, string>)[
      documentKind
    ] ?? "prompt";
  const titleLabel =
    ({ scene: "Delete Scene", lore: "Delete Entry", research: "Delete Note", view: "Delete View", plot_template: "Delete Template", plot_card: "Delete Card", plotline: "Delete Plotline" } as Record<string, string>)[
      documentKind
    ] ?? "Delete Prompt";
  const baseMessage = `Delete "${sceneTitle}"? This removes the ${fileLabel} file from the project.`;
  const message =
    backlinks.length > 0
      ? `${baseMessage}\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} this — those links will become broken:`
      : baseMessage;
  const details = backlinks.map((link) => `${link.title} — ${link.field_name}`);
  confirmService.request({
    title: titleLabel,
    message,
    details,
    confirmLabel: titleLabel,
    destructive: true,
    onConfirm: () => deleteScene(host, id),
  });
}

async function deleteScene(host: DeletePaneHost, id: string): Promise<void> {
  const pane = host.panes.find((candidate) => candidate.id === id);
  if (!pane?.scene) return;
  const documentKind = pane.document?.type ?? "scene";
  const sceneTitle = pane.scene.title;
  if (documentKind === "lore") {
    setLoreEntries((await api.deleteLoreEntry(pane.scene.id)).entries);
  } else if (documentKind === "research") {
    // Delete the tree node that points at this note; the backend
    // unlinks the markdown file as part of the cascade.
    const researchStructure = get(researchStructureStore);
    const node = researchStructure ? findNodeBySceneId(researchStructure.root, pane.scene.id) : null;
    if (node) {
      setResearchStructure(await api.deleteResearchNode(node.id));
    }
  } else if (documentKind === "prompt") {
    setPromptEntries((await api.deletePromptEntry(pane.scene.id)).entries);
  } else if (documentKind === "plot_template") {
    // An owned plot-template clone deletes via its own endpoint — routing it
    // through api.deleteScene would 404 (it is a `plot` node, not a scene), the
    // same hazard the `view` branch below guards against.
    setPlotTemplates((await api.deletePlotTemplate(pane.scene.id)).entries);
  } else if (documentKind === "plot_card") {
    // A book-local card deletes via its own endpoint (a `plot` node, not a scene,
    // so api.deleteScene would 404 — same hazard as the template/view branches).
    // No card list store to update; refresh the board so it drops the card.
    await api.deleteCard(pane.scene.id);
    await refreshPlotBoard();
  } else if (documentKind === "plotline") {
    // A book-local plotline deletes via its own endpoint (a `plot` node, not a
    // scene — api.deleteScene would 404, same hazard as the card/template/view
    // branches). The delete returns the refreshed roster for the ReferencePicker's
    // `plot` source; refresh the board too so any card on this thread loses its
    // colour axis (the backend blanks the now-dangling plotline ref).
    setPlotlines((await api.deletePlotline(pane.scene.id)).entries);
    await refreshPlotBoard();
  } else if (documentKind === "assistant") {
    setAssistantEntries((await api.deleteAssistantEntry(pane.scene.id)).entries);
  } else if (documentKind === "chat") {
    setChatSessions((await api.deleteChatSession(pane.scene.id)).sessions);
    if (host.activeChatId === pane.scene.id) host.activeChatId = null;
  } else if (documentKind === "view") {
    // A view is a frontmatter-only node with its own deleter; routing it
    // through api.deleteScene 404s ("Scene <view-id> does not exist").
    await api.deleteView(pane.scene.id);
    await paneViews.reload();
  } else {
    setStructure(await api.deleteScene(pane.scene.id));
    await refreshTodos();
  }
  // A delete drops the node's outgoing refs and dangles any backlinks to it,
  // so rebuild the reverse reference index (#184 Phase 2) in the background.
  refreshReferenceIndexInBackground();
  host.tearDown(id);
  host.setStatus(`Deleted ${sceneTitle}`);
}

// Delete a saved view from a list affordance (e.g. the ViewSwitcher),
// confirming first. Works whether or not the view is currently open: it
// tears down any pane showing it and refreshes the view roster.
export function requestDeleteView(host: DeletePaneHost, viewId: string, title: string): void {
  confirmService.request({
    title: "Delete View",
    message: `Delete "${title}"? This removes the view file from the project.`,
    confirmLabel: "Delete View",
    destructive: true,
    onConfirm: () => deleteView(host, viewId),
  });
}

async function deleteView(host: DeletePaneHost, viewId: string): Promise<void> {
  await api.deleteView(viewId);
  const pane = host.panes.find((p) => p.document?.type === "view" && p.document.id === viewId);
  if (pane) host.tearDown(pane.id);
  await paneViews.reload();
  host.setStatus("Deleted view");
}
