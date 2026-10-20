// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { Schema } from "@tiptap/pm/model";
import { collectSentences } from "./readAloudText";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { content: "inline*", group: "block", toDOM: () => ["p", 0] },
    text: { group: "inline" },
    mutation: { group: "inline", inline: true, atom: true, toDOM: () => ["span", "⤳"] },
  },
  marks: { em: { toDOM: () => ["em", 0] } },
});

const p = (...kids: ReturnType<typeof schema.text>[]) => schema.node("paragraph", null, kids);
const t = (s: string) => schema.text(s);

afterEach(() => vi.unstubAllGlobals());

describe("collectSentences", () => {
  it("splits each paragraph into sentences with exact ranges", () => {
    const doc = schema.node("doc", null, [p(t("One. Two! ")), p(t("Three?"))]);
    const out = collectSentences(doc, 0, doc.content.size);
    expect(out.map((s) => s.text)).toEqual(["One.", "Two!", "Three?"]);
    for (const s of out) expect(doc.textBetween(s.from, s.to)).toBe(s.text);
  });

  it("never spans two blocks and skips empty blocks", () => {
    const doc = schema.node("doc", null, [p(t("No stop")), p(), p(t("  "))]);
    expect(collectSentences(doc, 0, doc.content.size).map((s) => s.text)).toEqual(["No stop"]);
  });

  it("clips to the range, mid-sentence", () => {
    const doc = schema.node("doc", null, [p(t("Alpha beta. Gamma delta."))]);
    // The text starts at position 1; take "beta. Gamma".
    const out = collectSentences(doc, 7, 18);
    expect(out.map((s) => s.text)).toEqual(["beta.", "Gamma"]);
    for (const s of out) expect(doc.textBetween(s.from, s.to)).toBe(s.text);
  });

  it("skips an inline atom and keeps positions mapped, marks keep their text", () => {
    const doc = schema.node("doc", null, [
      p(t("Before "), schema.node("mutation"), t("after. Next "), schema.text("one.", [schema.marks.em.create()])),
    ]);
    const out = collectSentences(doc, 0, doc.content.size);
    expect(out.map((s) => s.text)).toEqual(["Before after.", "Next one."]);
    expect(doc.textBetween(out[1].from, out[1].to)).toBe("Next one.");
    expect(out[0].from).toBe(1);
  });

  it("falls back to punctuation splitting without Intl.Segmenter", () => {
    vi.stubGlobal("Intl", { ...Intl, Segmenter: undefined });
    const doc = schema.node("doc", null, [p(t('He said "Go." Then left. Done'))]);
    const out = collectSentences(doc, 0, doc.content.size);
    expect(out.map((s) => s.text)).toEqual(['He said "Go."', "Then left.", "Done"]);
    for (const s of out) expect(doc.textBetween(s.from, s.to)).toBe(s.text);
  });
});
