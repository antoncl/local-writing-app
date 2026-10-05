// @vitest-environment happy-dom
// #2428: a long inline stream must not render per delta. Renders coalesce into
// one per window, each render is ONE transaction, and the text present when the
// stream ends equals the full accumulated text. Real TipTap editor + the real
// AiSuggestionController; only `api.aiGenerateStream` is faked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { AISuggestion } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import { AiSuggestionController } from "./aiSuggestion.svelte";

const editors: Editor[] = [];
beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(api, "aiAppendInvocation").mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  for (const editor of editors.splice(0)) editor.destroy();
});

const ENTRY = {
  id: "p1",
  title: "P",
  body: "x",
  entry_type: "prompt:general",
  context_strategy: { output: { handler: "inline" } },
} as never;

function setup() {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), AISuggestion],
    content: { type: "doc", content: [{ type: "paragraph" }] },
  });
  editors.push(editor);
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: "scene_1" }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ promptEntries: [] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onOpenChat: () => {},
  });
  let updates = 0;
  editor.on("update", () => updates++);
  return { editor, ctrl, updates: () => updates };
}

const DONE = {
  type: "done",
  provider: "p",
  model: "m",
  latency_ms: 1,
  truncated: false,
} as never;

function fakeStream(events: unknown[]) {
  vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
    for (const ev of events) yield ev as never;
  });
}
const deltas = (n: number) => Array.from({ length: n }, (_, i) => ({ type: "delta", text: `w${i} ` }));
const docText = (editor: Editor) => editor.state.doc.textContent;
function markedText(editor: Editor) {
  let marked = "";
  let unmarked = "";
  editor.state.doc.descendants((node) => {
    if (!node.isText) return;
    if (node.marks.some((m) => m.type.name === "aiSuggestion")) marked += node.text;
    else unmarked += node.text;
  });
  return { marked, unmarked };
}

describe("inline stream render throttle (#2428)", () => {
  it("coalesces 500 synchronous deltas into at most 3 doc updates", async () => {
    const { ctrl, updates } = setup();
    fakeStream([...deltas(500), DONE]);
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(updates()).toBeLessThanOrEqual(3);
    expect(updates()).toBeGreaterThanOrEqual(1);
  });

  it("ends with the full accumulated text, all carrying the mark; accept works", async () => {
    const { editor, ctrl } = setup();
    const evs = deltas(500);
    const full = evs.map((e) => e.text).join("");
    fakeStream([...evs, DONE]);
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(docText(editor)).toBe(full);
    expect(markedText(editor)).toEqual({ marked: full, unmarked: "" });
    expect(ctrl.suggestionId).not.toBeNull();
    ctrl.accept();
    expect(markedText(editor)).toEqual({ marked: "", unmarked: full });
  });

  it("revert after the stream removes the whole suggestion", async () => {
    const { editor, ctrl } = setup();
    fakeStream([...deltas(50), DONE]);
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    ctrl.revert();
    expect(docText(editor)).toBe("");
  });

  it("each flushed render is exactly one transaction", async () => {
    const { editor, ctrl } = setup();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield { type: "delta", text: "one " } as never;
      await gate;
      yield { type: "delta", text: "two " } as never;
      yield DONE;
    });
    const dispatched: number[] = [];
    editor.on("transaction", ({ transaction }) => {
      if (transaction.docChanged) dispatched.push(1);
    });
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.advanceTimersByTimeAsync(0);
    expect(dispatched.length).toBe(1); // first delta: immediate render, one transaction
    release();
    await run;
    expect(dispatched.length).toBe(2); // final flush: one more transaction
    expect(docText(editor)).toBe("one two ");
  });

  it("a revert mid-stream clears the pending timer; nothing re-renders afterwards", async () => {
    const { editor, ctrl } = setup();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      yield { type: "delta", text: "a " } as never;
      yield { type: "delta", text: "b " } as never; // coalesced, pending
      await gate;
      yield { type: "delta", text: "c " } as never;
      yield DONE;
    });
    const run = ctrl.runPromptEntryWithInputs(ENTRY, {});
    await vi.advanceTimersByTimeAsync(0);
    expect(docText(editor)).toBe("a ");
    ctrl.revert();
    expect(docText(editor)).toBe("");
    await vi.advanceTimersByTimeAsync(500);
    expect(docText(editor)).toBe("");
    release();
    await run;
    await vi.advanceTimersByTimeAsync(500);
    expect(docText(editor)).toBe("");
  });

  it("an error event drops the pending render and removes the suggestion", async () => {
    const { editor, ctrl } = setup();
    fakeStream([...deltas(20), { type: "error", error: "boom" }]);
    await ctrl.runPromptEntryWithInputs(ENTRY, {});
    expect(ctrl.error).toBe("boom");
    await vi.advanceTimersByTimeAsync(500);
    expect(docText(editor)).toBe("");
  });
});
