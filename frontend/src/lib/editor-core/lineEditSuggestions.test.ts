// @vitest-environment happy-dom
// #2460: the review plugin keeps placed edits in state (document untouched),
// decorates them, and resolves them one at a time or all at once.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import {
  LineEditSuggestions,
  acceptAllLineEdits,
  acceptLineEdit,
  installLineEdits,
  lineEditState,
  rejectAllLineEdits,
  rejectLineEdit,
} from "./lineEditSuggestions";
import { placeLineEdits } from "./lineEdits";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

const TEXT = "The cat sat on the mat.";

function setup() {
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
  installLineEdits(editor.view, placed);
  return editor;
}
const docText = (editor: Editor) => editor.state.doc.textContent;

describe("LineEditSuggestions", () => {
  it("install leaves the document alone and decorates the old text and widgets", () => {
    const editor = setup();
    expect(docText(editor)).toBe(TEXT);
    expect(lineEditState(editor.state).edits).toHaveLength(2);
    const dom = editor.view.dom;
    const old = dom.querySelectorAll(".line-edit-old");
    expect(old).toHaveLength(2);
    expect(old[0].getAttribute("title")).toBe("livelier");
    // one new-text span (the pure cut has none), two button pairs
    expect(dom.querySelectorAll(".line-edit-new")).toHaveLength(1);
    expect(dom.querySelector(".line-edit-new")?.textContent).toBe("dog");
    expect(dom.querySelectorAll('[data-testid="line-edit-accept"]')).toHaveLength(2);
    expect(dom.querySelectorAll('[aria-label="Reject edit"]')).toHaveLength(2);
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

  it("the widget's accept button applies its edit", () => {
    const editor = setup();
    const btn = editor.view.dom.querySelector('[data-testid="line-edit-accept"]') as HTMLElement;
    btn.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
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
