// @vitest-environment happy-dom
// #2460: the review plugin keeps placed edits in state (document untouched),
// decorates them, and resolves them one at a time or all at once.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import {
  LineEditSuggestions,
  acceptAllLineEdits,
  acceptCurrentLineEdit,
  acceptLineEdit,
  installLineEdits,
  lineEditState,
  rejectAllLineEdits,
  rejectCurrentLineEdit,
  rejectLineEdit,
  setCurrentLineEdit,
  stepLineEdit,
} from "./lineEditSuggestions";
import { placeLineEdits } from "./lineEdits";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

const TEXT = "The cat sat on the mat.";

function setup(select = false) {
  const host = document.createElement("div");
  document.body.append(host);
  const editor = new Editor({
    element: host,
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: TEXT }] }] },
  });
  editors.push(editor);
  const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, [
    { find: "cat", replace: "dog", reason: "livelier" },
    { find: " on the mat", replace: "", reason: "cut" },
  ]);
  if (select) editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
  installLineEdits(editor.view, placed, editor.state.doc.content.size - 1);
  return editor;
}
const setupSelected = () => ({ editor: setup(true) });
const docText = (editor: Editor) => editor.state.doc.textContent;

describe("LineEditSuggestions", () => {
  it("install leaves the document alone and decorates the old text and the new-text widget", () => {
    const editor = setup();
    expect(docText(editor)).toBe(TEXT);
    expect(lineEditState(editor.state).edits).toHaveLength(2);
    const dom = editor.view.dom;
    const old = dom.querySelectorAll(".line-edit-old");
    expect(old).toHaveLength(2);
    expect(old[0].getAttribute("title")).toBe("livelier");
    // one new-text span (the pure cut has none), and no inline buttons at all
    expect(dom.querySelectorAll(".line-edit-new")).toHaveLength(1);
    expect(dom.querySelector(".line-edit-new")?.textContent).toBe("dog");
    expect(dom.querySelectorAll("button")).toHaveLength(0);
  });

  it("collapses the selection to the end of the revised range on install", () => {
    const { editor } = setupSelected();
    const { from, to } = editor.state.selection;
    expect(from).toBe(to);
    expect(to).toBe(editor.state.doc.content.size - 1);
  });

  it("the first edit is current, and the current one carries the stronger class on both parts", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    expect(lineEditState(editor.state).currentId).toBe(first.id);
    const dom = editor.view.dom;
    expect(dom.querySelectorAll(".line-edit-old.line-edit-current")).toHaveLength(1);
    expect(dom.querySelector(".line-edit-new")?.classList.contains("line-edit-current")).toBe(true);
    setCurrentLineEdit(editor.view, second.id);
    expect(dom.querySelector(".line-edit-new")?.classList.contains("line-edit-current")).toBe(false);
    expect(dom.querySelector(".line-edit-old.line-edit-current")?.textContent).toBe(" on the mat");
  });

  it("clicking the old text or the new text makes that edit current", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    setCurrentLineEdit(editor.view, second.id);
    editor.view.dom.querySelector(".line-edit-new")!.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, cancelable: true }),
    );
    expect(lineEditState(editor.state).currentId).toBe(first.id);
    const oldSecond = editor.view.dom.querySelectorAll(".line-edit-old")[1] as HTMLElement;
    editor.view.someProp("handleClick", (f) => f(editor.view, 0, { target: oldSecond } as unknown as MouseEvent));
    expect(lineEditState(editor.state).currentId).toBe(second.id);
  });

  it("stepLineEdit moves by position and wraps", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    stepLineEdit(editor.view, 1);
    expect(lineEditState(editor.state).currentId).toBe(second.id);
    stepLineEdit(editor.view, 1);
    expect(lineEditState(editor.state).currentId).toBe(first.id);
    stepLineEdit(editor.view, -1);
    expect(lineEditState(editor.state).currentId).toBe(second.id);
  });

  it("after resolving the current edit, the next by position is current; wraps; none when empty", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    // current = first; accepting it moves to the second
    acceptCurrentLineEdit(editor.view);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    expect(lineEditState(editor.state).currentId).toBe(second.id);
    expect(first.id).not.toBe(second.id);
    rejectCurrentLineEdit(editor.view);
    expect(lineEditState(editor.state)).toMatchObject({ edits: [], currentId: null });
  });

  it("resolving the last edit by position wraps current to the first", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    setCurrentLineEdit(editor.view, second.id);
    rejectCurrentLineEdit(editor.view);
    expect(lineEditState(editor.state).currentId).toBe(first.id);
  });

  it("accepting the current edit is one undo step", () => {
    const editor = setup();
    acceptCurrentLineEdit(editor.view);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    editor.commands.undo();
    expect(docText(editor)).toBe(TEXT);
  });

  describe("keyboard", () => {
    const press = (editor: Editor, key: string, init: KeyboardEventInit = { altKey: true }) => {
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
      editor.view.dom.dispatchEvent(event);
      return event;
    };

    it("Alt+Down / Alt+Up step; Alt+Enter accepts; Alt+Backspace rejects the current edit", () => {
      const editor = setup();
      const [first, second] = lineEditState(editor.state).edits;
      expect(press(editor, "ArrowDown").defaultPrevented).toBe(true);
      expect(lineEditState(editor.state).currentId).toBe(second.id);
      press(editor, "ArrowUp");
      expect(lineEditState(editor.state).currentId).toBe(first.id);
      press(editor, "Enter");
      expect(docText(editor)).toBe("The dog sat on the mat.");
      press(editor, "Backspace");
      expect(docText(editor)).toBe("The dog sat on the mat.");
      expect(lineEditState(editor.state).edits).toHaveLength(0);
    });

    it("does nothing without Alt, and does not swallow Alt+Enter when nothing is pending", () => {
      const editor = setup();
      press(editor, "ArrowDown", {});
      press(editor, "Backspace", {});
      expect(lineEditState(editor.state).edits).toHaveLength(2);
      expect(docText(editor)).toBe(TEXT);
      rejectAllLineEdits(editor.view);
      expect(press(editor, "Enter").defaultPrevented).toBe(false);
      expect(press(editor, "ArrowDown").defaultPrevented).toBe(false);
    });
  });

  it("accept applies one edit and keeps the other in place", () => {
    const editor = setup();
    const [first] = lineEditState(editor.state).edits;
    acceptLineEdit(editor.view, first.id);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    const { edits, accepted } = lineEditState(editor.state);
    expect(accepted).toBe(1);
    expect(edits).toHaveLength(1);
    expect(editor.state.doc.textBetween(edits[0].from, edits[0].to)).toBe(" on the mat");
  });

  it("accept ignores stored marks and takes the replaced text's marks", () => {
    const editor = setup();
    const bold = editor.state.schema.marks.bold.create();
    editor.view.dispatch(editor.state.tr.setStoredMarks([bold]));
    const [first] = lineEditState(editor.state).edits;
    acceptLineEdit(editor.view, first.id);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    expect(editor.getJSON().content?.[0].content).toEqual([
      { type: "text", text: "The dog sat on the mat." },
    ]);
  });

  it("accept keeps the marks of the text it replaces", () => {
    const editor = setup();
    // make "cat" italic, then accept the edit over it
    const [first] = lineEditState(editor.state).edits;
    const italic = editor.state.schema.marks.italic.create();
    editor.view.dispatch(editor.state.tr.addMark(first.from, first.to, italic));
    acceptLineEdit(editor.view, lineEditState(editor.state).edits[0].id);
    const marks: string[] = [];
    editor.state.doc.descendants((node) => {
      if (node.isText && node.text?.includes("dog")) marks.push(...node.marks.map((m) => m.type.name));
    });
    expect(marks).toEqual(["italic"]);
    expect(docText(editor)).toBe("The dog sat on the mat.");
  });

  it("reject drops the edit and leaves the text", () => {
    const editor = setup();
    const [first] = lineEditState(editor.state).edits;
    rejectLineEdit(editor.view, first.id);
    expect(docText(editor)).toBe(TEXT);
    expect(lineEditState(editor.state)).toMatchObject({ accepted: 0 });
    expect(lineEditState(editor.state).edits).toHaveLength(1);
  });

  it("reject all clears everything and changes nothing", () => {
    const editor = setup();
    rejectAllLineEdits(editor.view);
    expect(docText(editor)).toBe(TEXT);
    expect(lineEditState(editor.state).edits).toHaveLength(0);
  });

  it("accept all applies every edit as ONE undo step", () => {
    const editor = setup();
    acceptAllLineEdits(editor.view);
    expect(docText(editor)).toBe("The dog sat.");
    expect(lineEditState(editor.state)).toMatchObject({ edits: [], accepted: 2 });
    editor.commands.undo();
    expect(docText(editor)).toBe(TEXT);
  });

  it("typing inside an edit's range drops that edit, not the others", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    editor.view.dispatch(editor.state.tr.insertText("X", first.from + 1));
    const { edits } = lineEditState(editor.state);
    expect(edits.map((e) => e.id)).toEqual([second.id]);
    // the survivor moved with the text
    expect(editor.state.doc.textBetween(edits[0].from, edits[0].to)).toBe(" on the mat");
  });

  it("an edit before the others shifts their positions", () => {
    const editor = setup();
    editor.view.dispatch(editor.state.tr.insertText("Well, ", 1));
    const { edits } = lineEditState(editor.state);
    expect(edits).toHaveLength(2);
    expect(editor.state.doc.textBetween(edits[0].from, edits[0].to)).toBe("cat");
  });
});
