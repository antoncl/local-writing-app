import type { ChangedPick, ChatSession, ChatSessionList, CreateChatSessionRequest } from "@/lib/types";
import { request } from "./core";

export const chatsApi = {
  listChatSessions() {
    return request<ChatSessionList>("/chats");
  },
  createChatSession(payload: CreateChatSessionRequest = {}) {
    return request<ChatSession>("/chats", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  deleteChatSession(chatId: string) {
    return request<ChatSessionList>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
    });
  },
  // #1635: picked lore entries edited since the AI last saw them — feeds the
  // Context door's "· edited" marker on the auto-added panel.
  chatChangedPicks(chatId: string) {
    return request<{ picks: ChangedPick[] }>(`/chats/${encodeURIComponent(chatId)}/changed-picks`);
  },
};
