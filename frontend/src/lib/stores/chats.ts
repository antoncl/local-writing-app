// Chats domain store — the chat-session roster (Chats pane). A server-mirrored
// slice lifted out of App.svelte as the first domain of the #14 reactive state
// layer (see docs/frontend-architecture.md).
//
// Deliberately `writable` (not runes `$state`): App.svelte stays in Svelte 5
// LEGACY mode for now, and a legacy `$:`/template read of `$store` is
// compiler-tracked (the proven colors.ts pattern), whereas a legacy block does
// not reliably re-run on a runes `$state` mutation. The accessor surface here
// is stable, so the internals can become `$state` later without touching
// consumers.

import { get, writable } from "svelte/store";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import type { ChatSessionSummary } from "@/lib/types";

export const chatSessionsStore = writable<ChatSessionSummary[]>([]);

// Refresh the roster from the backend. Swallows errors (backend may be offline)
// and leaves an empty list — matching the prior App.svelte behavior.
export async function refreshChatSessions(): Promise<void> {
  try {
    chatSessionsStore.set((await api.listChatSessions()).sessions);
  } catch {
    chatSessionsStore.set([]);
  }
}

// #2347: deleting a node cascades to every chat whose saved `subject` is that
// node (#1078, backend `_purge_references_to`) — for EVERY delete (scene, card,
// plotline, deck, tag, mutation set, tree subtree…), not just the editor-pane
// one. These three are the one frontend mechanism for it: the confirm sentence,
// the post-delete roster diff that closes the vanished chats' tabs, and the
// wrapper that runs the latter after the former's delete.

// The sentence a cascading delete's confirm appends: how many roster chats are
// about ANY of `subjectIds`. Null when none (the confirm stays as it was).
export function chatCascadeLine(subjectIds: readonly string[]): string | null {
  const subjects = new Set(subjectIds);
  const chats = get(chatSessionsStore).filter((session) => session.subject && subjects.has(session.subject));
  if (chats.length === 0) return null;
  const names = chats.map((chat) => `"${chat.title || "Untitled chat"}"`).join(", ");
  const noun = chats.length === 1 ? "chat" : "chats";
  return `This also deletes ${chats.length} ${noun} about it (${names}) — the conversation is removed with it.`;
}

// Re-fetch the roster and close the tabs of chats that vanished from it. A FAILED
// fetch changes nothing and returns [] — diffing against an empty roster would
// close every open chat. tearDown (via closeRemovedNodes), not close: close
// flushes, and there is no file left to save to. Returns the vanished ids.
export async function reconcileCascadedChats(): Promise<string[]> {
  const before = get(chatSessionsStore).map((session) => session.id);
  let sessions: ChatSessionSummary[];
  try {
    sessions = (await api.listChatSessions()).sessions;
  } catch {
    return [];
  }
  chatSessionsStore.set(sessions);
  const present = new Set(sessions.map((session) => session.id));
  const gone = before.filter((id) => !present.has(id));
  if (gone.length === 0) return gone;
  editorPanes.closeRemovedNodes(gone);
  if (editorPanes.activeChatId && gone.includes(editorPanes.activeChatId)) editorPanes.activeChatId = null;
  return gone;
}

// Run a cascading delete, then reconcile the chats it took with it — BEFORE the
// caller tears down the deleted node's own pane (tearing that down closes its
// subordinate brainstorm chat, which would flush a save to the deleted file).
// A failed `remove` throws as before and reconciles nothing.
export async function withChatCascade<T>(remove: () => Promise<T>): Promise<T> {
  const result = await remove();
  await reconcileCascadedChats();
  return result;
}

// Write-through from a mutation that already returns the canonical roster
// (e.g. delete chat session → ChatSessionList).
export function setChatSessions(sessions: ChatSessionSummary[]): void {
  chatSessionsStore.set(sessions);
}

export function clearChats(): void {
  chatSessionsStore.set([]);
}
