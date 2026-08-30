import type { PromptEntry, PromptEntryList, SnippetDependents, PromotionPlan } from "@/lib/types";
import { request } from "./core";

export const promptsApi = {
  listPromptEntries() {
    return request<PromptEntryList>("/prompts");
  },
  createPromptEntry(title: string, entryType: string) {
    return request<PromptEntry>("/prompts", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType }),
    });
  },
  getPromptEntry(entryId: string) {
    return request<PromptEntry>(`/prompts/${entryId}`);
  },
  savePromptEntry(entry: PromptEntry, body: string) {
    return request<PromptEntry>(`/prompts/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
        inputs: entry.inputs ?? [],
        // Round-trip the "show this prompt on…" allow-list so a body/inputs edit
        // never strips it (ADR-0054 §4/S4; no authoring UI yet).
        offer_on: entry.offer_on ?? [],
        // Round-trip the behavior contract (ADR-0065 S3 / ADR-0062 D3) — the
        // writer rebuilds front matter from these arguments (not a merge), so
        // omitting this silently wipes a forked prompt's output/commit config
        // on the next autosave.
        context_strategy: entry.context_strategy ?? null,
      }),
    });
  },
  deletePromptEntry(entryId: string) {
    return request<PromptEntryList>(`/prompts/${entryId}`, {
      method: "DELETE",
    });
  },
  // Clone a built-in Library prompt into the project as an editable copy
  // (ADR-0049 §5). Unlike lore's fork, this mints a NEW id and leaves the
  // shipped original in place; the returned entry is the local copy.
  forkPromptEntry(entryId: string) {
    return request<PromptEntry>(`/prompts/${entryId}/fork`, { method: "POST" });
  },
  // §2/§9 slice 3: prompt promote — same shape, plus the §6 include cascade + §5 dynamic-reference list.
  previewPromptPromotion(entryId: string, targetLayerId: string) {
    return request<PromotionPlan>(`/prompts/${entryId}/promote/preview`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  promotePromptEntry(entryId: string, targetLayerId: string) {
    return request<PromptEntry>(`/prompts/${entryId}/promote`, {
      method: "POST",
      body: JSON.stringify({ target_layer_id: targetLayerId }),
    });
  },
  // The "used by N prompts / M chats" dependency counts for a snippet (ADR-0061
  // §5). Harmless for a non-snippet prompt (nothing includes it → 0/0), so the
  // caller shows the advisory only when a count is non-zero.
  getPromptDependents(entryId: string) {
    return request<SnippetDependents>(`/prompts/${entryId}/dependents`);
  },
};
