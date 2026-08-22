// Headless tests for the interiority reveal plugin (ADR-0070 S2). Like the
// document-boundary tests, these drive a real prosemirror EditorState with a
// minimal character-mark schema — no TipTap mount, no DOM. The widget DOM and
// textarea write-back are exercised by live verification instead.
import { describe, expect, it } from "vitest";
import { Schema, type Node as PMNode } from "@tiptap/pm/model";
import { EditorState } from "@tiptap/pm/state";

import {
  createInteriorityPlugin,
  findBeats,
  interiorityHasBeats,
  interiorityAnyRevealed,
  interiorityDecorations,
  INTERIORITY_META,
} from "./interiorityReveal";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*", toDOM: () => ["p", 0] },
    text: { group: "inline" },
  },
  marks: {
    character: {
      attrs: { characterId: { default: null }, internal: { default: "" } },
      toDOM: (m) => ["span", { "data-character": m.attrs.characterId }, 0],
    },
  },
});

const markType = schema.marks.character;

function beat(id: string, text: string, internal = "") {
  return schema.text(text, [markType.create({ characterId: id, internal })]);
}
function para(...inline: PMNode[]) {
  return schema.node("paragraph", null, inline);
}
function stateOf(doc: PMNode): EditorState {
  return EditorState.create({ doc, plugins: [createInteriorityPlugin(() => "")] });
}

// Narration, then an Annie beat; a second paragraph is a Bill beat.
function sampleDoc(): PMNode {
  return schema.node("doc", null, [
    para(schema.text("Narration. "), beat("annie", "She fired.", "Steady now.")),
    para(beat("bill", "He grins.", "She'll miss.")),
  ]);
}

describe("findBeats", () => {
  it("coalesces contiguous same-character text and captures interiority", () => {
    // "She " bold + "fired." plain, both Annie → one beat.
    const doc = schema.node("doc", null, [
      para(beat("annie", "She "), beat("annie", "fired.", "Steady.")),
    ]);
    const beats = findBeats(doc, markType);
    expect(beats).toHaveLength(1);
    expect(beats[0].id).toBe("annie");
    expect(doc.textBetween(beats[0].from, beats[0].to)).toBe("She fired.");
    expect(beats[0].internal).toBe("Steady.");
  });

  it("splits a new beat on narration and on a different character", () => {
    const beats = findBeats(sampleDoc(), markType);
    expect(beats.map((b) => b.id)).toEqual(["annie", "bill"]);
    expect(beats[1].internal).toBe("She'll miss.");
  });

  it("finds nothing in un-marked prose", () => {
    const doc = schema.node("doc", null, [para(schema.text("Just narration."))]);
    expect(findBeats(doc, markType)).toHaveLength(0);
  });
});

describe("reveal state machine", () => {
  it("reports beats present and none revealed initially, one handle per beat", () => {
    const state = stateOf(sampleDoc());
    expect(interiorityHasBeats(state)).toBe(true);
    expect(interiorityAnyRevealed(state)).toBe(false);
    // Two beats → two handles, no blocks yet.
    expect(interiorityDecorations(state).find()).toHaveLength(2);
  });

  it("has no beats in un-marked prose", () => {
    const state = stateOf(schema.node("doc", null, [para(schema.text("nada"))]));
    expect(interiorityHasBeats(state)).toBe(false);
  });

  it("reveal-all opens every beat; collapse-all closes them", () => {
    let state = stateOf(sampleDoc());
    state = state.apply(state.tr.setMeta(INTERIORITY_META.revealAll, true));
    expect(interiorityAnyRevealed(state)).toBe(true);
    // 2 handles + 2 blocks.
    expect(interiorityDecorations(state).find()).toHaveLength(4);

    state = state.apply(state.tr.setMeta(INTERIORITY_META.collapseAll, true));
    expect(interiorityAnyRevealed(state)).toBe(false);
    expect(interiorityDecorations(state).find()).toHaveLength(2);
  });

  it("toggles a single beat by its anchor position", () => {
    let state = stateOf(sampleDoc());
    const anchor = findBeats(state.doc, markType)[0].to;
    state = state.apply(state.tr.setMeta(INTERIORITY_META.toggleOne, anchor));
    expect(interiorityAnyRevealed(state)).toBe(true);
    expect(interiorityDecorations(state).find()).toHaveLength(3); // 2 handles + 1 block
    state = state.apply(state.tr.setMeta(INTERIORITY_META.toggleOne, anchor));
    expect(interiorityAnyRevealed(state)).toBe(false);
  });

  it("keeps a beat revealed when text is inserted before it (position mapping)", () => {
    let state = stateOf(sampleDoc());
    state = state.apply(state.tr.setMeta(INTERIORITY_META.revealAll, true));
    expect(interiorityAnyRevealed(state)).toBe(true);
    // Insert at the very start of the doc — every beat shifts right.
    state = state.apply(state.tr.insertText("X", 1));
    expect(interiorityAnyRevealed(state)).toBe(true);
    expect(interiorityDecorations(state).find()).toHaveLength(4);
  });

  it("prunes a reveal whose beat was deleted", () => {
    let state = stateOf(sampleDoc());
    const bill = findBeats(state.doc, markType)[1];
    state = state.apply(state.tr.setMeta(INTERIORITY_META.revealAll, true));
    expect(interiorityAnyRevealed(state)).toBe(true);
    // Delete Bill's beat text; its anchor no longer lands on a beat end.
    state = state.apply(state.tr.delete(bill.from, bill.to));
    const stillOpen = findBeats(state.doc, markType).length;
    expect(stillOpen).toBe(1); // only Annie remains
    expect(interiorityDecorations(state).find()).toHaveLength(2); // 1 handle + 1 block for Annie
  });
});
