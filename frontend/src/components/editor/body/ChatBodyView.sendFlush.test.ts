// @vitest-environment happy-dom
// #2587: a chat send reads what it places (the scene, picks, lore) from disk,
// and an editor pane saves only after 6s idle. So Send must persist every dirty
// pane BEFORE the turn goes out — otherwise an edit made just before Send ships
// as the previous saved version. This mounts the real view, seeds the composer,
// clicks Send, and asserts the flush finished before the stream was requested.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@/lib/test/component";
import { api } from "@/lib/api";
import { composerPrefills } from "@/lib/stores/composerPrefill.svelte";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import ChatBodyView from "./ChatBodyView.svelte";
import type { ChatSession, EditableDocument } from "@/lib/types";

vi.mock("@/lib/stores/chats", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/stores/chats")>()),
  refreshChatSessions: vi.fn(async () => {}),
}));

const CHAT_ID = "chat_sendflush1";

function storedChat(): ChatSession {
  return {
    id: CHAT_ID,
    title: "Doctor",
    prompt_entry_id: "",
    assistant_id: "",
    system_prompt: "Locked system prompt.",
    messages: [
      { role: "user", content: "Diagnose it." },
      { role: "assistant", content: "Turn one report." },
    ],
    journal: [],
    lore_enabled: false,
    lore_free: false,
  } as unknown as ChatSession;
}

describe("ChatBodyView send (#2587)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    composerPrefills.clear(CHAT_ID);
  });

  it("persists dirty editor panes before the turn is sent", async () => {
    const order: string[] = [];
    let releaseFlush: () => void = () => {};
    vi.spyOn(editorPanes, "flushDirtyPanes").mockImplementation(async () => {
      order.push("flush:start");
      await new Promise<void>((resolve) => (releaseFlush = resolve));
      order.push("flush:done");
      return true;
    });
    const stream = vi.spyOn(api, "aiChatStream").mockImplementation(async function* () {
      order.push("stream");
      yield { type: "done", truncated: false, provider: "mock", model: "mock" } as never;
    });
    vi.spyOn(api, "readNode").mockResolvedValue(storedChat() as never);
    vi.spyOn(api, "saveNode").mockImplementation(async (_id, payload) => ({
      ...storedChat(),
      ...(payload as object),
    }) as never);
    composerPrefills.set(CHAT_ID, "I rewrote the ending. Look again.");

    const { getByText } = render(ChatBodyView, {
      scene: { id: CHAT_ID } as unknown as EditableDocument,
    });
    await vi.waitFor(() => expect(api.readNode).toHaveBeenCalled());
    const send = await vi.waitFor(() => {
      const button = getByText("Send") as HTMLButtonElement;
      expect(button.disabled).toBe(false);
      return button;
    });
    send.click();

    // The flush is in flight: nothing has been sent yet.
    await vi.waitFor(() => expect(order).toContain("flush:start"));
    expect(stream).not.toHaveBeenCalled();

    releaseFlush();
    await vi.waitFor(() => expect(stream).toHaveBeenCalled());
    expect(order).toEqual(["flush:start", "flush:done", "stream"]);
  });
});
