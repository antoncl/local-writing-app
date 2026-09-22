// @vitest-environment happy-dom
// The search-match reveal (#1925) against a real TipTap editor: opening a hit
// marks every match of the query and puts the caret at the one the hit
// names — identified by its neighbourhood, the ordinal breaking ties; an
// edit, Escape or a new reveal ends it.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import {
  chooseMatch,
  compileSearchPattern,
  findMatches,
  findMatchesInContext,
  firstMatchPosition,
  SearchMatchHighlight,
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

/** A reveal as the pane sends it: the excerpt defaults to the query itself
 *  (no neighbourhood to go on), so the ordinal decides. */
const reveal = (editor: Editor, query: string, ordinal = 0, options: Partial<SearchReveal> = {}): boolean =>
  editor.commands.revealSearchMatch({ query, matchCase: false, wholeWord: false, excerpt: query, ordinal, ...options });
/** The text of every marked span, in document order — a match that crosses a
 *  formatting boundary renders as more than one span. */
const marked = (editor: Editor): string[] =>
  Array.from(editor.view.dom.querySelectorAll(".search-match"), (el) => el.textContent ?? "");
const currentMark = (editor: Editor): string | null =>
  editor.view.dom.querySelector(".search-match-current")?.textContent ?? null;
/** The caret is collapsed; the text right after it says where it landed. */
const caretBefore = (editor: Editor, chars: number): string => {
  const { from, empty } = editor.state.selection;
  if (!empty) throw new Error("the reveal must leave a caret, not a selection");
  return editor.state.doc.textBetween(from, Math.min(from + chars, editor.state.doc.content.size));
};
/** Send Escape to the editor; whether the editor consumed it. */
const escape = (editor: Editor): boolean => {
  const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  editor.view.dom.dispatchEvent(event);
  return event.defaultPrevented;
};

describe("search-match reveal", () => {
  it("marks every match and puts the caret at the one the ordinal names", () => {
    const editor = editorWith("<p>Aetheria rose.</p><p>Then Aetheria fell.</p>");
    expect(reveal(editor, "aetheria", 1)).toBe(true);

    expect(marked(editor)).toEqual(["Aetheria", "Aetheria"]);
    expect(currentMark(editor)).toBe("Aetheria");
    expect(caretBefore(editor, 13)).toBe("Aetheria fell");
  });

  it("lands on the last match for an ordinal past the end", () => {
    const editor = editorWith("<p>Aetheria rose.</p><p>Then Aetheria fell.</p>");
    expect(reveal(editor, "aetheria", 7)).toBe(true);
    expect(caretBefore(editor, 13)).toBe("Aetheria fell");
  });

  it("identifies the match by its neighbourhood before its ordinal", () => {
    // The corpus counted an occurrence the editor does not show (a link's
    // URL, a comment): the ordinal is off, the excerpt is not.
    const editor = editorWith("<p>Aetheria rose.</p><p>Then Aetheria fell.</p>");
    expect(reveal(editor, "aetheria", 0, { excerpt: "Then Aetheria fell." })).toBe(true);
    expect(caretBefore(editor, 13)).toBe("Aetheria fell");
    expect(reveal(editor, "aetheria", 1, { excerpt: "Aetheria rose." })).toBe(true);
    expect(caretBefore(editor, 13)).toBe("Aetheria rose");
  });

  it("marks nothing and reports false when the document has no match — and drops the previous reveal", () => {
    const editor = editorWith("<p>Aetheria rose.</p>");
    reveal(editor, "rose");
    expect(marked(editor)).toEqual(["rose"]);
    expect(reveal(editor, "citadel")).toBe(false);
    expect(marked(editor)).toEqual([]);
  });

  it("finds a match that crosses a formatting boundary", () => {
    const editor = editorWith("<p>Ae<strong>theria</strong> rose.</p>");
    expect(reveal(editor, "aetheria")).toBe(true);
    expect(marked(editor).join("")).toBe("Aetheria");
    expect(caretBefore(editor, 2)).toBe("Ae");
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
    editor.commands.insertContent("x");
    expect(marked(editor)).toEqual([]);
  });

  it("ends with Escape, which it consumes — and leaves alone when nothing is revealed", () => {
    const editor = editorWith("<p>Aetheria rose.</p>");
    expect(escape(editor)).toBe(false);

    reveal(editor, "aetheria");
    expect(escape(editor)).toBe(true);
    expect(marked(editor)).toEqual([]);
    expect(escape(editor)).toBe(false);
  });

  it("is replaced by the next reveal", () => {
    const editor = editorWith("<p>Aetheria rose. Aetheria fell.</p>");
    reveal(editor, "rose");
    reveal(editor, "fell");
    expect(marked(editor)).toEqual(["fell"]);
    expect(caretBefore(editor, 4)).toBe("fell");
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

  it("treats a letter outside ASCII as a word character, as the backend does", () => {
    expect(findMatches("Bürgermeister meister", compileSearchPattern("meister", false, true))).toEqual([
      { start: 14, end: 21 },
    ]);
    expect(findMatches("naïve ve", compileSearchPattern("ve", false, true))).toEqual([{ start: 6, end: 8 }]);
  });
});

describe("chooseMatch", () => {
  const found = { query: "Aetheria", matchCase: false, wholeWord: false };
  const candidates = (line: string) => findMatchesInContext(line, compileSearchPattern("Aetheria", false, false));

  it("picks the match whose neighbourhood agrees with the excerpt", () => {
    const line = "Aetheria rose at dawn. By dusk Aetheria had fallen, and Aetheria wept.";
    expect(chooseMatch(candidates(line), { ...found, excerpt: "dusk Aetheria had", ordinal: 0 })).toBe(1);
    expect(chooseMatch(candidates(line), { ...found, excerpt: "and Aetheria wept.", ordinal: 0 })).toBe(2);
  });

  it("breaks a tie between identical neighbourhoods by the ordinal", () => {
    const line = "Aetheria. Aetheria. Aetheria.";
    expect(chooseMatch(candidates(line), { ...found, excerpt: "Aetheria. Aetheria. Aetheria.", ordinal: 2 })).toBe(2);
    expect(chooseMatch(candidates(line), { ...found, excerpt: "Aetheria.", ordinal: 1 })).toBe(1);
  });

  it("is -1 with nothing to choose from", () => {
    expect(chooseMatch([], { ...found, excerpt: "Aetheria", ordinal: 0 })).toBe(-1);
  });
});

// #2124: the first-mention reveal picks the earliest of several candidate
// names — built on the same scan+pattern the search-hit reveal uses.
describe("firstMatchPosition", () => {
  it("returns the earliest position for a name that occurs more than once", () => {
    const editor = editorWith("<p>Then the Captain spoke. Later, the Captain left.</p>");
    const pos = firstMatchPosition(editor.state.doc, "the Captain", { matchCase: false, wholeWord: true });
    expect(pos).not.toBeNull();
    expect(editor.state.doc.textBetween(pos!, pos! + 11)).toBe("the Captain");
  });

  it("is null for a name absent from the document", () => {
    const editor = editorWith("<p>Nothing here but quiet.</p>");
    expect(firstMatchPosition(editor.state.doc, "the Captain", { matchCase: false, wholeWord: true })).toBeNull();
  });

  it("respects wholeWord — a name that is only a substring does not match", () => {
    const editor = editorWith("<p>The Captaincy was a formality.</p>");
    expect(firstMatchPosition(editor.state.doc, "Captain", { matchCase: false, wholeWord: true })).toBeNull();
    expect(firstMatchPosition(editor.state.doc, "Captain", { matchCase: false, wholeWord: false })).not.toBeNull();
  });
});
