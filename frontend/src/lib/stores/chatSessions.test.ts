// ADR-0051 S3 — the live reverse-index refresh on chat creation. The Conversations
// surface reads the in-memory reverse index; a chat's creation path bypasses
// saveEditorPane's change-gated refresh, so `openChatFromPromptEntry` refreshes
// the index itself when it stamps a `subject`. Without it the surface stays stale
// until reload and the writer re-spawns the very duplicate S3 removes — so this
// pins that a subject-stamped create refreshes and a subject-less one does not.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Stub only the refresh fn; keep the rest of the module real so every other
// importer (editorPanes, …) still resolves its exports.
vi.mock("@/lib/stores/references", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/stores/references")>()),
  refreshReferenceIndexInBackground: vi.fn(),
}));

import { api } from "@/lib/api";
import { chatSessions } from "@/lib/stores/chatSessions.svelte";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { refreshReferenceIndexInBackground } from "@/lib/stores/references";
import type { PromptEntrySummary } from "@/lib/types";

const PROMPT = { id: "p1", title: "Revise entry", inputs: [] } as unknown as PromptEntrySummary;

beforeEach(() => {
  vi.spyOn(api, "createChatSession").mockResolvedValue({ id: "chat-1", title: "T" } as never);
  vi.spyOn(api, "listChatSessions").mockResolvedValue({ sessions: [] } as never);
  vi.spyOn(editorPanes, "openChat").mockResolvedValue(undefined);
  vi.spyOn(api, "resolveReferences").mockResolvedValue({
    candidates: [
      { id: "lysandra", title: "Lysandra", kind: "lore", entry_type: "lore:character", summary: "", found: true },
      { id: "scene-7", title: "The Hook", kind: "manuscript", entry_type: "manuscript:scene", summary: "", found: true },
    ],
  } as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(refreshReferenceIndexInBackground).mockClear();
});

describe("openChatFromPromptEntry — reverse-index refresh (ADR-0051 S3)", () => {
  it("refreshes the reverse index when the new chat is stamped with a subject", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, { subject: "hero" });
    expect(refreshReferenceIndexInBackground).toHaveBeenCalledTimes(1);
  });

  it("resolves to the created session's id (ADR-0090 §4: Propose needs it to prefill)", async () => {
    const chatId = await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, { subject: "hero" });
    expect(chatId).toBe("chat-1");
  });

  it("does not refresh for a subject-less chat (e.g. a scene chat)", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, {});
    expect(refreshReferenceIndexInBackground).not.toHaveBeenCalled();
  });
});

// #2309 review: a chat deleted by id (Chats pane ×, Conversations row ×) drops
// its outgoing refs, so the reverse index must rebuild — as the header Delete does.
describe("deleteChatSessionFromPane — reverse-index refresh (#2309)", () => {
  it("refreshes the reverse index after a successful delete", async () => {
    vi.spyOn(api, "deleteChatSession").mockResolvedValue({ sessions: [] } as never);
    await chatSessions.deleteChatSessionFromPane("chat-1");
    expect(refreshReferenceIndexInBackground).toHaveBeenCalledTimes(1);
  });

  it("does not refresh when the delete fails", async () => {
    vi.spyOn(api, "deleteChatSession").mockRejectedValue(new Error("boom"));
    await chatSessions.deleteChatSessionFromPane("chat-1");
    expect(refreshReferenceIndexInBackground).not.toHaveBeenCalled();
  });
});

describe("openChatFromPromptEntry — chat title (#695)", () => {
  it("titleOverride names the chat wholesale, replacing the dual-mode prompt title", async () => {
    // A create-mode brainstorm names itself "Draft <Type>" rather than inheriting
    // the prompt's "Revise entry" title, which reads wrong for a create flow.
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, { titleOverride: "Draft Character" });
    expect(api.createChatSession).toHaveBeenCalledWith(expect.objectContaining({ title: "Draft Character" }));
  });

  it("falls back to '<subject> — <prompt>' when no override is given (revise launch)", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, { subjectTitle: "Aurora" });
    expect(api.createChatSession).toHaveBeenCalledWith(expect.objectContaining({ title: "Aurora — Revise entry" }));
  });

  it("falls back to the bare prompt title when neither override nor subject is given", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, {});
    expect(api.createChatSession).toHaveBeenCalledWith(expect.objectContaining({ title: "Revise entry" }));
    expect(api.resolveReferences).not.toHaveBeenCalled();
  });

  // #2314: a subject-anchored launch that doesn't know its subject's title (the
  // lock doorway, a scene's prompt invocation) resolves it, so the chat reads
  // "<subject> — <prompt>" like every other subject-anchored chat.
  it("resolves the subject's title when the caller passes only a subject id (lock doorway)", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, "lysandra", {});
    expect(api.resolveReferences).toHaveBeenCalledWith(["lysandra"]);
    expect(api.createChatSession).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Lysandra — Revise entry", subject: "lysandra" }),
    );
  });

  it("resolves an explicit subject too, when no title comes with it", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, { subject: "scene-7" });
    expect(api.createChatSession).toHaveBeenCalledWith(expect.objectContaining({ title: "The Hook — Revise entry" }));
  });

  it("keeps the bare prompt title when the subject can't be found", async () => {
    vi.mocked(api.resolveReferences).mockResolvedValueOnce({
      candidates: [{ id: "gone", title: "gone", kind: "", entry_type: "", summary: "", found: false }],
    } as never);
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, "gone", {});
    expect(api.createChatSession).toHaveBeenCalledWith(expect.objectContaining({ title: "Revise entry" }));
  });

  it("keeps the bare prompt title when the lookup fails", async () => {
    vi.mocked(api.resolveReferences).mockRejectedValueOnce(new Error("offline"));
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, "lysandra", {});
    expect(api.createChatSession).toHaveBeenCalledWith(expect.objectContaining({ title: "Revise entry" }));
  });

  it("does not look the subject up when the caller already named it", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, { subject: "lysandra", subjectTitle: "Lys" });
    expect(api.resolveReferences).not.toHaveBeenCalled();
    expect(api.createChatSession).toHaveBeenCalledWith(expect.objectContaining({ title: "Lys — Revise entry" }));
  });
});
