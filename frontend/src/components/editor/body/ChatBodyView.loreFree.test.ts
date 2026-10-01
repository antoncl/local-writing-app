// @vitest-environment happy-dom
// ADR-0092 Amendment 1 §3: a chat whose prompt called `no_lore()` is persisted
// as `lore_free`. A save always sends the HYDRATED value, so a missed hydrate in
// `applyChatSession` would reset a lore-free chat on its first save after a
// reopen. This mounts the real view over a stored lore-free chat, triggers a
// save (a title rename from the pane), and asserts the payload echoes it.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@/lib/test/component";
import { api } from "@/lib/api";
import ChatBodyView from "./ChatBodyView.svelte";
import type { ChatSession, EditableDocument } from "@/lib/types";

// The rename's follow-up roster refresh would hit the network; it is not under test.
vi.mock("@/lib/stores/chats", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/stores/chats")>()),
  refreshChatSessions: vi.fn(async () => {}),
}));

const CHAT_ID = "chat_lorefree1";

function storedChat(over: Partial<ChatSession> = {}): ChatSession {
  return {
    id: CHAT_ID,
    title: "Research",
    prompt_entry_id: "prompt_r",
    assistant_id: "",
    system_prompt: "Locked system prompt.",
    messages: [],
    journal: [],
    lore_enabled: false,
    lore_free: true,
    ...over,
  } as unknown as ChatSession;
}

async function saveAfterRename(session: ChatSession): Promise<Record<string, unknown>> {
  vi.spyOn(api, "readNode").mockResolvedValue(session as never);
  const save = vi.spyOn(api, "saveNode").mockImplementation(async (_id, payload) => ({
    ...session,
    ...(payload as object),
  }) as never);
  const { component } = render(ChatBodyView, { scene: { id: CHAT_ID } as unknown as EditableDocument });
  // The load is async (readNode → applyChatSession); wait until it has landed.
  await vi.waitFor(() => expect(api.readNode).toHaveBeenCalled());
  await new Promise((resolve) => setTimeout(resolve, 0));
  (component as unknown as { setTitleFromPane: (t: string) => void }).setTitleFromPane("Renamed");
  await vi.waitFor(() => expect(save).toHaveBeenCalled(), { timeout: 2000 });
  return save.mock.calls[0][1] as Record<string, unknown>;
}

describe("ChatBodyView lore_free", () => {
  afterEach(() => vi.restoreAllMocks());

  it("hydrates lore_free from the stored chat, so a save echoes it back", async () => {
    const payload = await saveAfterRename(storedChat({ lore_free: true }));
    expect(payload.lore_free).toBe(true);
    expect(payload.lore_enabled).toBe(false);
  });

  it("a chat that is not lore-free saves lore_free false", async () => {
    const payload = await saveAfterRename(storedChat({ lore_free: false }));
    expect(payload.lore_free).toBe(false);
  });
});
