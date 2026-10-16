import { describe, expect, it } from "vitest";
import { ChatSessionRecord } from "./chatSessionRecord.svelte";
import type { ChatMessage, ChatSession } from "@/lib/types";

function stored(): ChatSession {
  return {
    id: "chat_1",
    title: "Brainstorm",
    pinned: true,
    subject: "scene_9",
    staged_set: "mset_3",
    lore_enabled: true,
    lore_free: true,
    used_node_ids: ["lore_a", "lore_b"],
    used_node_hints: { lore_a: "stable" },
    used_snapshots: [{ node_id: "lore_a", snapshot_id: "snap_1" }],
    field_contract_stored: [{ name: "summary" }],
    journal: [{ id: "lore_a", source: "mention" }],
    cache_write_times: { system: "2026-10-16T10:00:00Z" },
    messages: [],
  } as unknown as ChatSession;
}

const OWN = {
  history: [] as ChatMessage[],
  promptEntryId: "prompt_x",
  assistantId: "asst_y",
  systemPrompt: "locked",
  inputDrafts: { entry: "lore_z" },
};

describe("ChatSessionRecord", () => {
  it("hydrate then toPayload round-trips every persisted field", () => {
    const r = new ChatSessionRecord();
    r.hydrate(stored());
    const history: ChatMessage[] = [
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello", input_truncated: true, journal_added: [] },
    ];
    const p = r.toPayload({ ...OWN, history });
    expect(p.title).toBe("Brainstorm");
    expect(p.pinned).toBe(true);
    expect(p.subject).toBe("scene_9");
    expect(p.staged_set).toBe("mset_3");
    expect(p.lore_enabled).toBe(true);
    expect(p.lore_free).toBe(true);
    expect(p.used_node_ids).toEqual(["lore_a", "lore_b"]);
    expect(p.used_node_hints).toEqual({ lore_a: "stable" });
    expect(p.used_snapshots).toEqual([{ node_id: "lore_a", snapshot_id: "snap_1" }]);
    expect(p.field_contract_stored).toEqual([{ name: "summary" }]);
    expect(p.prompt_entry_id).toBe("prompt_x");
    expect(p.assistant_id).toBe("asst_y");
    expect(p.system_prompt).toBe("locked");
    expect(p.inputs).toEqual({ entry: "lore_z" });
    expect(p.messages.map((m) => m.input_truncated)).toEqual([false, true]);
    expect(r.journal).toEqual([{ id: "lore_a", source: "mention" }]);
    expect(r.cacheWriteTimes).toEqual({ system: "2026-10-16T10:00:00Z" });
  });

  it("derives the title from the first user message while untitled", () => {
    const r = new ChatSessionRecord();
    const history: ChatMessage[] = [{ role: "user", content: "  Plan   the heist  " }];
    expect(r.toPayload({ ...OWN, history }).title).toBe("Plan the heist");
  });

  it("reset clears to the empty state", () => {
    const r = new ChatSessionRecord();
    r.hydrate(stored());
    r.addCacheSlot("system");
    r.changedPicks = [{ id: "lore_a" } as never];
    r.reset();
    const p = r.toPayload(OWN);
    expect(p.title).toBe("Untitled chat");
    expect(p.pinned).toBe(false);
    expect(p.subject).toBe("");
    expect(p.staged_set).toBe("");
    expect(p.lore_enabled).toBe(false);
    expect(p.lore_free).toBe(false);
    expect(p.used_node_ids).toEqual([]);
    expect(p.used_node_hints).toEqual({});
    expect(p.used_snapshots).toEqual([]);
    expect(p.field_contract_stored).toEqual([]);
    expect(p.cache_write_slots).toBeUndefined();
    expect(r.journal).toEqual([]);
    expect(r.changedPicks).toEqual([]);
    expect(r.cacheWriteTimes).toEqual({});
  });

  it("consumeCacheSlots returns the pending slots and clears them; restore puts them back", () => {
    const r = new ChatSessionRecord();
    r.addCacheSlot("system");
    r.addCacheSlot("system");
    expect(r.toPayload(OWN).cache_write_slots).toEqual(["system"]);
    const taken = r.consumeCacheSlots();
    expect(taken).toEqual(["system"]);
    expect(r.consumeCacheSlots()).toEqual([]);
    r.addCacheSlot("tools"); // accrued while the save was in flight
    r.restoreCacheSlots(taken);
    expect(r.consumeCacheSlots()).toEqual(["system", "tools"]);
  });

  it("appendJournal dedupes by (id, source)", () => {
    const r = new ChatSessionRecord();
    r.appendJournal([{ id: "a", source: "mention" } as never]);
    r.appendJournal([{ id: "a", source: "mention" } as never, { id: "a", source: "tag" } as never]);
    expect(r.journal).toHaveLength(2);
  });
});
