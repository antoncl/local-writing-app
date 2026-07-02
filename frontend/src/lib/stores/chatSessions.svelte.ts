// Chat-session glue — the Chats-pane roster sync + the openers/creators that
// route a chat into an editor pane, lifted out of App.svelte (#14 P0). A
// singleton rune controller (mirrors editorPanes / projectSession / treeActions
// / todoActions).
//
// App keeps the session roster (Chats pane) in sync and routes opens into
// editor panes; everything inside a conversation — history, composer, streaming,
// cost/TTL, per-turn persistence — lives in ChatBodyView. The reactive list
// itself lives in the chats store (chatSessionsStore); this controller owns the
// actions. Which chat is open is a projection of the editor surface
// (editorPanes.activeChatId), so the controller reads/writes it there.

import { get } from "svelte/store";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { resolutionSceneIdFromInputs } from "@/lib/editor-core/promptResolution";
import {
  chatSessionsStore,
  refreshChatSessions,
  setChatSessions,
} from "@/lib/stores/chats";
import type { ChatSession, PromptEntrySummary } from "@/lib/types";

class ChatSessions {
  // ---- Injected host hooks (set in App.onMount) ----
  run: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  setStatus: (message: string) => void = () => {};
  setError: (message: string) => void = () => {};

  async refresh(): Promise<void> {
    await refreshChatSessions();
  }

  // "+ New Chat": create an empty session and open it in an editor pane.
  async createNewChatSession(): Promise<void> {
    try {
      const session = await api.createChatSession({});
      await this.refresh();
      await editorPanes.openChat(session.id);
    } catch (e) {
      this.setError(`Couldn't create chat: ${(e as Error).message}`);
    }
  }

  // "Invoke chat prompt" from a prose scene: ProseBodyView emits open-chat
  // once its inputs dialog resolves. Create a prompt-bound chat session
  // tied to the originating scene (so the first-send render resolves the
  // `scene` binding), seed the resolved inputs as drafts so the user's
  // dialog entries carry over, and open it in an editor pane.
  async openChatFromPromptEntry(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    sceneId: string | null,
    assistantId: string = "",
  ): Promise<void> {
    await this.run(async () => {
      // A `scene_ref` input (ADR-0012) sets the chat's resolution scene,
      // overriding the originating scene; it then drives per-turn journal
      // resolution (backend reads chat.target_scene_id) and the first-send
      // render alike.
      const resolutionScene = resolutionSceneIdFromInputs(entry, inputs) || (sceneId ?? "");
      const session = await api.createChatSession({
        prompt_entry_id: entry.id,
        assistant_id: assistantId,
        title: entry.title,
        target_scene_id: resolutionScene,
      });
      if (Object.keys(inputs).length > 0) {
        // Persist resolved inputs via the unified node path so ChatBodyView
        // restores them as drafts on load. Echo target_scene_id so it's
        // never dropped (backend also falls back to the persisted value).
        await api.saveNode<ChatSession>(session.id, {
          title: session.title,
          prompt_entry_id: session.prompt_entry_id,
          assistant_id: session.assistant_id,
          system_prompt: session.system_prompt,
          target_scene_id: session.target_scene_id ?? resolutionScene,
          pinned: session.pinned,
          context_items: [],
          messages: [],
          inputs,
        });
      }
      await this.refresh();
      await editorPanes.openChat(session.id);
      this.setStatus(`Opened ${entry.title} as a chat`);
    });
  }

  async deleteChatSessionFromPane(chatId: string): Promise<void> {
    try {
      const listing = await api.deleteChatSession(chatId);
      setChatSessions(listing.sessions);
      if (editorPanes.activeChatId === chatId) {
        editorPanes.activeChatId = null;
      }
      // Tear down any editor pane still pointing at the deleted chat.
      for (const pane of editorPanes.panes.filter(
        (candidate) => candidate.document?.type === "chat" && candidate.document.id === chatId,
      )) {
        editorPanes.tearDown(pane.id);
      }
    } catch (e) {
      this.setError(`Couldn't delete chat: ${(e as Error).message}`);
    }
  }

  async hydrateForProject(): Promise<void> {
    await this.refresh();
    if (get(chatSessionsStore).length === 0) {
      // Auto-create a first chat so the Chats pane always has somewhere to
      // write. Don't auto-open it — chats open into editor panes on demand.
      try {
        await api.createChatSession({});
        await this.refresh();
      } catch {
        // Backend may be offline at boot — leave the list empty; the user
        // can retry via + New Chat.
      }
    }
  }
}

export const chatSessions = new ChatSessions();
