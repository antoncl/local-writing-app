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

import { writable } from "svelte/store";
import { api } from "@/lib/api";
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

// Write-through from a mutation that already returns the canonical roster
// (e.g. delete chat session → ChatSessionList).
export function setChatSessions(sessions: ChatSessionSummary[]): void {
  chatSessionsStore.set(sessions);
}

export function clearChats(): void {
  chatSessionsStore.set([]);
}
