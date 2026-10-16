// @vitest-environment happy-dom
// ADR-0100: the Place flags controller - transcript cut at the chosen reply, then
// show the scene beside the chat and install the flags in its pane.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import * as quoteReveal from "@/lib/stores/quoteReveal";
import { PlaceFlagsController } from "./placeFlags.svelte";
import type { ChatMessage } from "@/lib/types";

const HISTORY = [
  { role: "user", content: "Check the scene", provider: "x" },
  { role: "assistant", content: "Reply one", model: "m" },
  { role: "user", content: "And?" },
  { role: "assistant", content: "Reply two" },
] as ChatMessage[];

const OK = {
  ok: true,
  error: null,
  edits: [{ find: "a", replace: "b", reason: "r" }],
  notes: [{ quote: "q", problem: "p", entry_id: null, entry_name: null }],
  cost_usd: 0.01,
  cost_usd_total: 0.5,
};

function setup(over: { chatId?: string | null; sceneId?: string | null; plain?: string | null } = {}) {
  const setCostTotal = vi.fn();
  const ctrl = new PlaceFlagsController({
    getChat: () => ({ chatId: over.chatId === undefined ? "chat_1" : over.chatId, assistantId: "asst_1", history: HISTORY }),
    getScene: () => ({
      sceneId: over.sceneId === undefined ? "scene_1" : over.sceneId,
      plain: over.plain === undefined ? "Scene text." : over.plain,
    }),
    hostPaneId: () => "pane_chat",
    setCostTotal,
  });
  return { ctrl, setCostTotal };
}

let extract: ReturnType<typeof vi.spyOn>;
let show: ReturnType<typeof vi.spyOn>;
let install: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  extract = vi.spyOn(api, "extractFlags").mockResolvedValue(OK as never);
  show = vi.spyOn(quoteReveal, "showSceneBeside").mockResolvedValue(undefined);
  install = vi.spyOn(editorPanes, "installFlagsInOpenPane").mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

describe("PlaceFlagsController", () => {
  it("sends the transcript cut at the chosen reply, then shows the scene and installs the flags", async () => {
    const { ctrl, setCostTotal } = setup();
    await ctrl.place(1);
    expect(extract).toHaveBeenCalledWith({
      messages: [
        { role: "user", content: "Check the scene" },
        { role: "assistant", content: "Reply one" },
      ],
      assistant_id: "asst_1",
      chat_id: "chat_1",
      scene_text: "Scene text.",
    });
    expect(setCostTotal).toHaveBeenCalledWith(0.5);
    expect(show).toHaveBeenCalledWith("scene_1", "pane_chat");
    expect(install).toHaveBeenCalledWith("scene_1", { edits: OK.edits, notes: OK.notes });
    expect(show.mock.invocationCallOrder[0]).toBeLessThan(install.mock.invocationCallOrder[0]);
    expect(ctrl.placingIndex).toBeNull();
    expect(ctrl.notice).toBeNull();
  });

  it("says so, and installs nothing, when the reply had nothing to place", async () => {
    extract.mockResolvedValue({ ...OK, edits: [], notes: [] } as never);
    const { ctrl, setCostTotal } = setup();
    await ctrl.place(3);
    expect(ctrl.notice).toBe("That reply had nothing to place on the scene.");
    expect(setCostTotal).toHaveBeenCalledWith(0.5);
    expect(install).not.toHaveBeenCalled();
    expect(show).not.toHaveBeenCalled();
  });

  it("shows the error when the turn failed", async () => {
    extract.mockResolvedValue({ ...OK, ok: false, error: "model unreachable", edits: [], notes: [] } as never);
    const { ctrl } = setup();
    await ctrl.place(1);
    expect(ctrl.notice).toBe("model unreachable");
    expect(install).not.toHaveBeenCalled();
    expect(ctrl.placingIndex).toBeNull();
  });

  it("shows a thrown error and clears the busy state", async () => {
    extract.mockRejectedValue(new Error("network down"));
    const { ctrl } = setup();
    await ctrl.place(1);
    expect(ctrl.notice).toBe("network down");
    expect(ctrl.placingIndex).toBeNull();
  });

  it("refuses a second placement while one is in flight", async () => {
    let finish: (v: unknown) => void = () => {};
    extract.mockReturnValue(new Promise((resolve) => (finish = resolve)) as never);
    const { ctrl } = setup();
    const first = ctrl.place(1);
    expect(ctrl.placingIndex).toBe(1);
    await ctrl.place(3);
    expect(extract).toHaveBeenCalledTimes(1);
    finish(OK);
    await first;
    expect(ctrl.placingIndex).toBeNull();
  });

  it("does nothing without a scene or chat", async () => {
    await setup({ sceneId: null }).ctrl.place(1);
    await setup({ chatId: null }).ctrl.place(1);
    await setup({ plain: null }).ctrl.place(1);
    expect(extract).not.toHaveBeenCalled();
  });
});
