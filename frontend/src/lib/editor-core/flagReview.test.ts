// @vitest-environment happy-dom
// ADR-0100 decisions 5 and 6: one review holds edits and notes together, and an
// edit's replacement may hold paragraphs. Real TipTap editor + the real plugin.
import { afterEach, describe, expect, it } from "vitest";
import { Editor, type JSONContent } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import {
  LineEditSuggestions,
  acceptAllLineEdits,
  acceptCurrentLineEdit,
  dismissAllLineNotes,
  dismissLineNote,
  editsKind,
  installFlags,
  installLineEdits,
  keepReviewItem,
  lineEditState,
  lineNoteState,
  stepLineEdit,
  stepLineNote,
} from "./lineEditSuggestions";
import { notesKind } from "./reviewKinds/notes";
import { pluginKey, rejectAllFlags, reviewState } from "./reviewKinds/core";

const editors: Editor[] = [];
afterEach(() => {
  for (const e of editors.splice(0)) e.destroy();
});

const para = (t: string): JSONContent => ({ type: "paragraph", content: [{ type: "text", text: t }] });
const TEXT = "alpha beta gamma delta";

function setup(content: JSONContent[] = [para(TEXT)]) {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content },
  });
  editors.push(editor);
  return editor;
}

const edits = editsKind({ keep: () => {} });
const notes = notesKind({ openEntry: () => {}, entryName: () => "" });

/** [from, to] of the first occurrence of `word` in the (single-paragraph) doc. */
function at(editor: Editor, word: string) {
  const from = editor.state.doc.textContent.indexOf(word) + 1;
  return { from, to: from + word.length };
}
const edit = (editor: Editor, word: string, replace: string) => ({
  ...at(editor, word), find: word, replace, reason: "r", kind: edits,
});
const note = (editor: Editor, word: string) => ({
  ...at(editor, word), quote: word, problem: `p-${word}`, entry: "", kind: notes,
});

/** alpha(edit) beta(note) gamma(edit) delta(note), interleaved by position. */
function mixed() {
  const editor = setup();
  installFlags(editor.view, [
    note(editor, "delta"), edit(editor, "gamma", "G"), note(editor, "beta"), edit(editor, "alpha", "A"),
  ]);
  return editor;
}
const currentWord = (editor: Editor) => {
  const s = reviewState(editor.state);
  const i = s.items.find((x) => x.id === s.currentId)!;
  return editor.state.doc.textBetween(i.from, i.to);
};
const keyDown = (editor: Editor, key: string) =>
  editor.view.someProp("handleKeyDown", (f) =>
    f(editor.view, new KeyboardEvent("keydown", { key, altKey: true, cancelable: true })),
  );

describe("one review, both kinds (ADR-0100 decision 5)", () => {
  it("steps through edits and notes together in position order, wrapping", () => {
    const editor = mixed();
    expect(currentWord(editor)).toBe("alpha");
    const seen = [currentWord(editor)];
    for (let i = 0; i < 4; i++) {
      stepLineEdit(editor.view, 1);
      seen.push(currentWord(editor));
    }
    expect(seen).toEqual(["alpha", "beta", "gamma", "delta", "alpha"]);
    stepLineNote(editor.view, -1);
    expect(currentWord(editor)).toBe("delta");
  });

  it("Accept applies the current edit, Alt+Enter does nothing on a note, Alt+Backspace dismisses it", () => {
    const editor = mixed();
    acceptCurrentLineEdit(editor.view);
    expect(editor.state.doc.textContent).toBe("A beta gamma delta");
    expect(currentWord(editor)).toBe("beta");
    // Our plugin declines Alt+Enter on a note (another extension may still take
    // the key): the note stays, and nothing is written.
    keyDown(editor, "Enter");
    expect(editor.state.doc.textContent).toBe("A beta gamma delta");
    expect(currentWord(editor)).toBe("beta");
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    expect(keyDown(editor, "Backspace")).toBe(true);
    expect(lineNoteState(editor.state).notes.map((n) => n.quote)).toEqual(["delta"]);
  });

  it("Keep on a note resolves it as kept", () => {
    const editor = mixed();
    stepLineEdit(editor.view, 1); // beta, a note
    keepReviewItem(editor.view, reviewState(editor.state).currentId!);
    expect(reviewState(editor.state).kept).toBe(1);
    expect(lineNoteState(editor.state).notes.map((n) => n.quote)).toEqual(["delta"]);
    expect(lineEditState(editor.state).kept).toBe(1);
  });

  it("Accept all applies the edits and leaves the notes open", () => {
    const editor = mixed();
    acceptAllLineEdits(editor.view);
    expect(editor.state.doc.textContent).toBe("A beta G delta");
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    expect(reviewState(editor.state).accepted).toBe(2);
  });

  it("Reject all empties the review and leaves the document alone", () => {
    const editor = mixed();
    rejectAllFlags(editor.view);
    expect(reviewState(editor.state).items).toHaveLength(0);
    expect(reviewState(editor.state).currentId).toBeNull();
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("closes only when no item of either kind remains", () => {
    const editor = mixed();
    acceptAllLineEdits(editor.view);
    expect(reviewState(editor.state).items).toHaveLength(2);
    expect(currentWord(editor)).toBe("beta");
    dismissLineNote(editor.view, lineNoteState(editor.state).notes[0].id);
    expect(reviewState(editor.state).items).toHaveLength(1);
    dismissAllLineNotes(editor.view);
    expect(reviewState(editor.state).items).toHaveLength(0);
  });

  it("accepting an edit drops a note over the same words", () => {
    const editor = setup();
    installFlags(editor.view, [edit(editor, "beta", "B"), note(editor, "beta")]);
    acceptCurrentLineEdit(editor.view);
    expect(editor.state.doc.textContent).toBe("alpha B gamma delta");
    expect(reviewState(editor.state).items).toHaveLength(0);
  });

  it("lineEditState / lineNoteState report only their kind; currentId is null for the other", () => {
    const editor = mixed();
    const id = reviewState(editor.state).currentId; // alpha, an edit
    expect(lineEditState(editor.state).edits.map((e) => e.find)).toEqual(["alpha", "gamma"]);
    expect(lineEditState(editor.state).currentId).toBe(id);
    expect(lineNoteState(editor.state).currentId).toBeNull();
    stepLineEdit(editor.view, 1); // beta, a note
    expect(lineNoteState(editor.state).notes.map((n) => n.quote)).toEqual(["beta", "delta"]);
    expect(lineNoteState(editor.state).currentId).toBe(reviewState(editor.state).currentId);
    expect(lineEditState(editor.state).currentId).toBeNull();
  });

  it("an install meta carries kinds, not a review", () => {
    const editor = mixed();
    expect(pluginKey.getState(editor.state)!.items.every((i) => i.kind.name)).toBe(true);
  });
});

describe("an edit's replacement may hold paragraphs (ADR-0100 decision 6)", () => {
  const blocks = (editor: Editor) =>
    editor.state.doc.children.map((n) => n.textContent);

  it("splits the paragraph at the edit and inserts the new ones", () => {
    const editor = setup([para("One two three.")]);
    installLineEdits(editor.view, [
      { ...at(editor, "two"), find: "two", replace: "two\n\nNew para.\n\nAnother", reason: "r" },
    ]);
    acceptCurrentLineEdit(editor.view);
    expect(blocks(editor)).toEqual(["One two", "New para.", "Another three."]);
  });

  it("a replace of only blank lines cuts the passage", () => {
    const editor = setup([para("One two three.")]);
    installLineEdits(editor.view, [{ ...at(editor, "two "), find: "two ", replace: "\n\n", reason: "r" }]);
    acceptCurrentLineEdit(editor.view);
    expect(blocks(editor)).toEqual(["One three."]);
  });

  it("a replace without a blank line is applied as before", () => {
    const editor = setup([para("One two three.")]);
    installLineEdits(editor.view, [{ ...at(editor, "two"), find: "two", replace: "2\nx", reason: "r" }]);
    acceptCurrentLineEdit(editor.view);
    expect(blocks(editor)).toEqual(["One 2\nx three."]);
  });
});
