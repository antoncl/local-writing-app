// Headless tests for beat pairing and the beat decoration plugin (ADR-0070,
// Amendment 1). Like the document-boundary tests, these drive a real
// prosemirror EditorState with a minimal two-marker schema — no TipTap mount.
// The close marker's node view is covered in beatCloseView.test.ts.
import { describe, expect, it } from "vitest";
import { Schema, type Node as PMNode } from "@tiptap/pm/model";
import { EditorState } from "@tiptap/pm/state";

import { beatAt, scanBeats } from "./beats";
import {
  createInteriorityPlugin,
  interiorityHasBeats,
  interiorityAnyRevealed,
  interiorityDecorations,
  INTERIORITY_META,
  type BeatMarkerSpec,
} from "./interiorityReveal";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*", toDOM: () => ["p", 0] },
    text: { group: "inline" },
    characterOpen: {
      group: "inline",
      inline: true,
      atom: true,
      attrs: { characterId: { default: "" } },
      toDOM: () => ["span", { "data-character-open": "" }],
    },
    characterClose: {
      group: "inline",
      inline: true,
      atom: true,
      attrs: { characterId: { default: "" }, internal: { default: "" } },
      toDOM: () => ["span", { "data-character-close": "" }],
    },
  },
});

const open = (id: string) => schema.node("characterOpen", { characterId: id });
const close = (id: string, internal = "") => schema.node("characterClose", { characterId: id, internal });
const text = (t: string) => schema.text(t);
function para(...inline: PMNode[]) {
  return schema.node("paragraph", null, inline);
}
function stateOf(doc: PMNode): EditorState {
  return EditorState.create({
    doc,
    plugins: [createInteriorityPlugin({ colorForId: () => "", titleForId: (id) => id })],
  });
}

/** The marker specs of every node decoration, in document order. */
function markerSpecs(state: EditorState): (BeatMarkerSpec & { pos: number })[] {
  return interiorityDecorations(state)
    .find()
    .filter((d) => (d.spec as { beatMarker?: BeatMarkerSpec }).beatMarker)
    .map((d) => ({ ...(d.spec as { beatMarker: BeatMarkerSpec }).beatMarker, pos: d.from }));
}
const underlines = (state: EditorState) =>
  interiorityDecorations(state)
    .find()
    .filter((d) => !(d.spec as { beatMarker?: BeatMarkerSpec }).beatMarker);

// Narration, then an Annie beat across two paragraphs, then a Bill beat.
function sampleDoc(): PMNode {
  return schema.node("doc", null, [
    para(text("Narration. "), open("annie"), text("She fired.")),
    para(text("Then ran."), close("annie", "Steady now.")),
    para(open("bill"), text("He grins."), close("bill", "She'll miss.")),
  ]);
}

describe("scanBeats", () => {
  it("pairs markers in order, a beat spanning paragraphs, its interiority from the close", () => {
    const { beats, orphans } = scanBeats(sampleDoc());
    expect(beats.map((b) => [b.characterId, b.internal])).toEqual([
      ["annie", "Steady now."],
      ["bill", "She'll miss."],
    ]);
    expect(orphans).toEqual([]);
  });

  it("treats an open marker followed by another open as an orphan (beats never nest)", () => {
    const doc = schema.node("doc", null, [para(open("annie"), text("a "), open("bill"), text("b"), close("bill"))]);
    const { beats, orphans } = scanBeats(doc);
    expect(beats.map((b) => b.characterId)).toEqual(["bill"]);
    expect(orphans).toEqual([1]);
  });

  it("treats a close with no open, and an unclosed open, as orphans", () => {
    const doc = schema.node("doc", null, [para(text("a"), close("annie"), text("b "), open("annie"), text("c"))]);
    const { beats, orphans } = scanBeats(doc);
    expect(beats).toEqual([]);
    expect(orphans).toHaveLength(2);
  });

  it("makes both markers orphans when the close names another character", () => {
    // A deletion from inside Annie's beat to past Bill's open marker: Annie's open
    // now meets Bill's close. Neither may hand its text or interiority over.
    const doc = schema.node("doc", null, [para(open("annie"), text("a b"), close("bill", "Bill's secret"))]);
    const { beats, orphans } = scanBeats(doc);
    expect(beats).toEqual([]);
    expect(orphans).toHaveLength(2);
  });

  it("finds the beat around a position, and none just after its close", () => {
    const state = stateOf(sampleDoc());
    const [annie] = scanBeats(state.doc).beats;
    expect(beatAt(state, annie.open + 1)?.characterId).toBe("annie");
    expect(beatAt(state, annie.close)?.characterId).toBe("annie");
    expect(beatAt(state, annie.close + 1)).toBeNull();
    expect(beatAt(state, annie.open)).toBeNull();
  });
});

describe("beat decorations", () => {
  it("underlines each beat once and marks both of its markers", () => {
    const state = stateOf(sampleDoc());
    expect(interiorityHasBeats(state)).toBe(true);
    expect(interiorityAnyRevealed(state)).toBe(false);
    // One inline decoration per beat, spanning from after the open to the close.
    const [annie, bill] = scanBeats(state.doc).beats;
    expect(underlines(state).map((d) => [d.from, d.to])).toEqual([
      [annie.open + 1, annie.close],
      [bill.open + 1, bill.close],
    ]);
    expect(markerSpecs(state).map((s) => [s.characterId, s.broken])).toEqual([
      ["annie", false],
      ["annie", false],
      ["bill", false],
      ["bill", false],
    ]);
  });

  it("marks an orphan broken and underlines nothing for it", () => {
    const state = stateOf(schema.node("doc", null, [para(open("annie"), text("Alone."))]));
    expect(interiorityHasBeats(state)).toBe(false);
    expect(underlines(state)).toHaveLength(0);
    expect(markerSpecs(state)).toEqual([{ characterId: "", revealed: false, broken: true, pos: 1 }]);
  });

  it("puts the state a node view reacts to in the decoration's attrs", () => {
    // ProseMirror compares node decorations by attrs only.
    const state = stateOf(sampleDoc());
    const [, annieClose] = interiorityDecorations(state).find().filter((d) => d.spec.beatMarker);
    const toggled = state.apply(state.tr.setMeta(INTERIORITY_META.toggleOne, annieClose.from));
    const after = interiorityDecorations(toggled).find(annieClose.from, annieClose.to).find((d) => d.spec.beatMarker);
    expect((annieClose as unknown as { type: { attrs: object } }).type.attrs).not.toEqual(
      (after as unknown as { type: { attrs: object } }).type.attrs,
    );
  });
});

describe("reveal state machine", () => {
  const closes = (state: EditorState) => scanBeats(state.doc).beats.map((b) => b.close);
  const revealedCloses = (state: EditorState) =>
    markerSpecs(state)
      .filter((s) => s.revealed)
      .map((s) => s.pos);

  it("reveal-all opens every beat; collapse-all closes them", () => {
    let state = stateOf(sampleDoc());
    state = state.apply(state.tr.setMeta(INTERIORITY_META.revealAll, true));
    expect(revealedCloses(state)).toEqual(closes(state));
    state = state.apply(state.tr.setMeta(INTERIORITY_META.collapseAll, true));
    expect(interiorityAnyRevealed(state)).toBe(false);
  });

  it("toggles a single beat by its close marker", () => {
    let state = stateOf(sampleDoc());
    const [first] = closes(state);
    state = state.apply(state.tr.setMeta(INTERIORITY_META.toggleOne, first));
    expect(revealedCloses(state)).toEqual([first]);
    state = state.apply(state.tr.setMeta(INTERIORITY_META.toggleOne, first));
    expect(interiorityAnyRevealed(state)).toBe(false);
  });

  it("reveals a given set of close markers", () => {
    let state = stateOf(sampleDoc());
    state = state.apply(state.tr.setMeta(INTERIORITY_META.reveal, closes(state)));
    expect(revealedCloses(state)).toEqual(closes(state));
  });

  it("keeps a beat revealed when text is typed inside it, right before its close", () => {
    let state = stateOf(sampleDoc());
    const [first] = closes(state);
    state = state.apply(state.tr.setMeta(INTERIORITY_META.toggleOne, first));
    state = state.apply(state.tr.insertText("!", first));
    expect(revealedCloses(state)).toEqual([first + 1]);
  });

  it("prunes a reveal whose close marker was deleted", () => {
    let state = stateOf(sampleDoc());
    const [first] = closes(state);
    state = state.apply(state.tr.setMeta(INTERIORITY_META.toggleOne, first));
    state = state.apply(state.tr.delete(first, first + 1));
    expect(interiorityAnyRevealed(state)).toBe(false);
  });
});
