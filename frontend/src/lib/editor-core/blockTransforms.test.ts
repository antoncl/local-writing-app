// @vitest-environment happy-dom
// The Style menu's block transforms against a real TipTap editor (#1893):
// the partial-selection extraction the body always had is now the one
// implementation every prose editor uses.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { setSelectionHeading, wrapSelectionBlock } from "./blockTransforms";

// Every editor is destroyed after its test — a live view schedules a DOM
// observer flush that would fire after the environment is torn down.
const editors: Editor[] = [];

function editorWith(html: string): Editor {
  const editor = new Editor({ element: document.createElement("div"), extensions: [StarterKit], content: html });
  editors.push(editor);
  return editor;
}

afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

/** Select `text` inside the (single) paragraph at document position 0. */
function select(ed: Editor, text: string) {
  const paragraphText = ed.state.doc.textBetween(0, ed.state.doc.content.size, " ");
  const start = paragraphText.indexOf(text);
  if (start < 0) throw new Error(`"${text}" not in "${paragraphText}"`);
  // +1 skips the paragraph's opening token.
  ed.commands.setTextSelection({ from: start + 1, to: start + 1 + text.length });
}

describe("setSelectionHeading", () => {
  it("extracts a partial selection into its own heading, leaving the rest as paragraphs", () => {
    const ed = editorWith("<p>before middle after</p>");
    select(ed, "middle");
    setSelectionHeading(ed, 2);
    expect(ed.getHTML()).toBe("<p>before </p><h2>middle</h2><p> after</p>");
  });

  it("sets the whole paragraph when the selection covers it; re-applying is a no-op, not a toggle", () => {
    const ed = editorWith("<p>whole</p>");
    select(ed, "whole");
    setSelectionHeading(ed, 1);
    expect(ed.getHTML()).toBe("<h1>whole</h1>");
    setSelectionHeading(ed, 1);
    expect(ed.getHTML()).toBe("<h1>whole</h1>");
  });
});

describe("wrapSelectionBlock", () => {
  it("extracts a partial selection into a list item / quote", () => {
    const ed = editorWith("<p>one two three</p>");
    select(ed, "two");
    wrapSelectionBlock(ed, "bulletList");
    expect(ed.getHTML()).toBe("<p>one </p><ul><li><p>two</p></li></ul><p> three</p>");

    const quoted = editorWith("<p>one two three</p>");
    select(quoted, "three");
    wrapSelectionBlock(quoted, "blockquote");
    expect(quoted.getHTML()).toBe("<p>one two </p><blockquote><p>three</p></blockquote>");
  });

  it("toggles the whole block when the selection covers it", () => {
    const ed = editorWith("<p>all of it</p>");
    select(ed, "all of it");
    wrapSelectionBlock(ed, "orderedList");
    expect(ed.getHTML()).toBe("<ol><li><p>all of it</p></li></ol>");
    wrapSelectionBlock(ed, "orderedList");
    expect(ed.getHTML()).toBe("<p>all of it</p>");
  });
});
