// Machine-layer assistant writes (#2444) — one home shared by the New-project
// wizard and the Machine Settings "Assistants" tab. Every call passes
// `layer_id: ""` (the machine layer) and then refreshes both rosters: the
// machine one these surfaces show, and the project-scoped one an open
// project's pane/chat picker reads.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import { refreshAssistantEntries } from "@/lib/stores/assistants";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import type { AssistantEntrySummary, EntryMetadata } from "@/lib/types";

const MACHINE = "";

// The machine layer's OWN roster (#2448) — what a machine-layer reorder or
// un-list acts on. The merged `assistantEntriesStore` is the open project's
// view (its files, its curation); building a machine reorder from it wrote
// project-local ids into the machine `.order.yaml`. `writable` because the
// wizard is a legacy-mode component (`$store` reads).
export const machineAssistantEntriesStore = writable<AssistantEntrySummary[]>([]);

export async function loadMachineAssistants(): Promise<AssistantEntrySummary[]> {
  return (await api.listMachineAssistantEntries()).entries;
}

// Monotonic guard, as in `refreshAssistantEntries`: an earlier answer must not
// land over a later one when two refreshes overlap.
let latest = 0;

export async function refreshMachineAssistants(): Promise<void> {
  const seq = ++latest;
  try {
    const entries = await loadMachineAssistants();
    if (seq === latest) machineAssistantEntriesStore.set(entries);
  } catch {
    // Leave the previous list in place (backend unavailable).
  }
}

async function refreshBoth(): Promise<void> {
  await Promise.all([refreshMachineAssistants(), refreshAssistantEntries()]);
}

/** The provider/tier/model an assistant stores in its metadata. */
export type AssistantModelChoice = { provider: string; tier: string; model: string };

function modelMetadata(choice: AssistantModelChoice): EntryMetadata {
  return { ai_provider: choice.provider, ai_capability_tier: choice.tier, ai_model: choice.model };
}

export async function hireMachineAssistant(
  title: string,
  provider: string,
  tier: string,
  model: string,
): Promise<void> {
  const created = await api.createAssistantEntry(title, MACHINE);
  await api.saveAssistantEntry({
    ...created,
    metadata: { ...created.metadata, ...modelMetadata({ provider, tier, model }) },
  });
  // The backend lists it topmost on the machine layer and leaves the open
  // project's order alone (#2449) — no follow-up reorder needed here.
  await refreshBoth();
}

export async function reorderMachineAssistants(orderedIds: string[]): Promise<void> {
  await api.reorderAssistants(orderedIds, MACHINE);
  await refreshBoth();
}

export async function unlistMachineAssistant(id: string): Promise<void> {
  await api.unlistAssistant(id, MACHINE);
  await refreshBoth();
}

/** Rename and/or re-point an assistant; omitted model fields keep what it has. */
export async function updateMachineAssistant(
  id: string,
  changes: { title: string; provider?: string; tier?: string; model?: string },
): Promise<void> {
  // Settings edits the file under any open editor pane on it, and assistant
  // panes are not re-baselined from disk — so close (and flush) such a pane
  // first, or its next autosave 409s against the revision written here.
  for (const pane of editorPanes.panes.filter((p) => p.document?.type === "assistant" && p.document.id === id)) {
    await editorPanes.close(pane.id);
  }
  const entry = await api.getAssistantEntry(id);
  const picked = changes.provider
    ? modelMetadata({ provider: changes.provider, tier: changes.tier ?? "", model: changes.model ?? "" })
    : {};
  await api.saveAssistantEntry({
    ...entry,
    title: changes.title,
    metadata: { ...entry.metadata, ...picked },
  });
  await refreshBoth();
}

export async function deleteMachineAssistant(id: string): Promise<void> {
  await api.deleteAssistantEntry(id);
  // Same tearDown an in-app delete ends with; an open pane must not autosave
  // into a file that is gone.
  editorPanes.closeRemovedNodes([id]);
  await refreshBoth();
}
