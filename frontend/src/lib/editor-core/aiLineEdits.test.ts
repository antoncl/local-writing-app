// @vitest-environment happy-dom
// #2460: the controller's line-edits path. Real TipTap editor + the real
// AiSuggestionController + the real review plugin; only `api.aiGenerate` is faked.
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
    getScene: () => ({ id: sceneId.current }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ promptEntries: [ENTRY] }) as never,
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

describe("line edits (#2460)", () => {
  it("sends response_format line_edits and installs the edits without touching the doc", async () => {
    const { editor, ctrl, costs } = setup();
    const spy = vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(spy.mock.calls[0][0]).toMatchObject({
      response_format: "line_edits",
      selection: TEXT,
      target_scene_id: "scene_1",
      commit: false,
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
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply({ ok: false, error: "cut off", edits: null }));
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toBe("cut off");
    expect(ctrl.lineEdits).toBeNull();
    expect(lineEditState(editor.state).edits).toHaveLength(0);
  });

  it("tells the writer when edits were skipped, and when none could be placed", async () => {
    const a = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(
      reply({ edits: [{ find: "cat", replace: "dog", reason: "r" }, { find: "ghost", replace: "x", reason: "r" }] }),
    );
    await a.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(a.ctrl.lineEdits).toMatchObject({ remaining: 1 });
    expect(a.notices).toEqual(["1 edit couldn't be matched to the text and was skipped."]);

    const b = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply({ edits: [{ find: "ghost", replace: "x", reason: "r" }] }));
    await b.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(b.ctrl.lineEdits).toBeNull();
    expect(b.notices).toEqual(["None of the 1 suggested edits could be placed."]);

    const c = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply({ edits: [] }));
    await c.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(c.notices).toEqual(["No edits suggested."]);
  });

  it("refuses to show edits when the selected text changed during the call", async () => {
    const { editor, ctrl } = setup();
    vi.spyOn(api, "aiGenerate").mockImplementation(async () => {
      editor.view.dispatch(editor.state.tr.insertText("Oh. ", 1));
      return reply();
    });
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toMatch(/Document changed during the AI call/);
    expect(ctrl.lineEdits).toBeNull();
  });

  it("refuses another run while edits are pending, with a visible notice (not a hidden error)", async () => {
    const { ctrl, notices } = setup();
    const spy = vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntry(ENTRY, {});
    expect(notices).toEqual([]);
    await ctrl.runPromptEntry(ENTRY, {});
    expect(spy).toHaveBeenCalledTimes(1);
    expect(notices).toEqual(["Finish reviewing the line edits first — accept or reject them, or Reject all."]);
    expect(ctrl.error).toBeNull();
  });

  it("records one invocation when the last edit is resolved after an accept", async () => {
    const { editor, ctrl } = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
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
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.rejectAllLineEdits();
    expect(ctrl.lineEdits).toBeNull();
    expect(api.aiAppendInvocation).not.toHaveBeenCalled();
  });

  it("accept all applies everything and records the invocation", async () => {
    const { editor, ctrl } = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.acceptAllLineEdits();
    expect(editor.state.doc.textContent).toBe("The dog sat on the rug.");
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("discards a reply that lands after reset() (document switch)", async () => {
    const { editor, ctrl, costs } = setup();
    let resolveReply!: (r: never) => void;
    const spy = vi.spyOn(api, "aiGenerate").mockReturnValue(new Promise((r) => (resolveReply = r)) as never);
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    ctrl.reset();
    resolveReply(reply());
    await run;
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.error).toBeNull();
    expect(costs).toEqual([]);
    expect(ctrl.generating).toBe(false);
  });

  it("discards a reply that lands after the scene changed", async () => {
    const { editor, ctrl, costs, sceneId } = setup();
    vi.spyOn(api, "aiGenerate").mockImplementation(async () => {
      sceneId.current = "scene_2";
      return reply();
    });
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.error).toBeNull();
    expect(costs).toEqual([]);
    expect(ctrl.generating).toBe(false);
  });

  it("reset() removes the pending edits from the editor", async () => {
    const { editor, ctrl } = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
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
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    editor.destroy();
    expect(() => ctrl.reset()).not.toThrow();
    expect(ctrl.lineEdits).toBeNull();
  });

  it("retry rejects what is left and asks again on the same text", async () => {
    const { editor, ctrl } = setup();
    const spy = vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    await ctrl.retry();
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[1][0].selection).toBe(TEXT);
    expect(editor.state.doc.textContent).toBe(TEXT);
    expect(ctrl.lineEdits).toMatchObject({ remaining: 2 });
  });

  it("collapses the selection when the edits are installed", async () => {
    const { editor, ctrl } = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    expect(editor.state.selection.empty).toBe(false);
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(editor.state.selection.empty).toBe(true);
    expect(editor.state.selection.to).toBe(editor.state.doc.content.size - 1);
  });

  it("next / prev move the current edit and its reason; accept/reject current advance it", async () => {
    const { editor, ctrl } = setup();
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
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
