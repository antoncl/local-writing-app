import type { AIPreviewResponse, PromptInputConflict } from "@/lib/types";

// The prompt author-preview's per-document state (ADR-0062 Amendment 2 / D1).
//
// This state used to live as component-local `$state` on `PromptPreviewPane`. The
// preview can be detached into its own workspace pane, which mounts a SECOND
// `PromptPreviewPane` instance — so the local state started empty and the author's
// typed input values (and the last render) vanished on detach, and again on
// reattach. Holding it here, keyed by the open prompt's document id, lets the
// docked and detached instances share ONE record: detach/reattach preserves
// everything. Only one instance is mounted at a time (the inline render is gated
// on `!previewDetached`), so there is no double-render or write contention.
//
// A record's fields are `$state` (deeply reactive); the id→record map is plain, so
// `entryFor` can lazily create a record from within a `$derived` without mutating
// tracked state. Records are never evicted — bounded by the number of open prompt
// documents, a handful — so there is no pruning here.
class PromptPreviewRecord {
  // The chosen target scene for the preview's ambient `scene`.
  sceneId = $state("");
  // The input VALUES the author typed — the state whose loss on detach is the bug.
  inputDrafts = $state<Record<string, string>>({});
  result = $state<AIPreviewResponse | null>(null);
  running = $state(false);
  error = $state<string | null>(null);
  // The last render's dedup key + the resolved include conflicts.
  lastRenderKey = $state("");
  conflicts = $state<PromptInputConflict[]>([]);
  // The entry id these drafts were seeded for. A plain field (not `$state`): it
  // only guards the one-time seed inside an effect that already tracks the doc id,
  // so a second instance for the same document reuses the drafts instead of
  // re-seeding (wiping) them. It is never rendered.
  seededEntryId: string | null = null;
}

class PromptPreviewDraftStore {
  #byDoc = new Map<string, PromptPreviewRecord>();

  // The mutable record for a document, created empty on first access. Two
  // `PromptPreviewPane` instances for the same id get the SAME record, so their
  // input drafts and render state are one shared, reactive object.
  entryFor(documentId: string): PromptPreviewRecord {
    let record = this.#byDoc.get(documentId);
    if (!record) {
      record = new PromptPreviewRecord();
      this.#byDoc.set(documentId, record);
    }
    return record;
  }
}

export const promptPreviewDrafts = new PromptPreviewDraftStore();
export type { PromptPreviewRecord };
