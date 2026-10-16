// @vitest-environment happy-dom
// ADR-0098: the shared review plugin, run with the NOTES kind. A note underlines
// its quote, never strikes or proposes text, has no accept, and nothing it does
// ever writes to the document.
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import {
  LineEditSuggestions,
  currentLineNote,
  dismissAllLineNotes,
  dismissCurrentLineNote,
  dismissLineNote,
  installLineEdits,
  installLineNotes,
  lineEditState,
  lineNoteState,
  stepLineNote,
} from "./lineEditSuggestions";
import { placeLineNotes } from "./lineEdits";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

const TEXT = "The cat sat on the mat.";
const NAMES: Record<string, string> = { lore_1: "Mira", lore_2: "The Keep" };

function setup() {
  const host = document.createElement("div");
  document.body.append(host);
  const editor = new Editor({
    element: host,
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: TEXT }] }] },
  });
  editors.push(editor);
  const { placed } = placeLineNotes(editor.state.doc, 0, editor.state.doc.content.size, [
    { quote: "cat", problem: "Mira has no cat", entry: "lore_1" },
    { quote: "on the mat", problem: "The Keep has no mats", entry: "lore_2" },
  ]);
  const openEntry = vi.fn();
  const keep = vi.fn();
  installLineNotes(editor.view, placed, editor.state.doc.content.size - 1, {
    openEntry,
    entryName: (id) => NAMES[id] ?? "",
    keep,
  });
  return { editor, openEntry, keep };
}

const keydown = (editor: Editor, key: string) => {
  const event = new KeyboardEvent("keydown", { key, altKey: true, bubbles: true, cancelable: true });
  editor.view.dom.dispatchEvent(event);
  return event;
};
const q = (editor: Editor, testid: string) => editor.view.dom.querySelector<HTMLElement>(`[data-testid="${testid}"]`);

describe("LineNoteSuggestions (notes kind)", () => {
  it("takes focus back from wherever the run left it (its inputs dialog), so the review keys reach the editor", () => {
    const outside = document.createElement("button");
    document.body.append(outside);
    const { editor } = setup();
    outside.focus();
    expect(editor.view.hasFocus()).toBe(false);
    const { placed } = placeLineNotes(editor.state.doc, 0, editor.state.doc.content.size, [
      { quote: "sat", problem: "p", entry: "lore_1" },
    ]);
    installLineNotes(editor.view, placed, undefined, { openEntry: () => {}, entryName: () => "" });
    expect(editor.view.hasFocus()).toBe(true);
    outside.remove();
  });

  it("decorates each quote quietly: no strike-through class, no proposed-text widget", () => {
    const { editor } = setup();
    const dom = editor.view.dom;
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    const quotes = dom.querySelectorAll(".line-note-quote");
    expect(quotes).toHaveLength(2);
    expect(quotes[0].getAttribute("title")).toBe("Mira has no cat");
    expect(dom.querySelectorAll(".line-edit, .r-now, .r-was")).toHaveLength(0);
    expect(dom.querySelectorAll(".line-note-current")).toHaveLength(1);
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("renders Keep before Dismiss, titled, and clicking it calls keep with the current note", () => {
    const { editor, keep } = setup();
    const button = q(editor, "line-note-card-keep")!;
    expect(button.getAttribute("title")).toBe("Keep as a TODO — decide later");
    expect(button.nextElementSibling).toBe(q(editor, "line-note-card-dismiss"));
    button.click();
    expect(keep).toHaveBeenCalledTimes(1);
    expect(keep.mock.calls[0][1]).toMatchObject({ quote: "cat", problem: "Mira has no cat" });
  });

  it("is not an edit list: the edit accessors see nothing", () => {
    const { editor } = setup();
    expect(lineEditState(editor.state).edits).toHaveLength(0);
  });

  it("shows one card for the current note: problem, entry name, no Accept", () => {
    const { editor } = setup();
    expect(editor.view.dom.querySelectorAll('[data-testid="line-note-card"]')).toHaveLength(1);
    const card = q(editor, "line-note-card")!;
    expect(card.classList.contains("line-edit-card")).toBe(true);
    expect(card.classList.contains("line-note-card")).toBe(true);
    expect(card.getAttribute("aria-label")).toBe("Current note");
    expect(q(editor, "line-note-card-problem")?.textContent).toBe("Mira has no cat");
    expect(q(editor, "line-note-card-entry")?.textContent).toBe("Mira");
    expect(q(editor, "line-edit-card")).toBeNull();
    expect(q(editor, "line-edit-card-accept")).toBeNull();
    expect(q(editor, "line-note-card-accept")).toBeNull();
  });

  it("falls back to the entry id when the name is unknown", () => {
    const editor = setup().editor;
    const { placed } = placeLineNotes(editor.state.doc, 0, editor.state.doc.content.size, [
      { quote: "sat", problem: "p", entry: "lore_x" },
    ]);
    dismissAllLineNotes(editor.view);
    installLineNotes(editor.view, placed, undefined, { openEntry: () => {}, entryName: () => "" });
    expect(q(editor, "line-note-card-entry")?.textContent).toBe("lore_x");
  });

  it("Open entry calls openEntry with the note's entry id and leaves the doc and the note alone", () => {
    const { editor, openEntry } = setup();
    q(editor, "line-note-card-open")!.click();
    expect(openEntry).toHaveBeenCalledWith("lore_1");
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("card buttons step and dismiss", () => {
    const { editor } = setup();
    q(editor, "line-note-card-next")!.click();
    expect(q(editor, "line-note-card-problem")?.textContent).toBe("The Keep has no mats");
    q(editor, "line-note-card-prev")!.click();
    expect(q(editor, "line-note-card-problem")?.textContent).toBe("Mira has no cat");
    q(editor, "line-note-card-dismiss")!.click();
    expect(lineNoteState(editor.state).notes).toHaveLength(1);
    expect(q(editor, "line-note-card-problem")?.textContent).toBe("The Keep has no mats");
  });

  it("Alt+Enter changes nothing", () => {
    const { editor } = setup();
    const before = editor.state.doc.toJSON();
    keydown(editor, "Enter");
    expect(editor.state.doc.toJSON()).toEqual(before);
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
  });

  it("Alt+Backspace dismisses the current note without touching the text", () => {
    const { editor } = setup();
    const event = keydown(editor, "Backspace");
    expect(event.defaultPrevented).toBe(true);
    expect(lineNoteState(editor.state).notes).toHaveLength(1);
    expect(currentLineNote(editor.state)?.problem).toBe("The Keep has no mats");
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("Alt+Down / Alt+Up step through the notes, wrapping", () => {
    const { editor } = setup();
    const problem = () => currentLineNote(editor.state)?.problem;
    expect(problem()).toBe("Mira has no cat");
    keydown(editor, "ArrowDown");
    expect(problem()).toBe("The Keep has no mats");
    keydown(editor, "ArrowDown");
    expect(problem()).toBe("Mira has no cat");
    keydown(editor, "ArrowUp");
    expect(problem()).toBe("The Keep has no mats");
    stepLineNote(editor.view, 1);
    expect(problem()).toBe("Mira has no cat");
  });

  it("clicking a quote makes that note current", () => {
    const { editor } = setup();
    const second = editor.view.dom.querySelectorAll<HTMLElement>(".line-note-quote")[1];
    second.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    // handleClick reads the event target; drive it as ProseMirror does.
    editor.view.someProp("handleClick", (f) => f(editor.view, 0, { target: second } as unknown as MouseEvent));
    expect(currentLineNote(editor.state)?.problem).toBe("The Keep has no mats");
  });

  it("editing inside a quote drops that note and only that note", () => {
    const { editor } = setup();
    const [first] = lineNoteState(editor.state).notes;
    editor.view.dispatch(editor.state.tr.insertText("X", first.from + 1));
    const left = lineNoteState(editor.state).notes;
    expect(left).toHaveLength(1);
    expect(left[0].quote).toBe("on the mat");
  });

  it("typing before a quote only moves it; the note survives", () => {
    const { editor } = setup();
    editor.view.dispatch(editor.state.tr.insertText("Oh. ", 1));
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    const [first] = lineNoteState(editor.state).notes;
    expect(editor.state.doc.textBetween(first.from, first.to)).toBe("cat");
  });

  it("dismiss helpers resolve by id and all, never touching the doc", () => {
    const { editor } = setup();
    const [first, second] = lineNoteState(editor.state).notes;
    dismissLineNote(editor.view, first.id);
    expect(lineNoteState(editor.state).notes.map((n) => n.id)).toEqual([second.id]);
    dismissCurrentLineNote(editor.view);
    expect(lineNoteState(editor.state).notes).toHaveLength(0);
    expect(editor.view.dom.querySelectorAll(".line-note-quote, .line-edit-card")).toHaveLength(0);
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("overlapping notes both decorate", () => {
    const { editor } = setup();
    const { placed } = placeLineNotes(editor.state.doc, 0, editor.state.doc.content.size, [
      { quote: "cat sat on", problem: "a", entry: "lore_1" },
      { quote: "sat on the", problem: "b", entry: "lore_2" },
    ]);
    dismissAllLineNotes(editor.view);
    installLineNotes(editor.view, placed, undefined, { openEntry: () => {}, entryName: () => "" });
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    expect(editor.view.dom.querySelectorAll(".line-note-quote").length).toBeGreaterThanOrEqual(2);
  });

  it("an edit review installed afterwards replaces the notes (one review per editor)", () => {
    const { editor } = setup();
    dismissAllLineNotes(editor.view);
    installLineEdits(editor.view, [{ from: 5, to: 8, find: "cat", replace: "dog", reason: "r" }]);
    expect(lineEditState(editor.state).edits).toHaveLength(1);
    expect(lineNoteState(editor.state).notes).toHaveLength(0);
  });
});
