// Machine-layer assistant writes (#2444) — one home shared by the New-project
// wizard and the Machine Settings "Assistants" tab. Every call passes
// `layer_id: ""` (the machine layer) and then refreshes the project-scoped
// roster store so an open project's pane/chat picker reflects the change.

import { api } from "@/lib/api";
import { isAssistantListed, refreshAssistantEntries } from "@/lib/stores/assistants";
import type { AssistantEntrySummary, EntryMetadata } from "@/lib/types";

const MACHINE = "";

export async function loadMachineAssistants(): Promise<AssistantEntrySummary[]> {
  return (await api.listMachineAssistantEntries()).entries;
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
  // Create alone only writes the OPEN PROJECT's order (backend design #333), so
  // with a project open the hire would be unlisted machine-wide. List it on the
  // machine layer, topmost (creating one is a statement of intent about it).
  const listed = (await loadMachineAssistants()).filter(isAssistantListed).map((entry) => entry.id);
  await api.reorderAssistants([created.id, ...listed.filter((id) => id !== created.id)], MACHINE);
  await refreshAssistantEntries();
}

export async function reorderMachineAssistants(orderedIds: string[]): Promise<void> {
  await api.reorderAssistants(orderedIds, MACHINE);
  await refreshAssistantEntries();
}

export async function unlistMachineAssistant(id: string): Promise<void> {
  await api.unlistAssistant(id, MACHINE);
  await refreshAssistantEntries();
}

/** Rename and/or re-point an assistant; omitted model fields keep what it has. */
export async function updateMachineAssistant(
  id: string,
  changes: { title: string; provider?: string; tier?: string; model?: string },
): Promise<void> {
  const entry = await api.getAssistantEntry(id);
  const picked = changes.provider
    ? modelMetadata({ provider: changes.provider, tier: changes.tier ?? "", model: changes.model ?? "" })
    : {};
  await api.saveAssistantEntry({
    ...entry,
    title: changes.title,
    metadata: { ...entry.metadata, ...picked },
  });
  await refreshAssistantEntries();
}

export async function deleteMachineAssistant(id: string): Promise<void> {
  await api.deleteAssistantEntry(id);
  await refreshAssistantEntries();
}
