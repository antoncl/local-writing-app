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
import {
  keyedReferrerIndexStore,
  referenceIndexStore,
  referrerFieldIndexStore,
  refreshReferenceIndexInBackground,
} from "@/lib/stores/references";
import { loreEntriesStore, setLoreEntries } from "@/lib/stores/lore";
import { mutationSetEntriesStore, setMutationSetEntries } from "@/lib/stores/mutationSets";
import { mutationSetLabel } from "@/lib/editor-core/mutationNodes";
import { setPromptEntries } from "@/lib/stores/prompts";
import { setPlotTemplates } from "@/lib/stores/plotTemplates";
import { deletePlotline } from "@/lib/stores/plotlines";
import { deleteDeck } from "@/lib/stores/decks";
import { refreshPlotBoard } from "@/lib/stores/plotBoard";
import { setAssistantEntries } from "@/lib/stores/assistants";
import { refreshTagNodes } from "@/lib/stores/tagNodes";
import { chatCascadeLine, setChatSessions, withChatCascade } from "@/lib/stores/chats";
import { researchStructureStore, setResearchStructure, setStructure } from "@/lib/stores/structure";
import { refreshTodos } from "@/lib/stores/todos";
import { findNodeBySceneId } from "@/lib/utils/treeHelpers";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
import { inheritedLayerLabel } from "@/lib/utils/provenance";
import type { EditorPaneState } from "@/lib/editor-core/editorPaneModel";
import type { Backlink } from "@/lib/types";

// The slice of the editor-pane controller this flow drives. The single
// EditorPanesController instance satisfies it structurally; a narrow interface
// keeps the coupling explicit and this module ignorant of the rest of the
// controller (and of its private autosave/save-chain state).
//
// `orphanWarning` is injected the same way (avoids a cycle with
// projectSession, which imports editorPanes) — `enabled()` reads the machine
// setting, `suppress()` writes it when the confirm dialog's "don't show this
// again" is ticked for THIS warning (ADR-0089 §9). Optional so a host built
// before it's wired (or a test double) just gets no orphan sentence.
export interface DeletePaneHost {
  panes: EditorPaneState[];
  activeChatId: string | null;
  tearDown(id: string): void;
  setStatus(message: string): void;
  orphanWarning?: { enabled: () => boolean; suppress: () => Promise<void> };
}

export async function requestDeleteScene(host: DeletePaneHost, id: string): Promise<void> {
  const pane = host.panes.find((candidate) => candidate.id === id);
  if (!pane?.scene) return;
  const documentKind = pane.document?.type ?? "manuscript";
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
    backlinks = await backlinksFor(sceneId, get(referenceIndexStore), {
      fieldIndex: get(referrerFieldIndexStore),
      schema: get(metadataSchemaStore),
      loreEntries: get(loreEntriesStore),
    });
  } catch (error) {
    console.warn("Failed to fetch backlinks", error);
  }
  // Confirm-dialog copy per kind. Maps rather than nested ternaries so a new
  // kind is one line in each place, not another ternary rung. `prompt` is the
  // fallback (its own kind); chat and assistant are listed explicitly so they
  // no longer borrow the prompt wording (#1082).
  const fileLabel =
    ({ manuscript: "scene", lore: "entry", research: "note", view: "view", plot_template: "template", plot_card: "card", plotline: "plotline", plot_deck: "deck", chat: "chat", assistant: "assistant", tag: "tag" } as Record<string, string>)[
      documentKind
    ] ?? "prompt";
  const titleLabel =
    ({ manuscript: "Delete Scene", lore: "Delete Entry", research: "Delete Note", view: "Delete View", plot_template: "Delete Template", plot_card: "Delete Card", plotline: "Delete Plotline", plot_deck: "Delete Deck", chat: "Delete Chat", assistant: "Delete Assistant", tag: "Delete Tag" } as Record<string, string>)[
      documentKind
    ] ?? "Delete Prompt";
  // An inherited assistant's file lives in an ancestor layer, so deleting it
  // there reaches every project that inherits it (#2444) — say so.
  const owner = pane.scene as { source_layer_id?: string; source_layer_label?: string };
  const inheritedFrom = documentKind === "assistant" ? inheritedLayerLabel(owner, get(projectLayerIdStore)) : null;
  const baseMessage = inheritedFrom
    ? `Delete "${sceneTitle}"? This removes the assistant file from ${inheritedFrom} — every project that inherits from it loses it.`
    : `Delete "${sceneTitle}"? This removes the ${fileLabel} file from the project.`;
  let message =
    backlinks.length > 0
      ? `${baseMessage}\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} this — those links will become broken:`
      : baseMessage;
  const details = backlinks.map((link) => `${link.title} — ${link.field_name}`);

  // ADR-0089 §9: a keyed referrer is a relationship-list ITEM naming this node
  // as its target, not an ordinary reference — deleting it leaves the item on
  // disk with a blank key (an orphan), so it gets its own sentence rather than
  // folding into the backlinks list above. Gated on the machine setting; a
  // delete with no keyed referrers changes nothing here.
  const orphanWarningEnabled = host.orphanWarning?.enabled() ?? false;
  const keyedReferrers = orphanWarningEnabled ? (get(keyedReferrerIndexStore).get(sceneId) ?? []) : [];
  let onDontShowAgain: (() => Promise<void>) | undefined;
  if (keyedReferrers.length > 0 && host.orphanWarning) {
    const schema = get(metadataSchemaStore);
    let titleById = new Map<string, string>();
    try {
      const { candidates } = await api.resolveReferences([...new Set(keyedReferrers.map((r) => r.referrerId))]);
      titleById = new Map(candidates.map((c) => [c.id, c.title]));
    } catch (error) {
      console.warn("Failed to resolve keyed referrers", error);
    }
    const owners = keyedReferrers
      .map((r) => `${titleById.get(r.referrerId) ?? r.referrerId} — ${schema?.fields[r.fieldId]?.name ?? r.fieldId}`)
      .join(", ");
    const noun = keyedReferrers.length === 1 ? "relationship item points" : "relationship items point";
    message = `${message}\n\n${keyedReferrers.length} ${noun} at this entry (${owners}); they will be kept as orphaned items and reported by Validate.`;
    onDontShowAgain = () => host.orphanWarning!.suppress();
  }

  // ADR-0095 §9: deleting a lore entry deletes the mutation sets pinned to
  // it (backend cascade). Warn first and name them — always shown, unlike
  // the orphan-warning sentence above, which has an opt-out (#2232).
  if (documentKind === "lore") {
    const pinnedSets = get(mutationSetEntriesStore).filter((set) => set.target_entity === sceneId);
    if (pinnedSets.length > 0) {
      const labels = pinnedSets.map((set) => mutationSetLabel(set)).join(", ");
      const sceneCount = new Set(pinnedSets.flatMap((set) => set.anchors.map((anchor) => anchor.scene_id))).size;
      message = `${message}\n\nThis also deletes ${pinnedSets.length} mutation set(s) (${labels}), used in ${sceneCount} scene(s); their pills will show as missing.`;
    }
  }

  // #2345: say so when the delete also removes chats about this node — a
  // brainstorm that just created an entry is exactly such a chat, and losing it
  // silently is how a stray delete wedged its open tab.
  // A chat's own delete cascades nothing.
  const chatLine = documentKind === "chat" ? null : chatCascadeLine([sceneId]);
  if (chatLine) message = `${message}\n\n${chatLine}`;

  confirmService.request({
    title: titleLabel,
    message,
    details,
    confirmLabel: titleLabel,
    destructive: true,
    onConfirm: () => deleteScene(host, id),
    onDontShowAgain,
  });
}

async function deleteScene(host: DeletePaneHost, id: string): Promise<void> {
  const pane = host.panes.find((candidate) => candidate.id === id);
  if (!pane?.scene) return;
  const documentKind = pane.document?.type ?? "manuscript";
  const sceneTitle = pane.scene.title;
  // #2347: every kind but a chat itself reconciles the chats it may have taken
  // with it (closing their tabs) before this pane is torn down below.
  const remove = () => removeDocument(host, pane as PaneWithScene, documentKind);
  if (documentKind === "chat") await remove();
  else await withChatCascade(remove);
  // A delete drops the node's outgoing refs and dangles any backlinks to it,
  // so rebuild the reverse reference index (#184 Phase 2) in the background.
  refreshReferenceIndexInBackground();
  host.tearDown(id);
  host.setStatus(`Deleted ${sceneTitle}`);
}

type PaneWithScene = EditorPaneState & { scene: NonNullable<EditorPaneState["scene"]> };

// The kind-routed API delete + store write-through for one document pane.
async function removeDocument(host: DeletePaneHost, pane: PaneWithScene, documentKind: string): Promise<void> {
  if (documentKind === "lore") {
    setLoreEntries((await api.deleteLoreEntry(pane.scene.id)).entries);
    // ADR-0095 §9: the delete may have cascade-deleted mutation sets pinned
    // to this entry — refresh the roster and bump mutationsVersion so the
    // pane, the card and every pill relabel as missing. Best-effort: the
    // entry itself is already gone, so a roster-refresh failure here must
    // not surface as a failed delete.
    try {
      setMutationSetEntries((await api.listMutationSetEntries()).entries);
    } catch (error) {
      console.warn("Failed to refresh the mutation-set roster after a delete", error);
    }
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
    // branches). Delegate to the store's deletePlotline — the single source for
    // this delete (it sets the refreshed roster for the ReferencePicker's `plot`
    // source and refreshes the board so cards on the thread lose their colour
    // axis); the board-node "Delete plotline" runs the very same function.
    await deletePlotline(pane.scene.id);
  } else if (documentKind === "plot_deck") {
    // A deck deletes via its own endpoint (a `plot` node, not a scene). Only the deck goes —
    // its cards fall to the loose area and its child decks to the top level — and the store
    // refreshes the roster + board so the box disappears and they reflow.
    await deleteDeck(pane.scene.id);
  } else if (documentKind === "assistant") {
    setAssistantEntries((await api.deleteAssistantEntry(pane.scene.id)).entries);
  } else if (documentKind === "tag") {
    // The dedicated delete returns 204, not the roster (review fix) — refresh
    // it ourselves, mirroring the assistant branch's write-through.
    await api.deleteTagEntry(pane.scene.id);
    await refreshTagNodes();
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
