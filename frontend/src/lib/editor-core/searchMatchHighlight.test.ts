// @vitest-environment happy-dom
// The search-match reveal (#1925) against a real TipTap editor: opening a hit
// marks every match of the query and selects the one the hit named; an edit,
// Escape or a new reveal ends it.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import {
  compileSearchPattern,
  findMatches,
  SearchMatchHighlight,
  searchRevealActive,
  type SearchReveal,
} from "./searchMatchHighlight";

// Every editor is destroyed after its test — a live view schedules a DOM
// observer flush that would fire after the environment is torn down.
const editors: Editor[] = [];

function editorWith(html: string): Editor {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [StarterKit, SearchMatchHighlight],
    content: html,
  });
  editors.push(editor);
  return editor;
}

afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

const reveal = (editor: Editor, query: string, ordinal = 0, options: Partial<SearchReveal> = {}): boolean =>
  editor.commands.revealSearchMatch({ query, matchCase: false, wholeWord: false, ordinal, ...options });
/** The text of every marked span, in document order — a match that crosses a
 *  formatting boundary renders as more than one span. */
const marked = (editor: Editor): string[] =>
  Array.from(editor.view.dom.querySelectorAll(".search-match"), (el) => el.textContent ?? "");
const currentMark = (editor: Editor): string | null =>
  editor.view.dom.querySelector(".search-match-current")?.textContent ?? null;
const selected = (editor: Editor): string => {
  const { from, to } = editor.state.selection;
  return editor.state.doc.textBetween(from, to);
};
/** Send Escape to the editor; whether the editor consumed it. */
const escape = (editor: Editor): boolean => {
  const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  editor.view.dom.dispatchEvent(event);
  return event.defaultPrevented;
};

describe("search-match reveal", () => {
  it("marks every match and selects the one the ordinal names", () => {
    const editor = editorWith("<p>Aetheria rose.</p><p>Then Aetheria fell.</p>");
    expect(reveal(editor, "aetheria", 1)).toBe(true);

    expect(marked(editor)).toEqual(["Aetheria", "Aetheria"]);
    expect(currentMark(editor)).toBe("Aetheria");
    expect(selected(editor)).toBe("Aetheria");
    // The second match — past the first paragraph.
    expect(editor.state.selection.from).toBeGreaterThan(editor.state.doc.firstChild!.nodeSize);
    expect(searchRevealActive(editor.state)).toBe(true);
  });

  it("lands on the last match for an ordinal past the end", () => {
    const editor = editorWith("<p>Aetheria rose.</p><p>Then Aetheria fell.</p>");
    expect(reveal(editor, "aetheria", 7)).toBe(true);
    expect(editor.state.selection.from).toBeGreaterThan(editor.state.doc.firstChild!.nodeSize);
    expect(selected(editor)).toBe("Aetheria");
  });

  it("marks nothing and reports false when the document has no match", () => {
    const editor = editorWith("<p>Aetheria rose.</p>");
    expect(reveal(editor, "citadel")).toBe(false);
    expect(marked(editor)).toEqual([]);
    expect(searchRevealActive(editor.state)).toBe(false);
  });

  it("finds a match that crosses a formatting boundary", () => {
    const editor = editorWith("<p>Ae<strong>theria</strong> rose.</p>");
    expect(reveal(editor, "aetheria")).toBe(true);
    expect(selected(editor)).toBe("Aetheria");
    expect(marked(editor).join("")).toBe("Aetheria");
  });

  it("never matches across an inline leaf", () => {
    const editor = editorWith("<p>Aeth<br>eria rose.</p>");
    expect(reveal(editor, "aetheria")).toBe(false);
    expect(marked(editor)).toEqual([]);
  });

  it("matches with the search options the hit was found with", () => {
    const editor = editorWith("<p>aetheria Aetheria Aetherian</p>");
    reveal(editor, "Aetheria", 0, { matchCase: true });
    expect(marked(editor)).toEqual(["Aetheria", "Aetheria"]);
    reveal(editor, "Aetheria", 0, { wholeWord: true });
    expect(marked(editor)).toEqual(["aetheria", "Aetheria"]);
    reveal(editor, "Aetheria", 0, { matchCase: true, wholeWord: true });
    expect(marked(editor)).toEqual(["Aetheria"]);
  });

  it("ends with an edit", () => {
    const editor = editorWith("<p>Aetheria rose.</p>");
    reveal(editor, "aetheria");
    editor.commands.insertContent("Aetherion");
    expect(marked(editor)).toEqual([]);
    expect(searchRevealActive(editor.state)).toBe(false);
  });

  it("ends with Escape, which it consumes — and leaves alone when nothing is revealed", () => {
    const editor = editorWith("<p>Aetheria rose.</p>");
    expect(escape(editor)).toBe(false);

    reveal(editor, "aetheria");
    expect(escape(editor)).toBe(true);
    expect(marked(editor)).toEqual([]);
    expect(searchRevealActive(editor.state)).toBe(false);
    expect(escape(editor)).toBe(false);
  });

  it("is replaced by the next reveal", () => {
    const editor = editorWith("<p>Aetheria rose. Aetheria fell.</p>");
    reveal(editor, "rose");
    reveal(editor, "fell");
    expect(marked(editor)).toEqual(["fell"]);
    expect(selected(editor)).toBe("fell");
  });
});

describe("the search pattern", () => {
  it("is a literal, with whole-word edges as lookarounds", () => {
    expect(findMatches("a.b axb", compileSearchPattern("a.b", false, false))).toEqual([{ start: 0, end: 3 }]);
    expect(findMatches("cat cats scat", compileSearchPattern("cat", false, true))).toEqual([{ start: 0, end: 3 }]);
    // Not `\b`: a query that ends in punctuation still matches whole.
    expect(findMatches("(cat) x", compileSearchPattern("(cat)", false, true))).toEqual([{ start: 0, end: 5 }]);
    expect(findMatches("Cat cat", compileSearchPattern("cat", true, false))).toEqual([{ start: 4, end: 7 }]);
  });
});
