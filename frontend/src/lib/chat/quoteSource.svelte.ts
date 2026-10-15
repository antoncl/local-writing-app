// Quote links (#2498): the chat subject's scene text, kept reactive so the
// transcript re-links when it arrives. Prefers an open pane's live draft, else
// the saved scene. Stale text at worst fails to link or reveal — it never links
// wrong, since the reveal re-matches in the live doc.

import { api } from "@/lib/api";
import { scenePlainText } from "@/lib/chat/quoteLinks";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { findNodeBySceneId } from "@/lib/utils/treeHelpers";
import type { StructureDocument } from "@/lib/types";

export class QuoteSourceController {
  /** The subject scene's plain text; null when the subject isn't a scene. */
  plain = $state<string | null>(null);
  sceneId = $state<string | null>(null);
  #seq = 0;

  /** Re-read the text for `subject` (a reset when it isn't a scene). */
  async refresh(subject: string, structure: StructureDocument | null): Promise<void> {
    const seq = ++this.#seq;
    const isScene = !!subject && !!structure && !!findNodeBySceneId(structure.root, subject);
    this.sceneId = isScene ? subject : null;
    if (!isScene) {
      this.plain = null;
      return;
    }
    try {
      const pane = editorPanes.panes.find((p) => p.document?.type === "manuscript" && p.document.id === subject);
      const markdown = pane ? pane.draftMarkdown : (await api.getScene(subject)).body;
      const plain = await scenePlainText(markdown ?? "");
      if (seq === this.#seq) this.plain = plain;
    } catch {
      if (seq === this.#seq) this.plain = null;
    }
  }
}
