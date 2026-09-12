// The chat's implicit-context journal (ADR-0075 §6), as the frontend reads it.
import type { ChatSessionJournalEntry } from "@/lib/types";

// ADR-0086 Amendment 1: the journal holds at most one entry per (id, source) —
// a better-ranked re-mention is a second entry for the same id — so an entry's
// identity is (id, source), never the id alone. Every keyed list and every
// dedup of journal entries reads this. `source` defaults the way the wire does.
export function journalEntryKey(entry: ChatSessionJournalEntry): string {
  return `${entry.entry_id}|${entry.source ?? "user_message"}`;
}

// How many distinct entities the journal holds — what "Auto-added this
// conversation · N" counts, so a promoted entry is not counted twice.
export function journalEntityCount(journal: readonly ChatSessionJournalEntry[]): number {
  return new Set(journal.map((e) => e.entry_id)).size;
}

// Whether an earlier entry in the journal already carries this id — i.e. this
// line is a promotion (the entity re-noticed from a better-ranked source).
export function isPromotedEntry(journal: readonly ChatSessionJournalEntry[], index: number): boolean {
  const id = journal[index]?.entry_id;
  for (let i = 0; i < index; i++) if (journal[i].entry_id === id) return true;
  return false;
}
