// @vitest-environment happy-dom
// markdownOffsetAt (ADR-0089 §4, #2072): a ProseMirror doc position mapped to
// its scene-markdown char offset, over a REAL editor doc/schema (the same
// production extension set proseRoundTrip.test.ts mounts) so the mapping is
// pinned against the TipTap version in the lockfile, not a hand-rolled stub.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import { markdownOffsetAt } from "./markdownOffset";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

function mount(html: string): Editor {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit()],
    content: html,
  });
  editors.push(editor);
  return editor;
}

describe("markdownOffsetAt", () => {
  it("maps a doc position to the markdown length of everything before it", () => {
    const editor = mount("<p>Alice arrives.</p><p>Bob leaves.</p>");
    // The position right at the start of the second paragraph's text.
    const secondParaStart = editor.state.doc.content.firstChild!.nodeSize + 1;
    const offset = markdownOffsetAt(editor.state.doc, editor.state.schema, secondParaStart);
    expect(offset).toBe("Alice arrives.".length);
  });

  it("maps the very start of the doc to offset 0", () => {
    const editor = mount("<p>Hello.</p>");
    expect(markdownOffsetAt(editor.state.doc, editor.state.schema, 0)).toBe(0);
  });

  it("clamps an out-of-range position to the document's bounds", () => {
    const editor = mount("<p>Hi.</p>");
    const end = editor.state.doc.content.size;
    const atEnd = markdownOffsetAt(editor.state.doc, editor.state.schema, end);
    expect(markdownOffsetAt(editor.state.doc, editor.state.schema, end + 999)).toBe(atEnd);
    expect(markdownOffsetAt(editor.state.doc, editor.state.schema, -5)).toBe(0);
  });
});
