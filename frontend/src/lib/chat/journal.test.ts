import { describe, expect, it } from "vitest";
import type { ChatSessionJournalEntry } from "@/lib/types";
import { isPromotedEntry, journalEntityCount, journalEntryKey } from "./journal";

const hop = { entry_id: "lore_n", title: "Nimitz", added_at_turn: 1, source: "depth1_expansion" as const };
const named = { entry_id: "lore_n", title: "Nimitz", added_at_turn: 3, source: "user_message" as const };
const other = { entry_id: "lore_h", title: "Honor", added_at_turn: 1, source: "user_message" as const };
const journal = [hop, other, named] as ChatSessionJournalEntry[];

describe("journal", () => {
  it("keys an entry by id and source — the same id under two sources is two entries", () => {
    expect(journalEntryKey(hop)).not.toBe(journalEntryKey(named));
    expect(journalEntryKey({ ...named, added_at_turn: 9 })).toBe(journalEntryKey(named));
    expect(journalEntryKey({ entry_id: "lore_x" } as ChatSessionJournalEntry)).toBe("lore_x|user_message");
  });

  it("counts entities, not lines", () => {
    expect(journalEntityCount(journal)).toBe(2);
    expect(journalEntityCount([])).toBe(0);
  });

  it("marks the later line for an already-journaled id as a promotion", () => {
    expect(isPromotedEntry(journal, 0)).toBe(false);
    expect(isPromotedEntry(journal, 1)).toBe(false);
    expect(isPromotedEntry(journal, 2)).toBe(true);
  });
});
