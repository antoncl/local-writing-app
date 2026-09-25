import type {
  CopyMutationSetResult,
  MutationSetEntry,
  MutationSetEntryList,
  MutationSetRow,
  PromotionPlan,
} from "@/lib/types";
import { request } from "./core";

export const mutationSetsApi = {
  // Reusable mutation sets (#62).
  listMutationSetEntries() {
    return request<MutationSetEntryList>("/mutation-sets");
  },
  createMutationSetEntry(payload: {
    // ADR-0095 §2: optional — an untitled set's label is derived from its rows.
    title?: string;
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
  // ADR-0095 §6/§7: copy a set into the open project, re-pinned. `undefined`/
  // omitted keeps the source's own pin (including none, for a template); an
  // empty string is a deliberate un-pin. Row ids are kept; rows that no
  // longer validate against the (re-)pinned entity's type are dropped and
  // reported back.
  copyMutationSet(entryId: string, targetEntity?: string | null) {
    return request<CopyMutationSetResult>(`/mutation-sets/${entryId}/copy`, {
      method: "POST",
      body: JSON.stringify({ target_entity: targetEntity ?? null }),
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
