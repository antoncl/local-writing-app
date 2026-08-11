import { describe, expect, it } from "vitest";
import type { ChatSessionSummary } from "@/lib/types";
import { conversationsFor } from "./conversations";

// A chat roster summary. Order in the array IS the resume-first order (the
// backend lists pinned-first then updated_at desc); the tests assert the filter
// preserves it.
function chat(over: Partial<ChatSessionSummary>): ChatSessionSummary {
  return {
    id: "c",
    title: "Chat",
    prompt_entry_id: "",
    assistant_id: "",
    pinned: false,
    created_at: "2026-08-01T00:00:00",
    updated_at: "2026-08-01T00:00:00",
    message_count: 0,
    ...over,
  };
}

// Build the reverse index (targetId → referrer ids) directly, the shape
// referenceIndexStore holds.
function reverse(pairs: Record<string, string[]>): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  for (const [target, referrers] of Object.entries(pairs)) map.set(target, new Set(referrers));
  return map;
}

describe("conversationsFor (ADR-0051 S3)", () => {
  it("returns the chats whose subject → the node, in roster (resume-first) order", () => {
    // Two chats reference the entry; a third does not. The reverse index carries
    // no ordering — the roster does, and the filter must preserve it.
    const roster = [
      chat({ id: "recent", updated_at: "2026-08-10T09:00:00" }),
      chat({ id: "older", updated_at: "2026-08-02T09:00:00" }),
      chat({ id: "unrelated" }),
    ];
    const index = reverse({ hero: ["older", "recent"] });
    expect(conversationsFor("hero", index, roster).map((c) => c.id)).toEqual(["recent", "older"]);
  });

  it("drops a referrer that is not a chat (not in the roster)", () => {
    // A scene and another lore entry can also reference the node; only roster
    // members (chats) survive the intersection.
    const roster = [chat({ id: "chat-1" })];
    const index = reverse({ hero: ["chat-1", "some-scene", "another-entry"] });
    expect(conversationsFor("hero", index, roster).map((c) => c.id)).toEqual(["chat-1"]);
  });

  it("returns [] for a node with no referrers", () => {
    const roster = [chat({ id: "chat-1" })];
    expect(conversationsFor("lonely", reverse({}), roster)).toEqual([]);
  });

  it("returns [] for an empty subject id", () => {
    const roster = [chat({ id: "chat-1" })];
    expect(conversationsFor("", reverse({ "": ["chat-1"] }), roster)).toEqual([]);
  });

  it("returns [] when the reverse index is unloaded", () => {
    expect(conversationsFor("hero", null, [chat({ id: "chat-1" })])).toEqual([]);
  });
});
