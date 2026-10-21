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
  // Mutable, so a test can move the pane to another document mid-save.
  const current = { sceneId: "scene_1" };
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: current.sceneId, entry_type: "manuscript:scene" }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ promptEntries: [] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onOpenChat: () => {},
    persistEdits,
  });
  return { editor, ctrl, current };
}

const DONE = { type: "done", provider: "p", model: "m", latency_ms: 1, truncated: false } as never;

/** A persist that holds until released, so a test can act mid-save. */
function heldPersist() {
  let release: () => void = () => {};
  const persist = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
  return { persist, release: () => release() };
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

  it("ignores a double submit straight from the inputs dialog", async () => {
    // The dialog calls `runPromptEntryWithInputs` directly, past `runPromptEntry`.
    const { persist, release } = heldPersist();
    const { ctrl } = setup(persist);
    const call = vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield DONE;
    });

    const first = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(persist).toHaveBeenCalledTimes(1));
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    release();
    await first;

    expect(persist).toHaveBeenCalledTimes(1);
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("drops the run when the pane moves to another document during the save", async () => {
    const { persist, release } = heldPersist();
    const { editor, ctrl, current } = setup(persist);
    const call = vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield { type: "delta", text: "Scene A's continuation." } as never;
      yield DONE;
    });

    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(persist).toHaveBeenCalled());
    current.sceneId = "scene_2"; // the writer opened another scene in this pane
    release();
    await run;

    expect(call).not.toHaveBeenCalled();
    expect(editor.state.doc.textContent).toBe("Draft.");
    expect(ctrl.generating).toBe(false);
  });

  it("drops the run when the controller is reset during the save", async () => {
    const { persist, release } = heldPersist();
    const { ctrl } = setup(persist);
    const call = vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield DONE;
    });

    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(persist).toHaveBeenCalled());
    ctrl.reset();
    release();
    await run;

    expect(call).not.toHaveBeenCalled();
  });

  it("line edits save first too — the flush sits ahead of every editor handler", async () => {
    const order: string[] = [];
    const { editor, ctrl } = setup(async () => {
      order.push("persist");
    });
    editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      order.push("call");
      yield { ...(DONE as object), line_edits: [] } as never;
    });
    const lineEdits = {
      ...(ENTRY as object),
      context_strategy: { output: { handler: "inline_edits" } },
    } as never;

    await ctrl.runPromptEntryWithInputs(lineEdits, {});

    expect(order).toEqual(["persist", "call"]);
  });
});
