// @vitest-environment happy-dom
// #2596: an editor prompt's template reads the scene, picks and lore from disk,
// and an idle autosave may still be seconds away — so an inline run persists
// pending edits first (`persistEdits`), before anything in the document changes
// and before the call. Saving is not generating, and a second run meanwhile is
// ignored. Real TipTap editor + the real controller; only the API is faked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { AISuggestion } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import { AiSuggestionController } from "./aiSuggestion.svelte";

const editors: Editor[] = [];
beforeEach(() => {
  vi.spyOn(api, "aiAppendInvocation").mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const editor of editors.splice(0)) editor.destroy();
});

const ENTRY = {
  id: "p1",
  title: "P",
  body: "x",
  entry_type: "prompt:general",
  // Offered on scenes, so a second `runPromptEntry` reaches the in-flight guard
  // rather than stopping at the offer check.
  offer_on: ["manuscript:scene"],
  context_strategy: { output: { handler: "inline" } },
} as never;

function setup(persistEdits: () => Promise<void>) {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), AISuggestion],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Draft." }] }] },
  });
  editors.push(editor);
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: "scene_1", entry_type: "manuscript:scene" }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ promptEntries: [] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onOpenChat: () => {},
    persistEdits,
  });
  return { editor, ctrl };
}

describe("inline run persists pending edits first (#2596)", () => {
  it("saves before the call, while the document is still untouched", async () => {
    const order: string[] = [];
    let docAtPersist = "";
    const { editor, ctrl } = setup(async () => {
      docAtPersist = editor.state.doc.textContent;
      order.push("persist");
    });
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      order.push("call");
      yield { type: "done", provider: "p", model: "m", latency_ms: 1, truncated: false } as never;
    });

    await ctrl.runPromptEntryWithInputs(ENTRY, {});

    expect(order).toEqual(["persist", "call"]);
    expect(docAtPersist).toBe("Draft.");
  });

  it("doesn't show generating while saving, and ignores a second run meanwhile", async () => {
    let release: () => void = () => {};
    const persist = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    const { ctrl } = setup(persist);
    const call = vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield { type: "done", provider: "p", model: "m", latency_ms: 1, truncated: false } as never;
    });

    const first = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(persist).toHaveBeenCalledTimes(1));
    expect(ctrl.generating).toBe(false);
    await ctrl.runPromptEntry(ENTRY, {}); // ignored: a save is in flight
    expect(persist).toHaveBeenCalledTimes(1);

    release();
    await first;
    expect(call).toHaveBeenCalledTimes(1);
  });
});
