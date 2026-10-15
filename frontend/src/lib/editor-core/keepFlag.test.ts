// @vitest-environment happy-dom
// ADR-0099 decision 3: Keep turns a flag into a TODO and resolves it as kept.
// Real TipTap editor + the real AiSuggestionController + the real review plugin
// and TodoAnchors; only the stream and the file-TODO write are faked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor, type JSONContent } from "@tiptap/core";
import { api } from "@/lib/api";
import type { NewTodo } from "@/lib/todoTypes";
import { editorHtmlToSceneMarkdown } from "../utils/markdown";
import { proseStarterKit } from "./proseStarterKit";
import { TodoAnchor } from "./proseMarks";
import { AiSuggestionController } from "./aiSuggestion.svelte";
import { LineEditSuggestions, lineEditState, lineNoteState } from "./lineEditSuggestions";
import { editKeepNote, keepFlag, noteKeepNote } from "./keepFlag";
import { TodoAnchors } from "./todoAnchors";

const editors: Editor[] = [];
beforeEach(() => {
  vi.spyOn(api, "aiAppendInvocation").mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const editor of editors.splice(0)) editor.destroy();
});

const para = (...content: JSONContent[]): JSONContent => ({ type: "paragraph", content });
const text = (t: string, marks?: JSONContent["marks"]): JSONContent => ({ type: "text", text: t, ...(marks ? { marks } : {}) });
const TEXT = "The cat sat on the mat.";

const EDIT_ENTRY = {
  id: "p1",
  title: "Line edit",
  body: "x",
  entry_type: "prompt:general",
  offer_on: ["manuscript:scene"],
  context_strategy: { output: { handler: "inline_edits" } },
} as never;
const NOTE_ENTRY = {
  ...(EDIT_ENTRY as object),
  title: "Lore check",
  context_strategy: { output: { handler: "inline_notes" } },
} as never;

function setup(opts: { content?: JSONContent[]; kind?: string; fileWrite?: () => Promise<void> } = {}) {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), TodoAnchor, LineEditSuggestions],
    content: { type: "doc", content: opts.content ?? [para(text(TEXT))] },
  });
  editors.push(editor);
  const anchors = new TodoAnchors({ getEditor: () => editor, getElement: () => null });
  const filed: NewTodo[][] = [];
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: opts.kind ? "lore_9" : "scene_1", entry_type: "manuscript:scene" }) as never,
    getDocumentKind: () => (opts.kind ?? "manuscript") as never,
    getPromptCtx: () => ({ metadataSchema: { entry_types: {}, fields: {} }, promptEntries: [EDIT_ENTRY, NOTE_ENTRY] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onOpenChat: () => {},
    keepWriters: {
      markRange: (from, to, note) => anchors.markRange(from, to, note),
      createTodos: async (items) => {
        await opts.fileWrite?.();
        filed.push(items);
      },
    },
  });
  editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
  return { editor, ctrl, anchors, filed };
}

const done = (over: Record<string, unknown>) =>
  ({ ok: true, content: "", provider: "p", model: "m", latency_ms: 1, truncated: false, cost_usd: 0.01, ...over }) as never;
const fakeStream = (reply: unknown) =>
  vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
    yield { type: "delta", text: "{}" } as never;
    yield { type: "done", ...(reply as object) } as never;
  });
const edits = (...e: { find: string; replace: string; reason: string }[]) => done({ edits: e });
const CAT = { find: "cat", replace: "dog", reason: "livelier" };
const MAT = { find: "mat", replace: "rug", reason: "fresher" };

const click = (editor: Editor, testid: string) =>
  (editor.view.dom.querySelector(`[data-testid="${testid}"]`) as HTMLElement).click();
const anchorMarks = (editor: Editor) => {
  const found: { text: string; attrs: Record<string, unknown> }[] = [];
  editor.state.doc.descendants((node) => {
    for (const m of node.marks) if (m.type.name === "todoAnchor") found.push({ text: node.text ?? "", attrs: m.attrs });
  });
  return found;
};

describe("Keep a line edit in a scene", () => {
  it("marks an embedded TODO over exactly the range, leaves the text, the selection and the focus alone, and resolves the flag as kept", async () => {
    const { editor, ctrl } = setup();
    fakeStream(edits(CAT, MAT));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    const selection = { from: editor.state.selection.from, to: editor.state.selection.to };
    const focus = vi.spyOn(editor.view, "focus");

    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(ctrl.lineEdits?.remaining).toBe(1));

    expect(editor.state.doc.textContent).toBe(TEXT);
    const marks = anchorMarks(editor);
    expect(marks).toHaveLength(1);
    expect(marks[0].text).toBe("cat");
    expect(marks[0].attrs).toMatchObject({ status: "open", note: "livelier — proposed: “dog”" });
    expect(marks[0].attrs.anchorId).toMatch(/^todo_/);
    expect(editor.state.selection).toMatchObject(selection);
    expect(focus).not.toHaveBeenCalled();
    expect(lineEditState(editor.state).edits.map((e) => e.find)).toEqual(["mat"]);
  });

  it("an empty replacement says `proposed: cut`", async () => {
    const { editor, ctrl } = setup();
    fakeStream(edits({ find: " on the mat", replace: "", reason: "tighter" }, CAT));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    // The edits are sorted by position: the cat edit is current first.
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(ctrl.lineEdits?.remaining).toBe(1));
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(ctrl.lineEdits).toBeNull());
    expect(anchorMarks(editor).map((m) => m.attrs.note)).toEqual(["livelier — proposed: “dog”", "tighter — proposed: cut"]);
  });

  it("over formatted words makes ONE embedded TODO that survives enforceUnique and serializes to one marker pair", async () => {
    const { editor, ctrl, anchors } = setup({
      content: [para(text("We sailed past the "), text("old", [{ type: "italic" }]), text(" docks at dawn."))],
    });
    fakeStream(edits({ find: "the old docks", replace: "the docks", reason: "cut the age" }));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(ctrl.lineEdits).toBeNull());

    const marks = anchorMarks(editor);
    expect(marks.map((m) => m.text)).toEqual(["the ", "old", " docks"]);
    expect(new Set(marks.map((m) => m.attrs.anchorId)).size).toBe(1);
    expect(anchors.enforceUnique()).toBe(false);
    expect(anchorMarks(editor)).toHaveLength(3);
    const markdown = editorHtmlToSceneMarkdown(editor.getHTML());
    expect(markdown.match(/<!-- embedded-todo:/g)).toHaveLength(1);
    expect(markdown.match(/<!-- \/embedded-todo -->/g)).toHaveLength(1);
  });

  it("over an existing TODO files a scene TODO instead, and leaves the existing anchor untouched", async () => {
    const existing = { type: "todoAnchor", attrs: { anchorId: "todo_old", status: "open", note: "mine" } };
    const { editor, ctrl, filed } = setup({
      content: [para(text("The "), text("cat", [existing]), text(" sat on the mat."))],
    });
    fakeStream(edits({ find: "cat sat", replace: "tom sat", reason: "name it" }));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(filed).toHaveLength(1));

    expect(filed[0]).toEqual([
      { scope: "scene", scene_id: "scene_1", text: "name it — proposed: “tom sat” — “cat sat”" },
    ]);
    expect(anchorMarks(editor)).toEqual([{ text: "cat", attrs: { anchorId: "todo_old", status: "open", note: "mine" } }]);
    await vi.waitFor(() => expect(ctrl.lineEdits).toBeNull());
  });

  it("on a lore entry body files a node TODO", async () => {
    const { editor, ctrl, filed } = setup({ kind: "lore" });
    fakeStream(edits(CAT));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(filed).toHaveLength(1));
    expect(filed[0]).toEqual([{ scope: "node", node_id: "lore_9", text: "livelier — proposed: “dog” — “cat”" }]);
    expect(anchorMarks(editor)).toEqual([]);
  });

  it("keeps the flag and surfaces the error when the file TODO write is rejected", async () => {
    const { editor, ctrl } = setup({
      kind: "lore",
      fileWrite: () => Promise.reject(new Error("disk full")),
    });
    fakeStream(edits(CAT));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(ctrl.error).toBe("disk full"));
    expect(ctrl.lineEdits).toMatchObject({ remaining: 1 });
    expect(lineEditState(editor.state).edits).toHaveLength(1);
  });

  it("records the invocation when the run only had kept edits", async () => {
    const { editor, ctrl } = setup();
    fakeStream(edits(CAT, MAT));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(ctrl.lineEdits?.remaining).toBe(1));
    expect(api.aiAppendInvocation).not.toHaveBeenCalled();
    click(editor, "line-edit-card-keep");
    await vi.waitFor(() => expect(ctrl.lineEdits).toBeNull());
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
  });

  it("records nothing when every edit is rejected", async () => {
    const { editor, ctrl } = setup();
    fakeStream(edits(CAT, MAT));
    await ctrl.runPromptEntryWithInputs(EDIT_ENTRY, {});
    click(editor, "line-edit-card-reject");
    click(editor, "line-edit-card-reject");
    expect(ctrl.lineEdits).toBeNull();
    expect(api.aiAppendInvocation).not.toHaveBeenCalled();
  });
});

describe("Keep a lore-check note", () => {
  it("uses `problem (Entry)` as the note text", async () => {
    const { editor, ctrl } = setup();
    fakeStream(
      done({
        notes: [{ quote: "cat", problem: "Mira has no cat", entry: "lore_1" }],
        notes_dropped: 0,
        checked_against: [{ id: "lore_1", name: "Mira" }],
      }),
    );
    await ctrl.runPromptEntryWithInputs(NOTE_ENTRY, {});
    expect(lineNoteState(editor.state).notes).toHaveLength(1);
    click(editor, "line-note-card-keep");
    await vi.waitFor(() => expect(lineNoteState(editor.state).notes).toHaveLength(0));
    expect(anchorMarks(editor).map((m) => [m.text, m.attrs.note])).toEqual([["cat", "Mira has no cat (Mira)"]]);
  });
});

describe("keepFlag", () => {
  const doc = (editor: Editor) => editor.state.doc;
  it("files a scene TODO when the range spans two paragraphs", async () => {
    const { editor } = setup({ content: [para(text("First one.")), para(text("Second one."))] });
    const filed: NewTodo[][] = [];
    const markRange = vi.fn(() => "x");
    await keepFlag(
      { doc: doc(editor), from: 8, to: 20, quote: "one. Second", note: "n", inScene: true, docId: "scene_1" },
      { markRange, createTodos: async (items) => void filed.push(items) },
    );
    expect(markRange).not.toHaveBeenCalled();
    expect(filed).toEqual([[{ scope: "scene", scene_id: "scene_1", text: "n — “one. Second”" }]]);
  });

  it("files a scene TODO when the range crosses a hard break (an inline node would split the mark)", async () => {
    const { editor } = setup({ content: [para(text("Line one"), { type: "hardBreak" }, text("line two"))] });
    const filed: NewTodo[][] = [];
    const markRange = vi.fn(() => "x");
    // "Line one" = 1..9, hard break = 9..10, "line two" = 10..18.
    await keepFlag(
      { doc: doc(editor), from: 6, to: 14, quote: "one line", note: "n", inScene: true, docId: "scene_1" },
      { markRange, createTodos: async (items) => void filed.push(items) },
    );
    expect(markRange).not.toHaveBeenCalled();
    expect(filed).toEqual([[{ scope: "scene", scene_id: "scene_1", text: "n — “one line”" }]]);
  });

  it("builds the note text", () => {
    expect(editKeepNote("why", "new")).toBe("why — proposed: “new”");
    expect(editKeepNote("why", "")).toBe("why — proposed: cut");
    expect(editKeepNote("", "")).toBe("proposed: cut");
    expect(noteKeepNote("wrong", "Mira")).toBe("wrong (Mira)");
  });
});
