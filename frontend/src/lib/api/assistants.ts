import type { AssistantEntry, AssistantEntryList } from "@/lib/types";
import { request } from "./core";

export const assistantsApi = {
  listAssistantEntries() {
    return request<AssistantEntryList>("/assistants");
  },
  createAssistantEntry(title: string, layerId: string | null = null) {
    // `null` (the default the "+" button sends) = the local layer, i.e. the
    // open project — machine when no project is open. Assistants are a layered
    // kind (ADR-0039), so a new one belongs in the project you're working in,
    // not forced onto the machine roster (#1452). An explicit "" still targets
    // the machine layer (the wizard's cross-project hire).
    return request<AssistantEntry>("/assistants", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: "assistant:assistant", layer_id: layerId }),
    });
  },
  getAssistantEntry(entryId: string) {
    return request<AssistantEntry>(`/assistants/${entryId}`);
  },
  saveAssistantEntry(entry: AssistantEntry) {
    return request<AssistantEntry>(`/assistants/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
      }),
    });
  },
  deleteAssistantEntry(entryId: string) {
    return request<AssistantEntryList>(`/assistants/${entryId}`, {
      method: "DELETE",
    });
  },
  // `layerId` omitted ⇒ the LOCAL layer, which is what a curation gesture always
  // means (#332/#333): the open project states its own opinion about what it
  // inherits, and no ancestor file is touched. Pass "" for the machine layer.
  reorderAssistants(orderedIds: string[], layerId?: string) {
    return request<AssistantEntryList>("/assistants/order", {
      method: "POST",
      body: JSON.stringify({ layer_id: layerId ?? null, ordered_ids: orderedIds }),
    });
  },
  unlistAssistant(entryId: string, layerId?: string) {
    return request<AssistantEntryList>("/assistants/unlist", {
      method: "POST",
      body: JSON.stringify({ layer_id: layerId ?? null, entry_id: entryId }),
    });
  },
};
