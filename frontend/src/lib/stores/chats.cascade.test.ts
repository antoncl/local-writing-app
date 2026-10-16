// #2347: every cascading delete reconciles the chats it took with it. The three
// helpers in chats.ts — the confirm line, the post-delete roster diff that closes
// vanished chats' tabs, and the wrapper — plus one wired path (a plot-board card).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import { chatCascadeLine, chatSessionsStore, reconcileCascadedChats, withChatCascade } from "@/lib/stores/chats";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { deleteCard } from "@/lib/stores/plotBoard";
import { createEmptyEditorPane, type EditorPaneState, type DocumentRef } from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument } from "@/lib/types";

function paneOn(paneId: string, type: DocumentRef["type"], docId: string): EditorPaneState {
  return {
    ...createEmptyEditorPane(paneId),
    document: { type, id: docId },
    scene: { id: docId, title: docId, body: "", revision: "r1", entry_type: "x", metadata: {}, computed_metadata: {} } as unknown as EditableDocument,
  };
}

const chat = (id: string, subject: string | null, title = id) => ({ id, title, subject }) as never;

beforeEach(() => {
  editorPanes.reset();
  vi.restoreAllMocks();
  chatSessionsStore.set([chat("chat_a", "node_1", "Revise it"), chat("chat_b", "node_2"), chat("chat_free", null)]);
  editorPanes.panes = [paneOn("pane_a", "chat", "chat_a"), paneOn("pane_free", "chat", "chat_free")];
});

afterEach(() => {
  editorPanes.reset();
  chatSessionsStore.set([]);
});

describe("reconcileCascadedChats", () => {
  it("closes the tabs of chats that vanished, leaves the others, and clears activeChatId", async () => {
    vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [chat("chat_b", "node_2"), chat("chat_free", null)] });
    editorPanes.activeChatId = "chat_a";
    const gone = await reconcileCascadedChats();
    expect(gone).toEqual(["chat_a"]);
    expect(editorPanes.panes.map((p) => p.id)).toEqual(["pane_free"]);
    expect(editorPanes.activeChatId).toBeNull();
    expect(get(chatSessionsStore).map((s) => s.id)).toEqual(["chat_b", "chat_free"]);
  });

  it("keeps activeChatId when its chat survived", async () => {
    vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [chat("chat_free", null)] });
    editorPanes.activeChatId = "chat_free";
    await reconcileCascadedChats();
    expect(editorPanes.activeChatId).toBe("chat_free");
  });

  it("changes nothing when the fetch fails", async () => {
    vi.spyOn(api, "listChatSessions").mockRejectedValue(new Error("offline"));
    editorPanes.activeChatId = "chat_a";
    expect(await reconcileCascadedChats()).toEqual([]);
    expect(editorPanes.panes.map((p) => p.id)).toEqual(["pane_a", "pane_free"]);
    expect(editorPanes.activeChatId).toBe("chat_a");
    expect(get(chatSessionsStore)).toHaveLength(3);
  });
});

describe("withChatCascade", () => {
  it("reconciles after a successful delete and returns its result", async () => {
    const list = vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [chat("chat_free", null)] });
    const result = await withChatCascade(async () => "done");
    expect(result).toBe("done");
    expect(list).toHaveBeenCalledTimes(1);
    expect(editorPanes.panes.map((p) => p.id)).toEqual(["pane_free"]);
  });

  it("rethrows a failed delete and reconciles nothing", async () => {
    const list = vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [] });
    await expect(withChatCascade(() => Promise.reject(new Error("409")))).rejects.toThrow("409");
    expect(list).not.toHaveBeenCalled();
    expect(editorPanes.panes).toHaveLength(2);
  });
});

describe("chatCascadeLine", () => {
  it("is null when no chat is about the subjects", () => {
    expect(chatCascadeLine(["node_unrelated"])).toBeNull();
    expect(chatCascadeLine([])).toBeNull();
  });

  it("carries the #2345 sentence for one subject", () => {
    expect(chatCascadeLine(["node_1"])).toBe(
      'This also deletes 1 chat about it ("Revise it") — the conversation is removed with it.',
    );
  });

  it("counts chats across several subject ids", () => {
    const line = chatCascadeLine(["node_1", "node_2"]);
    expect(line).toContain("This also deletes 2 chats about it");
    expect(line).toContain('"Revise it", "chat_b"');
  });
});

describe("a wired path: deleting a plot card", () => {
  it("names the chat in the confirm line and closes its tab before the card's own pane", async () => {
    editorPanes.panes = [paneOn("pane_card", "plot_card", "node_1"), paneOn("pane_a", "chat", "chat_a")];
    expect(chatCascadeLine(["node_1"])).toContain("1 chat about it");
    vi.spyOn(api, "deleteCard").mockResolvedValue(undefined as never);
    vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [chat("chat_b", "node_2")] });
    await deleteCard("node_1", false);
    // The card's pane is still up (the caller tears it down next); the chat's is gone.
    expect(editorPanes.panes.map((p) => p.id)).toEqual(["pane_card"]);
  });
});
