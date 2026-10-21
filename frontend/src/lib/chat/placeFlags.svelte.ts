// Place flags (ADR-0100): the chat's action that turns one finished assistant
// reply into flags on the subject scene. One extraction turn on the backend (which
// records its cost on the chat), then the scene opens beside the conversation and
// its pane places the edits and notes over the whole body. Kept out of
// ChatBodyView (its size cap); the view only wires deps and passes `place` on.

import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { showSceneBeside } from "@/lib/stores/quoteReveal";
import type { ChatMessage } from "@/lib/types";

export interface PlaceFlagsDeps {
  getChat: () => { chatId: string | null; assistantId: string | null; history: ChatMessage[] };
  /** The subject scene and its plain text (QuoteSourceController's). */
  getScene: () => { sceneId: string | null; plain: string | null };
  /** The chat's own pane, so the scene opens beside it. */
  hostPaneId: () => string | null;
  /** The chat's new running cost after the extraction turn. */
  setCostTotal: (total: number | null) => void;
}

export class PlaceFlagsController {
  /** The reply being turned into flags (its transcript index), else null. */
  placingIndex = $state<number | null>(null);
  notice = $state<string | null>(null);
  #deps: PlaceFlagsDeps;

  constructor(deps: PlaceFlagsDeps) {
    this.#deps = deps;
  }

  async place(index: number): Promise<void> {
    if (this.placingIndex !== null) return;
    const { chatId, assistantId, history } = this.#deps.getChat();
    const { sceneId, plain } = this.#deps.getScene();
    if (!chatId || !sceneId) return;
    if (plain === null) {
      // The scene's text is read on a short debounce; say so rather than do nothing.
      this.notice = "The scene's text hasn't loaded yet — try again in a moment.";
      return;
    }
    this.notice = null;
    this.placingIndex = index;
    try {
      // #2596: the call reads the chat's lore from disk — persist pending edits
      // first. The scene's own text rides along live (`scene_text`).
      await editorPanes.flushBeforeAICall();
      // The transcript ENDS at the chosen reply: later turns aren't sent (ADR-0100 §3).
      const res = await api.extractFlags({
        messages: history.slice(0, index + 1).map(({ role, content }) => ({ role, content })),
        assistant_id: assistantId,
        chat_id: chatId,
        scene_text: plain,
      });
      if (!res.ok) {
        this.notice = res.error || "Couldn't turn that reply into flags.";
        return;
      }
      this.#deps.setCostTotal(res.cost_usd_total ?? null);
      if (res.edits.length === 0 && res.notes.length === 0) {
        this.notice = "That reply had nothing to place on the scene.";
        return;
      }
      await showSceneBeside(sceneId, this.#deps.hostPaneId());
      editorPanes.installFlagsInOpenPane(sceneId, { edits: res.edits, notes: res.notes });
    } catch (e) {
      this.notice = (e as Error).message;
    } finally {
      this.placingIndex = null;
    }
  }
}
