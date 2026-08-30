import type { ResearchNote, StructureDocument, StructureNodeDeletePreview } from "@/lib/types";
import { request } from "./core";

export const researchApi = {
  // ----- Research tree -----
  // Mirrors the manuscript-structure calls; see docs/research-strategy.md.
  getResearchStructure() {
    return request<StructureDocument>("/research-structure");
  },
  createResearchNode(title: string, entryType: string, parentId?: string | null) {
    return request<StructureDocument>("/research-structure/nodes", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType, parent_id: parentId ?? null }),
    });
  },
  renameResearchNode(nodeId: string, title: string) {
    return request<StructureDocument>(`/research-structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  },
  moveResearchNode(nodeId: string, targetParentId: string, position: number) {
    return request<StructureDocument>(`/research-structure/nodes/${encodeURIComponent(nodeId)}/move`, {
      method: "POST",
      body: JSON.stringify({ target_parent_id: targetParentId, position }),
    });
  },
  cascadeResearchDeletePreview(nodeId: string) {
    return request<StructureNodeDeletePreview>(`/research-structure/nodes/${encodeURIComponent(nodeId)}/cascade-preview`);
  },
  deleteResearchNode(nodeId: string) {
    return request<StructureDocument>(`/research-structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
  },
  getResearchNote(noteId: string) {
    return request<ResearchNote>(`/research/notes/${encodeURIComponent(noteId)}`);
  },
  saveResearchNote(note: ResearchNote, body: string) {
    return request<ResearchNote>(`/research/notes/${encodeURIComponent(note.id)}`, {
      method: "PUT",
      body: JSON.stringify({
        title: note.title,
        body,
        base_revision: note.revision,
        entry_type: note.entry_type,
        metadata: note.metadata,
      }),
    });
  },
};
