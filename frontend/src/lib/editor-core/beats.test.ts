// The pure beat helpers a real ProseMirror doc needs (ADR-0070 Amendment 1).
// Pairing itself is covered with the decoration plugin in interiorityReveal.test.ts.
import { describe, expect, it } from "vitest";
import { Schema } from "@tiptap/pm/model";

import { modelLeafText, rangeHasBeatMarker } from "./beats";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*" },
    text: { group: "inline" },
    pill: { group: "inline", inline: true, atom: true },
    characterOpen: { group: "inline", inline: true, atom: true, attrs: { characterId: { default: "" } } },
    characterClose: {
      group: "inline",
      inline: true,
      atom: true,
      attrs: { characterId: { default: "" }, internal: { default: "" } },
    },
  },
});

// "a" ⌜ "She fired." ⌟ ⤳ "b"
const doc = schema.node("doc", null, [
  schema.node("paragraph", null, [
    schema.text("a"),
    schema.node("characterOpen", { characterId: "lore_1" }),
    schema.text("She fired."),
    schema.node("characterClose", { characterId: "lore_1" }),
    schema.node("pill"),
    schema.text("b"),
  ]),
]);

describe("rangeHasBeatMarker", () => {
  it("finds a marker in the range, and none in text inside the beat", () => {
    expect(rangeHasBeatMarker(doc, 1, 6)).toBe(true);
    expect(rangeHasBeatMarker(doc, 3, 8)).toBe(false);
  });
});

describe("modelLeafText", () => {
  it("adds nothing for a beat marker, and a space for any other leaf", () => {
    expect(doc.textBetween(0, doc.content.size, "\n\n", modelLeafText)).toBe("aShe fired. b");
  });
});
