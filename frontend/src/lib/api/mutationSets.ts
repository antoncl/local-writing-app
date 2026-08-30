import type { MutationSetEntry, MutationSetEntryList, MutationSetRow, PromotionPlan } from "@/lib/types";
import { request } from "./core";

export const mutationSetsApi = {
  // Reusable mutation sets (#62).
  listMutationSetEntries() {
    return request<MutationSetEntryList>("/mutation-sets");
  },
  createMutationSetEntry(payload: {
    title: string;
    target_entry_type: string;
    // ADR-0055 §3: optional entity pin (omit/"" ⇒ reusable template).
    target_entity?: string;
    rows: MutationSetRow[];
  }) {
    return request<MutationSetEntry>("/mutation-sets", {
      method: "POST",
      body: JSON.stringify({ ...payload, entry_type: "mutation_set:mutation_set" }),
    });
  },
  getMutationSetEntry(entryId: string) {
    return request<MutationSetEntry>(`/mutation-sets/${entryId}`);
  },
  // ADR-0055 §5: mark a pinned set placed — the single write-back apply gains
  // when the writer stamps a one-off into a scene. Rejected (400) for a reusable
  // set, which apply leaves untouched.
  placeMutationSet(entryId: string) {
    return request<MutationSetEntry>(`/mutation-sets/${entryId}/place`, { method: "POST" });
  },
  saveMutationSetEntry(entry: MutationSetEntry) {
    return request<MutationSetEntry>(`/mutation-sets/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        target_entry_type: entry.target_entry_type,
        target_entity: entry.target_entity,
        rows: entry.rows,
      }),
    });
  },
  deleteMutationSetEntry(entryId: string) {
    return request<MutationSetEntryList>(`/mutation-sets/${entryId}`, {
      method: "DELETE",
    });
  },
  // §2/§9 slice 4: mutation-set promote — staged + owned only; cascades a pin (§6/§7).
  previewMutationSetPromotion(entryId: string, targetLayerId: string) {
    return request<PromotionPlan>(`/mutation-sets/${entryId}/promote/preview`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  promoteMutationSetEntry(entryId: string, targetLayerId: string) {
    return request<MutationSetEntry>(`/mutation-sets/${entryId}/promote`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
};
