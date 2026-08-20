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

  it("does not refresh for a subject-less chat (e.g. a scene chat)", async () => {
    await chatSessions.openChatFromPromptEntry(PROMPT, {}, null, {});
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
  });
});
