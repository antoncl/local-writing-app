// The prior turns a chat send ships to the model (#2339). A reply's thinking,
// usage, cost and provenance are kept on the transcript (and saved with the
// chat), but the model only ever sees who said what: role + content. Replaying
// earlier reasoning would inflate every follow-up's context (the very cost that
// slows local models) and isn't what thinking models expect between turns.
import type { ChatMessage } from "@/lib/types";

export function outgoingHistory(messages: readonly ChatMessage[]): ChatMessage[] {
  return messages.map(({ role, content }) => ({ role, content }));
}
