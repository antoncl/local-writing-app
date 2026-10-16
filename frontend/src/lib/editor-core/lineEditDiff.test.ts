// @vitest-environment happy-dom
// #2531 (ADR-0100 decision 11): an edit renders as a word-level diff - the
// passage's own words that go are `.r-now`, the replacement's new words are
// `.r-was` widgets - over one `.line-edit` span that carries click and outline.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import {
  LineEditSuggestions,
  acceptCurrentLineEdit,
  installLineEdits,
  lineEditState,
  setCurrentLineEdit,
} from "./lineEditSuggestions";
import { editRunsCache } from "./reviewKinds/edits";
import { placeLineEdits } from "./lineEdits";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

const TEXT = "The cat sat on the mat.";

type Edit = { find: string; replace: string; reason: string };

function setup(edits: Edit[], text = TEXT) {
  const host = document.createElement("div");
  document.body.append(host);
  const editor = new Editor({
    element: host,
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] },
  });
  editors.push(editor);
  const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, edits);
  installLineEdits(editor.view, placed);
  return editor;
}
const all = (editor: Editor, selector: string) => [...editor.view.dom.querySelectorAll(selector)];

describe("line edits as a word diff", () => {
  it("marks only the changed words: the going word warm, the coming word a cool widget", () => {
    const editor = setup([{ find: "cat sat", replace: "dog sat", reason: "r" }]);
    const now = all(editor, ".r-now");
    expect(now).toHaveLength(1);
    expect(now[0].textContent).toBe("cat");
    const was = all(editor, ".r-was");
    expect(was).toHaveLength(1);
    expect(was[0].textContent).toBe("dog");
    // PM splits the passage's span around the marks; together they cover it all.
    expect(all(editor, ".line-edit").map((n) => n.textContent).join("")).toBe("cat sat");
    expect(now.some((n) => n.textContent?.includes("sat"))).toBe(false);
    expect(editor.state.doc.textContent).toBe(TEXT);
  });

  it("prose with markdown-ish characters still marks the right words (or the whole passage)", () => {
    // The engine is markdown-aware; the runs must spell the passage, else the
    // guard marks the whole of it. Either way no mark lands on the wrong text.
    const text = "She said *no* to Tom_Ri and # left.";
    const editor = setup([{ find: "*no* to Tom_Ri", replace: "*yes* to Tom_Ri", reason: "r" }], text);
    const warm = all(editor, ".r-now").map((n) => n.textContent).join("");
    const cool = all(editor, ".r-was").map((n) => n.textContent).join("");
    expect(["*no* to Tom_Ri".includes(warm), warm.length > 0]).toEqual([true, true]);
    expect(cool.length).toBeGreaterThan(0);
    expect(editor.state.doc.textContent).toBe(text);
  });

  it("a pure cut is one warm run over the passage and no widget", () => {
    const editor = setup([{ find: " on the mat", replace: "", reason: "cut" }]);
    const now = all(editor, ".r-now");
    expect(now).toHaveLength(1);
    expect(now[0].textContent).toBe(" on the mat");
    expect(all(editor, ".r-was")).toHaveLength(0);
  });

  it("a paragraph insertion is one cool widget showing the blank line, and no warm run", () => {
    const editor = setup([{ find: "The cat sat", replace: "The cat sat\n\nNew para.", reason: "more" }]);
    const was = all(editor, ".r-was");
    expect(was).toHaveLength(1);
    expect(was[0].textContent).toMatch(/\n[ \t]*\n/);
    expect(was[0].textContent).toContain("New para.");
    expect(all(editor, ".r-now")).toHaveLength(0);
  });

  it("the current edit is outlined, a widget click selects its edit, accept writes the whole replacement", () => {
    const editor = setup([
      { find: "cat", replace: "dog", reason: "a" },
      { find: "mat", replace: "rug", reason: "b" },
    ]);
    const [first, second] = lineEditState(editor.state).edits;
    expect(all(editor, ".line-edit-current")).toHaveLength(1);
    expect(all(editor, ".line-edit-current")[0].textContent).toBe("cat");
    setCurrentLineEdit(editor.view, second.id);
    expect(all(editor, ".line-edit-current")[0].textContent).toBe("mat");
    all(editor, ".r-was")[0].dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    expect(lineEditState(editor.state).currentId).toBe(first.id);

    acceptCurrentLineEdit(editor.view);
    expect(editor.state.doc.textContent).toBe("The dog sat on the mat.");
    expect(all(editor, '[data-line-edit-id="' + first.id + '"]')).toHaveLength(0);
    // only the second edit's marks remain
    expect(all(editor, ".line-edit")).toHaveLength(1);
    expect(all(editor, ".r-now")).toHaveLength(1);
    expect(all(editor, ".r-was")).toHaveLength(1);
  });

  it("diffs once per (find, replace) across re-decorations", () => {
    editRunsCache.clear();
    const editor = setup([
      { find: "cat", replace: "dog", reason: "a" },
      { find: "mat", replace: "rug", reason: "b" },
    ]);
    expect(editRunsCache.size).toBe(2);
    const [first, second] = lineEditState(editor.state).edits;
    for (let i = 0; i < 3; i++) {
      setCurrentLineEdit(editor.view, second.id);
      setCurrentLineEdit(editor.view, first.id);
    }
    expect(editRunsCache.size).toBe(2);
  });

  it("shows the going word before the coming one (older text first, #2533)", () => {
    const editor = setup([{ find: "cat sat", replace: "dog sat", reason: "r" }]);
    const marks = all(editor, ".r-now, .r-was").map((n) => n.textContent);
    expect(marks).toEqual(["cat", "dog"]);
  });
});
