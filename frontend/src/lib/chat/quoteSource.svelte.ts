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
  #timer: ReturnType<typeof setTimeout> | null = null;

  /** The open scene pane's live draft for `subject` (undefined when it isn't
   *  open). Read inside an effect so editing the scene re-links the chat: a
   *  quote edited away stops being a link instead of opening onto nothing. */
  liveDraft(subject: string): string | undefined {
    return editorPanes.panes.find((p) => p.document?.type === "manuscript" && p.document.id === subject)
      ?.draftMarkdown;
  }

  /** `refresh`, debounced: typing in the scene re-parses it once it settles. */
  schedule(subject: string, structure: StructureDocument | null, delayMs = 400): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = setTimeout(() => {
      this.#timer = null;
      void this.refresh(subject, structure);
    }, delayMs);
  }

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
