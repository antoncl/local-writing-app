// @vitest-environment happy-dom
// #2491: the pill ids before a position, in document order.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { createMutationCloseMark, createMutationMark } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import { markerIdsBefore } from "./markersBefore";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

type Json = Record<string, unknown>;
const pill = (anchorId: string): Json => ({ type: "mutation", attrs: { setId: "mset_1", anchorId } });
const close = (closeId: string): Json => ({ type: "mutationClose", attrs: { ref: "a1", row: "", closeId } });
const text = (t: string): Json => ({ type: "text", text: t });

function docOf(...paragraphs: Json[][]) {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), createMutationMark(), createMutationCloseMark()],
    content: { type: "doc", content: paragraphs.map((content) => ({ type: "paragraph", content })) },
  });
  editors.push(editor);
  return editor.state.doc;
}

describe("markerIdsBefore", () => {
  it("collects anchors and closes before the position, in document order", () => {
    const doc = docOf([text("A"), pill("a1"), text("B")], [close("c1"), text("C"), pill("a2")]);
    expect(markerIdsBefore(doc, doc.content.size)).toEqual(["a1", "c1", "a2"]);
  });

  it("leaves out a pill at or after the position", () => {
    const doc = docOf([text("A"), pill("a1"), text("B"), pill("a2"), text("C")]);
    let pos2 = 0;
    doc.descendants((node, pos) => {
      if (node.type.name === "mutation" && node.attrs.anchorId === "a2") pos2 = pos;
    });
    expect(markerIdsBefore(doc, pos2)).toEqual(["a1"]);
    expect(markerIdsBefore(doc, 1)).toEqual([]);
  });

  it("skips a pill with no id", () => {
    const doc = docOf([pill(""), pill("a1")]);
    expect(markerIdsBefore(doc, doc.content.size)).toEqual(["a1"]);
  });
});
