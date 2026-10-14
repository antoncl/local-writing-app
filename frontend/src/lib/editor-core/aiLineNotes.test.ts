// @vitest-environment happy-dom
// ADR-0098: the controller's lore-check (notes) path. Real TipTap editor + the real
// AiSuggestionController + the real review plugin; only `api.aiGenerateStream` is faked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { proseStarterKit } from "./proseStarterKit";
import { AiSuggestionController } from "./aiSuggestion.svelte";
import { LineEditSuggestions, lineEditState, lineNoteState } from "./lineEditSuggestions";
import { noteNotice } from "./aiLineNotes";

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
  title: "Lore check",
  body: "x",
  entry_type: "prompt:general",
  offer_on: ["manuscript:scene"],
  context_strategy: { output: { handler: "inline_notes" } },
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
  const opened: string[] = [];
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: "scene_1", entry_type: "manuscript:scene" }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ metadataSchema: { entry_types: {}, fields: {} }, promptEntries: [ENTRY] }) as never,
    onInvocationCost: (c) => costs.push(c),
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onNotice: (m) => notices.push(m),
    onOpenEntry: (id) => opened.push(id),
    onOpenChat: () => {},
  });
  editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
  return { editor, ctrl, notices, costs, opened };
}

const reply = (over: Record<string, unknown> = {}) =>
  ({
    ok: true,
    content: "",
    provider: "p",
    model: "m",
    latency_ms: 1,
    truncated: false,
    cost_usd: 0.02,
    notes: [
      { quote: "cat", problem: "Mira has no cat", entry: "lore_1" },
      { quote: "mat", problem: "No mats in the Keep", entry: "lore_2" },
    ],
    notes_dropped: 0,
    checked_against: [
      { id: "lore_1", name: "Mira" },
      { id: "lore_2", name: "The Keep" },
    ],
    ...over,
  }) as never;

const fakeStream = (done: unknown) =>
  vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
    yield { type: "delta", text: "{}" } as never;
    yield { type: "done", ...(done as object) } as never;
  });

describe("lore check notes (ADR-0098)", () => {
  it("sends response_format notes, installs the notes without touching the doc", async () => {
    const { editor, ctrl } = setup();
    const spy = fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(spy.mock.calls[0][0]).toMatchObject({
      response_format: "notes",
      selection: TEXT,
      target_scene_id: "scene_1",
      commit: false,
    });
    expect(editor.state.doc.textContent).toBe(TEXT);
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(ctrl.lineNotes).toEqual({
      remaining: 2,
      index: 1,
      checkedAgainst: [
        { id: "lore_1", name: "Mira" },
        { id: "lore_2", name: "The Keep" },
      ],
    });
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.generating).toBe(false);
    expect(ctrl.meta?.model).toBe("m");
  });

  it("records cost and the invocation on ARRIVAL, before any note is touched", async () => {
    const { ctrl, costs } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(costs).toEqual([0.02]);
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
    expect(api.aiAppendInvocation).toHaveBeenCalledWith(
      expect.objectContaining({ prompt_entry_id: "p1", scene_id: "scene_1", model: "m", cost_usd: 0.02 }),
    );
    // dismissing the notes records nothing more
    ctrl.dismissAllLineNotes();
    expect(ctrl.lineNotes).toBeNull();
    expect(ctrl.meta).toBeNull();
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("an empty reply still records the invocation and says so", async () => {
    const { ctrl, costs, notices, editor } = setup();
    fakeStream(reply({ notes: [] }));
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(notices).toEqual(["No contradictions found."]);
    expect(ctrl.lineNotes).toBeNull();
    expect(lineNoteState(editor.state).notes).toHaveLength(0);
    expect(costs).toEqual([0.02]);
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("tells the writer when none of the notes could be placed", async () => {
    const { ctrl, notices } = setup();
    fakeStream(reply({ notes: [{ quote: "ghost", problem: "p", entry: "lore_1" }] }));
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.lineNotes).toBeNull();
    expect(notices).toEqual(["The note couldn't be placed."]);
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("tells the writer when some notes were skipped (singular and plural)", async () => {
    const a = setup();
    fakeStream(reply({ notes: [{ quote: "cat", problem: "p", entry: "lore_1" }, { quote: "ghost", problem: "p", entry: "lore_1" }] }));
    await a.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(a.ctrl.lineNotes).toMatchObject({ remaining: 1 });
    expect(a.notices).toEqual(["1 note couldn't be matched and was skipped."]);

    const b = setup();
    fakeStream(
      reply({
        notes: [{ quote: "cat", problem: "p", entry: "lore_1" }, { quote: "ghost", problem: "p", entry: "lore_1" }, { quote: "phantom", problem: "p", entry: "lore_1" }],
      }),
    );
    await b.ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(b.notices).toEqual(["2 notes couldn't be matched and were skipped."]);
  });

  it("the dropped total sums the backend's drops and the placement's", async () => {
    const { ctrl, notices } = setup();
    fakeStream(
      reply({ notes_dropped: 2, notes: [{ quote: "cat", problem: "p", entry: "lore_1" }, { quote: "ghost", problem: "p", entry: "lore_1" }] }),
    );
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.lineNotes).toMatchObject({ remaining: 1 });
    expect(notices).toEqual(["3 notes couldn't be matched and were skipped."]);
  });

  it("backend-dropped notes alone (an empty list) count as none placed", async () => {
    const { ctrl, notices } = setup();
    fakeStream(reply({ notes: [], notes_dropped: 2 }));
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(notices).toEqual(["None of the 2 notes could be placed."]);
    expect(ctrl.lineNotes).toBeNull();
  });

  it("noteNotice covers each case", () => {
    expect(noteNotice(0, 0)).toBe("No contradictions found.");
    expect(noteNotice(0, 1)).toBe("The note couldn't be placed.");
    expect(noteNotice(0, 3)).toBe("None of the 3 notes could be placed.");
    expect(noteNotice(2, 0)).toBeNull();
    expect(noteNotice(2, 1)).toBe("1 note couldn't be matched and was skipped.");
    expect(noteNotice(2, 2)).toBe("2 notes couldn't be matched and were skipped.");
  });

  it("an unusable reply (cut off) installs nothing but its cost is still recorded", async () => {
    const { ctrl, editor, costs } = setup();
    fakeStream(reply({ ok: false, error: "cut off", notes: null }));
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toBe("cut off");
    expect(ctrl.lineNotes).toBeNull();
    expect(ctrl.meta).toBeNull();
    expect(lineNoteState(editor.state).notes).toHaveLength(0);
    expect(costs).toEqual([0.02]);
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("a stream that fails before finishing records nothing", async () => {
    const { ctrl, costs } = setup();
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield { type: "error", error: "provider down" } as never;
    });
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toBe("provider down");
    expect(costs).toEqual([]);
    expect(api.aiAppendInvocation).not.toHaveBeenCalled();
  });

  it("refuses to show notes when the selected text changed during the call, but records the paid reply", async () => {
    const { editor, ctrl, costs } = setup();
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      editor.view.dispatch(editor.state.tr.insertText("Oh. ", 1));
      yield { type: "done", ...(reply() as object) } as never;
    });
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toMatch(/Document changed during the AI call/);
    expect(ctrl.lineNotes).toBeNull();
    expect(costs).toEqual([0.02]);
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("refuses another run while notes are open, with a visible notice", async () => {
    const { ctrl, notices } = setup();
    const spy = fakeStream(reply());
    await ctrl.runPromptEntry(ENTRY, {});
    expect(notices).toEqual([]);
    await ctrl.runPromptEntry(ENTRY, {});
    expect(spy).toHaveBeenCalledTimes(1);
    expect(notices).toEqual(["Finish reviewing the notes first — dismiss them or Dismiss all."]);
    expect(ctrl.error).toBeNull();
  });

  it("Cancel aborts the call: nothing installed, no cost, 'Check cancelled.'", async () => {
    const { ctrl, editor, costs, notices } = setup();
    const spy = vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* (_payload, signal) {
      await new Promise<void>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
      yield* [] as never[];
    });
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    ctrl.cancelGeneration();
    await run;
    expect(notices).toEqual(["Check cancelled."]);
    expect(ctrl.error).toBeNull();
    expect(ctrl.lineNotes).toBeNull();
    expect(lineNoteState(editor.state).notes).toHaveLength(0);
    expect(costs).toEqual([]);
    expect(ctrl.generating).toBe(false);
  });

  it("dismissing the last note closes the review", async () => {
    const { ctrl, editor } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.nextLineNote();
    expect(ctrl.lineNotes).toMatchObject({ remaining: 2, index: 2 });
    ctrl.prevLineNote();
    expect(ctrl.lineNotes).toMatchObject({ index: 1 });
    ctrl.dismissCurrentLineNote();
    expect(ctrl.lineNotes).toMatchObject({ remaining: 1, index: 1 });
    ctrl.dismissCurrentLineNote();
    expect(ctrl.lineNotes).toBeNull();
    expect(ctrl.meta).toBeNull();
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("editing a quote drops its note from the count", async () => {
    const { ctrl, editor } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    const [first] = lineNoteState(editor.state).notes;
    editor.view.dispatch(editor.state.tr.insertText("X", first.from + 1));
    expect(ctrl.lineNotes).toMatchObject({ remaining: 1 });
  });

  it("reset() clears the notes from the editor", async () => {
    const { ctrl, editor } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.reset();
    expect(lineNoteState(editor.state).notes).toHaveLength(0);
    expect(ctrl.lineNotes).toBeNull();
    expect(editor.view.dom.querySelectorAll(".line-note-quote")).toHaveLength(0);
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("retry dismisses what is left and checks the same text again", async () => {
    const { ctrl, editor } = setup();
    const spy = fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    await ctrl.retry();
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[1][0].selection).toBe(TEXT);
    expect(spy.mock.calls[1][0].response_format).toBe("notes");
    expect(editor.state.doc.textContent).toBe(TEXT);
    expect(ctrl.lineNotes).toMatchObject({ remaining: 2 });
  });

  it("the card's Open entry reaches the host's onOpenEntry with the entry id", async () => {
    const { ctrl, editor, opened } = setup();
    fakeStream(reply());
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    editor.view.dom.querySelector<HTMLElement>('[data-testid="line-note-card-open"]')!.click();
    expect(opened).toEqual(["lore_1"]);
    expect(editor.view.dom.querySelector('[data-testid="line-note-card-entry"]')?.textContent).toBe("Mira");
  });
});
