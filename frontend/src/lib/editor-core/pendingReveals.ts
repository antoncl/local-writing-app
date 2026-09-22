// A search hit's reveal (#1925) and a review item's reveal (#2124), queued
// the same way and extracted together so ProseBodyView keeps only the
// call-site one-liners: applied once the document they target is loaded —
// the hit's pane may have just opened, and `loadScene` finishes after the
// opener's tick. Keyed to that document — a load of any OTHER document (the
// pane moved on) drops the queued reveal rather than marking a document
// nobody searched. The editor marks matches itself (searchMatchHighlight.ts):
// no markdown offset crosses this seam.
//
// #2124: a review item's reveal. `mutates_source` reveals its own marker's
// pill (mutationNodes.ts); every other reason reveals the source's first
// mention by name (searchMatchHighlight.ts) — a silent no-op when nothing is
// found.
import type { Editor } from "@tiptap/core";
import { firstMentionReveal, type SearchReveal } from "./searchMatchHighlight";
import { revealMutationPill } from "./mutationNodes";

type SearchTarget = { sceneId: string; reveal: SearchReveal };
type ReviewTarget = { sceneId: string; markerId?: string; names?: string[] };

export class PendingReveals {
  #search: SearchTarget | null = null;
  #review: ReviewTarget | null = null;

  queueSearch(sceneId: string, reveal: SearchReveal): void {
    this.#search = { sceneId, reveal };
  }

  queueReview(sceneId: string, target: { markerId?: string; names?: string[] }): void {
    this.#review = { sceneId, ...target };
  }

  /** Drop both queues without applying — a load of a scene neither reveal
   *  targets (or a clear back to no scene at all). */
  clear(): void {
    this.#search = null;
    this.#review = null;
  }

  /** Apply whichever queued reveals target `loadedSceneId`. Both queues are
   *  consumed (cleared) regardless of whether each one fires — a reveal for
   *  a scene that never becomes `loadedSceneId` is simply dropped. */
  apply(loadedSceneId: string | null, editor: Editor | null, editorElement: HTMLElement | null): void {
    const search = this.#search;
    this.#search = null;
    if (search && editor && search.sceneId === loadedSceneId) {
      editor.commands.revealSearchMatch(search.reveal);
    }

    const review = this.#review;
    this.#review = null;
    if (review && editor && editorElement && review.sceneId === loadedSceneId) {
      if (review.markerId) revealMutationPill(editorElement, review.markerId);
      const reveal = review.names ? firstMentionReveal(editor.state.doc, review.names) : null;
      if (reveal) editor.commands.revealSearchMatch(reveal);
    }
  }
}
