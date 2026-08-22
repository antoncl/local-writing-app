// Roster row detail shared by the Chats pane and the entry Conversations panel:
// "<n> message(s) · <YYYY-MM-DD HH:MM>". One source so a change to how a chat
// row shows its count/timestamp can't drift between the two surfaces (#831).
export function formatChatRosterDetail(messageCount: number, updatedAt: string): string {
  const plural = messageCount === 1 ? "" : "s";
  const when = updatedAt.slice(0, 16).replace("T", " ");
  return `${messageCount} message${plural} · ${when}`;
}
