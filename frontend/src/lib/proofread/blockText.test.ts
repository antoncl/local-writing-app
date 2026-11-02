// Proofreading (ADR-0102 §2): the text a block is linted as, and the way back
// from an offset in it to a document position — across a hard break, an inline
// atom (the mutation pill is a point with no text) and a character outside the
// Basic Multilingual Plane, which takes two UTF-16 units like any JS string.
import { describe, expect, it } from "vitest";
import { Schema } from "@tiptap/pm/model";
import { blockText, docRange, textBlocks } from "./blockText";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*" },
    codeBlock: { group: "block", content: "text*", code: true },
    text: { group: "inline" },
    hardBreak: { group: "inline", inline: true },
    pill: { group: "inline", inline: true, atom: true },
  },
});
const { doc, paragraph, codeBlock, hardBreak, pill } = schema.nodes;
const t = (s: string) => schema.text(s);

describe("blockText", () => {
  it("joins text, turns a hard break into a newline and skips an atom", () => {
    const d = doc.create(null, [paragraph.create(null, [t("Hello "), pill.create(), t("world"), hardBreak.create(), t("Again")])]);
    const [block] = textBlocks(d);
    expect(block.text).toBe("Hello world\nAgain");
    // Each text unit maps to the document character it came from.
    for (let i = 0; i < block.text.length; i++) {
      const at = block.pos[i];
      expect(d.textBetween(at, at + 1, "\n", "\n")).toBe(block.text[i]);
    }
  });

  it("maps a range past the atom onto the right document text", () => {
    const d = doc.create(null, [paragraph.create(null, [t("Hello "), pill.create(), t("wrold here")])]);
    const [block] = textBlocks(d);
    const from = block.text.indexOf("wrold");
    const range = docRange(block, from, from + 5);
    expect(d.textBetween(range.from, range.to)).toBe("wrold");
  });

  it("puts an insertion right after the text it follows, not after an atom", () => {
    const d = doc.create(null, [paragraph.create(null, [t("end"), pill.create()])]);
    const [block] = textBlocks(d);
    const at = docRange(block, 3, 3);
    expect(at.from).toBe(block.pos[2] + 1);
    expect(at.from).toBe(at.to);
  });

  it("lists prose blocks only, in order, with their content bounds", () => {
    const d = doc.create(null, [paragraph.create(null, [t("One")]), codeBlock.create(null, [t("let x")]), paragraph.create(null, [t("Two")])]);
    const blocks = textBlocks(d);
    expect(blocks.map((b) => b.text)).toEqual(["One", "Two"]);
    expect(d.textBetween(blocks[1].start, blocks[1].end)).toBe("Two");
  });

  it("maps text after an emoji by UTF-16 units", () => {
    const d = doc.create(null, [paragraph.create(null, [t("Go 🙂 teh end")])]);
    const [block] = textBlocks(d);
    const from = block.text.indexOf("teh");
    const range = docRange(block, from, from + 3);
    expect(d.textBetween(range.from, range.to)).toBe("teh");
  });

  it("an empty block has empty text and an insertion point at its start", () => {
    const block = blockText(paragraph.create(), 1);
    expect(block.text).toBe("");
    expect(docRange(block, 0, 0)).toEqual({ from: 1, to: 1 });
  });
});
