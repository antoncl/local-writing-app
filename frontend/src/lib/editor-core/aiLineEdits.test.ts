// @vitest-environment happy-dom
// #2460: the controller's line-edits path. Real TipTap editor + the real
// AiSuggestionController + the real review plugin; only `api.aiGenerateStream` is faked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { proseStarterKit } from "./proseStarterKit";
import { AiSuggestionController } from "./aiSuggestion.svelte";
import { LineEditSuggestions, acceptLineEdit, lineEditState, rejectLineEdit } from "./lineEditSuggestions";

const editors: Editor[] = [];
beforeEach(() => {
  vi.spyOn(api, "aiAppendInvocation").mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const editor of editors.splice(0)) editor.destroy();
});

const TEXT = "The cat sat on the mat.";
const ENTRY = {
  id: "p1",
  title: "Line edit",
  body: "x",
  entry_type: "prompt:general",
  offer_on: ["manuscript:scene"],
  context_strategy: { output: { handler: "inline_edits" } },
} as never;

function setup() {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: TEXT }] }] },
  });
  editors.push(editor);
  const notices: string[] = [];
  const costs: number[] = [];
  const sceneId = { current: "scene_1" };
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: sceneId.current, entry_type: "manuscript:scene" }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ metadataSchema: { entry_types: {}, fields: {} }, promptEntries: [ENTRY] }) as never,
    onInvocationCost: (c) => costs.push(c),
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onNotice: (m) => notices.push(m),
    onOpenChat: () => {},
  });
  editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
  return { editor, ctrl, notices, costs, sceneId };
}

const reply = (over: Record<string, unknown> = {}) =>
  ({
    ok: true,
    content: "",
    provider: "p",
    model: "m",
    latency_ms: 1,
    truncated: false,
    cost_usd: 0.01,
    edits: [
      { find: "cat", replace: "dog", reason: "livelier" },
      { find: "mat", replace: "rug", reason: "fresher" },
    ],
    ...over,
  }) as never;

// A line-edit run rides the streaming route (#2464): a delta, then the `done` line
// that carries the parsed edits.
const fakeStream = (done: unknown) =>
  vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
    yield { type: "delta", text: "{}" } as never;
    yield { type: "done", ...(done as object) } as never;
  });

// A stream that never answers: `release(reply)` ends it with a `done` line.
function pendingStream() {
  let release!: (done: unknown) => void;
  const gate = new Promise<unknown>((r) => (release = r));
  const spy = vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
    yield { type: "done", ...((await gate) as object) } as never;
  });
  return { spy, release };
}

describe("line edits (#2460)", () => {
  it("sends response_format line_edits and installs the edits without touching the doc", async () => {
    const { editor, ctrl, costs } = setup();
    const spy = fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(spy.mock.calls[0][0]).toMatchObject({
      response_format: "line_edits",
      selection: TEXT,
      target_scene_id: "scene_1",
      commit: false,
      // Every selection run names the pills before it (#2491); none here.
      markers_before_selection: [],
    });
    expect(editor.state.doc.textContent).toBe(TEXT);
    expect(lineEditState(editor.state).edits).toHaveLength(2);
    expect(ctrl.lineEdits).toEqual({ remaining: 2, index: 1, currentReason: "livelier" });
    expect(ctrl.generating).toBe(false);
    expect(ctrl.meta?.model).toBe("m");
    expect(costs).toEqual([0.01]);
  });

  it("surfaces a backend error and installs nothing", async () => {
    const { editor, ctrl } = setup();
    fakeStream(reply({ ok: false, error: "cut off", edits: null }));
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toBe("cut off");
    expect(ctrl.lineEdits).toBeNull();
    expect(lineEditState(editor.state).edits).toHaveLength(0);
  });

  it("surfaces a stream error event and installs nothing", async () => {
    const { ctrl } = setup();
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield { type: "error", error: "provider down" } as never;
    });
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toBe("provider down");
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.generating).toBe(false);
  });

  it("tells the writer when edits were skipped, and when none could be placed", async () => {
    const a = setup();
    fakeStream(
      reply({ edits: [{ find: "cat", replace: "dog", reason: "r" }, { find: "ghost", replace: "x", reason: "r" }] }),
    );
    await a.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(a.ctrl.lineEdits).toMatchObject({ remaining: 1 });
    expect(a.notices).toEqual(["1 edit couldn't be matched to the text and was skipped."]);

    const b = setup();
    fakeStream(reply({ edits: [{ find: "ghost", replace: "x", reason: "r" }] }));
    await b.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(b.ctrl.lineEdits).toBeNull();
    expect(b.notices).toEqual(["None of the 1 suggested edits could be placed."]);

    const c = setup();
    fakeStream(reply({ edits: [] }));
    await c.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(c.notices).toEqual(["No edits suggested."]);
  });

  it("refuses to show edits when the selected text changed during the call", async () => {
    const { editor, ctrl } = setup();
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      editor.view.dispatch(editor.state.tr.insertText("Oh. ", 1));
      yield { type: "done", ...(reply() as object) } as never;
    });
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toMatch(/Document changed during the AI call/);
    expect(ctrl.lineEdits).toBeNull();
  });

  it("refuses another run while edits are pending, with a visible notice (not a hidden error)", async () => {
    const { ctrl, notices } = setup();
    const spy = fakeStream(reply());
    await ctrl.runPromptEntry(ENTRY, {});
    expect(notices).toEqual([]);
    await ctrl.runPromptEntry(ENTRY, {});
    expect(spy).toHaveBeenCalledTimes(1);
    expect(notices).toEqual(["Finish reviewing the line edits first — accept or reject them, or Reject all."]);
    expect(ctrl.error).toBeNull();
  });

  it("records one invocation when the last edit is resolved after an accept", async () => {
    const { editor, ctrl } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    const [first, second] = lineEditState(editor.state).edits;
    acceptLineEdit(editor.view, first.id);
    expect(ctrl.lineEdits).toMatchObject({ remaining: 1, index: 1, currentReason: "fresher" });
    expect(api.aiAppendInvocation).not.toHaveBeenCalled();
    rejectLineEdit(editor.view, second.id);
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.meta).toBeNull();
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
    expect(editor.state.doc.textContent).toBe("The dog sat on the mat.");
  });

  it("records nothing when every edit is rejected", async () => {
    const { ctrl } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.rejectAllLineEdits();
    expect(ctrl.lineEdits).toBeNull();
    expect(api.aiAppendInvocation).not.toHaveBeenCalled();
  });

  it("accept all applies everything and records the invocation", async () => {
    const { editor, ctrl } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.acceptAllLineEdits();
    expect(editor.state.doc.textContent).toBe("The dog sat on the rug.");
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("discards a reply that lands after reset() (document switch)", async () => {
    const { editor, ctrl, costs } = setup();
    const { spy, release } = pendingStream();
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    ctrl.reset();
    release(reply());
    await run;
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.error).toBeNull();
    expect(costs).toEqual([]);
    expect(ctrl.generating).toBe(false);
  });

  it("discards a reply that lands after the scene changed", async () => {
    const { editor, ctrl, costs, sceneId } = setup();
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      sceneId.current = "scene_2";
      yield { type: "done", ...(reply() as object) } as never;
    });
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.error).toBeNull();
    expect(costs).toEqual([]);
    expect(ctrl.generating).toBe(false);
  });

  // A fetch that never answers and rejects the way the real one does on abort.
  const hangingFetch = () =>
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* (_payload, signal) {
      await new Promise<void>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
      yield* [] as never[];
    });

  it("cancelGeneration aborts the request: nothing installed, no error, no cost (#2464)", async () => {
    const { editor, ctrl, costs, notices } = setup();
    const spy = hangingFetch();
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    expect(ctrl.generating).toBe(true);
    expect(spy.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
    ctrl.cancelGeneration();
    await run;
    expect(ctrl.generating).toBe(false);
    expect(ctrl.error).toBeNull();
    expect(ctrl.lineEdits).toBeNull();
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(costs).toEqual([]);
    expect(notices).toEqual(["Line edit cancelled."]);
    // and the controller is usable again
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.lineEdits).toMatchObject({ remaining: 2 });
  });

  it("a reply that races the abort installs nothing (#2464)", async () => {
    const { editor, ctrl, costs } = setup();
    const { spy, release } = pendingStream();
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    ctrl.cancelGeneration();
    release(reply());
    await run;
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(costs).toEqual([]);
    expect(ctrl.error).toBeNull();
    expect(ctrl.generating).toBe(false);
  });

  it("leaving the document (reset) aborts the running request, without a cancel notice (#2464)", async () => {
    const { ctrl, notices } = setup();
    const spy = hangingFetch();
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    const signal = spy.mock.calls[0][1] as AbortSignal;
    ctrl.reset();
    expect(signal.aborted).toBe(true);
    await run;
    expect(ctrl.generating).toBe(false);
    expect(ctrl.error).toBeNull();
    expect(notices).toEqual([]);
  });

  it("cancelGeneration with nothing running is a no-op (#2464)", () => {
    const { ctrl } = setup();
    expect(() => ctrl.cancelGeneration()).not.toThrow();
  });

  it("reset() removes the pending edits from the editor", async () => {
    const { editor, ctrl } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(lineEditState(editor.state).edits).toHaveLength(2);
    ctrl.reset();
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(editor.view.dom.querySelectorAll(".line-edit-old")).toHaveLength(0);
    expect(ctrl.lineEdits).toBeNull();
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("reset() with a destroyed editor does not throw", async () => {
    const { editor, ctrl } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    editor.destroy();
    expect(() => ctrl.reset()).not.toThrow();
    expect(ctrl.lineEdits).toBeNull();
  });

  it("retry rejects what is left and asks again on the same text", async () => {
    const { editor, ctrl } = setup();
    const spy = fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    await ctrl.retry();
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[1][0].selection).toBe(TEXT);
    expect(editor.state.doc.textContent).toBe(TEXT);
    expect(ctrl.lineEdits).toMatchObject({ remaining: 2 });
  });

  it("collapses the selection when the edits are installed", async () => {
    const { editor, ctrl } = setup();
    fakeStream(reply());
    expect(editor.state.selection.empty).toBe(false);
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(editor.state.selection.empty).toBe(true);
    expect(editor.state.selection.to).toBe(editor.state.doc.content.size - 1);
  });

  it("next / prev move the current edit and its reason; accept/reject current advance it", async () => {
    const { editor, ctrl } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.nextLineEdit();
    expect(ctrl.lineEdits).toEqual({ remaining: 2, index: 2, currentReason: "fresher" });
    ctrl.nextLineEdit();
    expect(ctrl.lineEdits).toMatchObject({ index: 1, currentReason: "livelier" });
    ctrl.prevLineEdit();
    expect(ctrl.lineEdits).toMatchObject({ index: 2 });
    ctrl.rejectCurrentLineEdit();
    expect(editor.state.doc.textContent).toBe(TEXT);
    expect(ctrl.lineEdits).toEqual({ remaining: 1, index: 1, currentReason: "livelier" });
    ctrl.acceptCurrentLineEdit();
    expect(editor.state.doc.textContent).toBe("The dog sat on the mat.");
    expect(ctrl.lineEdits).toBeNull();
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });
});
