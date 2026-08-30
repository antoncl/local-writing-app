import type {
  EntryPatchExtraction,
  LoreEntry,
  LoreEntryList,
  MoveLoreNoteToResearchResponse,
  PromotionTarget,
  PromotionPlan,
} from "@/lib/types";
import { request } from "./core";

export const loreApi = {
  listLoreEntries() {
    return request<LoreEntryList>("/lore");
  },
  createLoreEntry(title: string, entryType: string) {
    return request<LoreEntry>("/lore", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType }),
    });
  },
  getLoreEntry(entryId: string) {
    return request<LoreEntry>(`/lore/${entryId}`);
  },
  // The entry's body with its whole-body code fence stripped (#1628), read-only —
  // fed into the standard revision review so the user commits or declines the
  // unwrap. 409s if the body is no longer a single wrapping fence.
  unwrapLoreCodeFencePreview(entryId: string) {
    return request<{ body: string }>(`/lore/${entryId}/unwrap-preview`);
  },
  // Fork-to-here (#313): copy an inherited lore entry down into the current
  // project, keeping its id, and stop inheriting it. Returns the now-local entry.
  forkLoreEntry(entryId: string) {
    return request<LoreEntry>(`/lore/${entryId}/fork`, { method: "POST" });
  },
  // `authoringLayerId` is ADR-0042's layer L (#314): the write target the rail
  // picker chose. `null` = no explicit target — the open project for a local
  // entry; for an *inherited* entry the backend then 409s rather than silently
  // rewriting ancestor canon. When set, `L == owning layer` edits the owning
  // file, `L < owning` writes a sparse override delta at L.
  // `clearOverrideFields` (#517 / create-project-wizard.md §8) names the fields
  // whose override row(s) to DROP at L, reverting them to the inherited value —
  // the explicit "unset ⇒ inherit" signal. The submitted `metadata` still carries
  // their overridden value; the backend drops the row regardless, which is what
  // distinguishes a reset from omitting the field (read as clear-to-empty).
  saveLoreEntry(
    entry: LoreEntry,
    body: string,
    authoringLayerId: string | null = null,
    clearOverrideFields: string[] = [],
  ) {
    return request<LoreEntry>(`/lore/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
        authoring_layer_id: authoringLayerId,
        clear_override_fields: clearOverrideFields,
      }),
    });
  },
  deleteLoreEntry(entryId: string) {
    return request<LoreEntryList>(`/lore/${entryId}`, {
      method: "DELETE",
    });
  },
  // ADR-0078 §2: declared ancestor projects a node HERE may promote into (empty for a flat project); shared by lore/prompt/mutation_set.
  promotionTargets() {
    return request<PromotionTarget[]>("/promotion/targets");
  },
  // Pure dry-run (ADR-0078 §9): the partition the commit would run, unwritten.
  previewLorePromotion(entryId: string, targetLayerId: string) {
    return request<PromotionPlan>(`/lore/${entryId}/promote/preview`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  // Lift an owned lore entry into a declared ancestor, keeping its id (§1/§2).
  // Refuses 409 already-inherited, 400 not-a-declared-ancestor.
  promoteLoreEntry(entryId: string, targetLayerId: string) {
    return request<LoreEntry>(`/lore/${entryId}/promote`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  // ADR-0051 S4 / ADR-0067 S2: the commit runs as a cached CONTINUATION of the
  // chat itself — `chat_id` is the chat's real id, so the server reads back the
  // field set its lock render registered (ChatSession.field_contract_stored)
  // instead of rebuilding a separate contract, and reuses the cached system
  // prefix + lore rather than re-shipping the transcript fresh. Returns the
  // patch + cost.
  extractEntryPatch(
    nodeId: string,
    body: { messages: { role: string; content: string }[]; assistant_id: string | null; chat_id: string },
  ) {
    return request<EntryPatchExtraction>(`/ai/entry-patch/${encodeURIComponent(nodeId)}/extract`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  // Create-mode sibling — no node yet, so the target entry_type rides in the body.
  extractEntryDraft(
    entryType: string,
    body: { messages: { role: string; content: string }[]; assistant_id: string | null; chat_id: string },
  ) {
    return request<EntryPatchExtraction>("/ai/entry-draft/extract", {
      method: "POST",
      body: JSON.stringify({ entry_type: entryType, ...body }),
    });
  },
  // Migrate a lore_note to a research/note (slice 5). Drops aliases /
  // related_entries / context_policy (the v1 research note schema is
  // title + body + tags only); the response lists what was dropped.
  moveLoreNoteToResearch(entryId: string) {
    return request<MoveLoreNoteToResearchResponse>(
      `/lore/${encodeURIComponent(entryId)}/move-to-research`,
      { method: "POST" },
    );
  },
};
