// @vitest-environment happy-dom
// #2460: placing a model's {find, replace, reason} edits on the revised selection.
import { afterEach, describe, expect, it } from "vitest";
import { Editor, type JSONContent } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import { locateQuote, placeLineEdits, placeLineNotes } from "./lineEdits";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

function docOf(...paragraphs: JSONContent[][]) {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit()],
    content: { type: "doc", content: paragraphs.map((content) => ({ type: "paragraph", content })) },
  });
  editors.push(editor);
  return editor.state.doc;
}
const text = (t: string) => ({ type: "text", text: t });
const edit = (find: string, replace: string, reason = "r") => ({ find, replace, reason });
const whole = (doc: ReturnType<typeof docOf>) => [0, doc.content.size] as const;

describe("placeLineEdits", () => {
  it("places a unique find at its document range", () => {
    const doc = docOf([text("The cat sat on the mat.")]);
    const { placed, dropped } = placeLineEdits(doc, ...whole(doc), [edit("cat", "dog")]);
    expect(dropped).toBe(0);
    expect(placed).toHaveLength(1);
    expect(doc.textBetween(placed[0].from, placed[0].to)).toBe("cat");
    expect(placed[0]).toMatchObject({ replace: "dog", reason: "r" });
  });

  it("drops a find that is absent", () => {
    const doc = docOf([text("The cat sat.")]);
    expect(placeLineEdits(doc, ...whole(doc), [edit("bird", "dog")])).toEqual({ placed: [], dropped: 1 });
  });

  it("drops an ambiguous find (twice in one block, or once in each of two)", () => {
    const doc = docOf([text("the cat and the cat")], [text("the cat")]);
    expect(placeLineEdits(doc, ...whole(doc), [edit("the cat", "x")]).dropped).toBe(1);
    const two = docOf([text("a cat")], [text("a cat")]);
    expect(placeLineEdits(two, ...whole(two), [edit("a cat", "x")]).dropped).toBe(1);
  });

  it("drops a later edit that overlaps an earlier one (model order wins)", () => {
    const doc = docOf([text("quick brown fox")]);
    const { placed, dropped } = placeLineEdits(doc, ...whole(doc), [edit("quick brown", "slow"), edit("brown fox", "dog")]);
    expect(dropped).toBe(1);
    expect(placed).toHaveLength(1);
    expect(placed[0].replace).toBe("slow");
  });

  it("ignores a no-op edit without counting it as dropped", () => {
    const doc = docOf([text("same")]);
    expect(placeLineEdits(doc, ...whole(doc), [edit("same", "same")])).toEqual({ placed: [], dropped: 0 });
  });

  it("never spans two paragraphs", () => {
    const doc = docOf([text("end of one")], [text("start of two")]);
    expect(placeLineEdits(doc, ...whole(doc), [edit("one\n\nstart", "x"), edit("one start", "x")]).dropped).toBe(2);
  });

  it("only looks inside the selection", () => {
    const doc = docOf([text("alpha beta gamma")]);
    // doc positions: paragraph content starts at 1; select "alpha " only.
    const { placed, dropped } = placeLineEdits(doc, 1, 7, [edit("gamma", "x"), edit("alpha", "y")]);
    expect(dropped).toBe(1);
    expect(placed.map((p) => p.replace)).toEqual(["y"]);
  });

  it("sorts placed edits by position, whatever order the model gave", () => {
    const doc = docOf([text("one two three")]);
    const { placed } = placeLineEdits(doc, ...whole(doc), [edit("three", "3"), edit("one", "1")]);
    expect(placed.map((p) => p.find)).toEqual(["one", "three"]);
  });

  it("matches a straight-quoted find against curly quotes, and keeps the document's own text", () => {
    const doc = docOf([text("She said “hello” and it’s fine.")]);
    const { placed, dropped } = placeLineEdits(doc, ...whole(doc), [edit("said \"hello\" and it's", "x")]);
    expect(dropped).toBe(0);
    expect(doc.textBetween(placed[0].from, placed[0].to)).toBe("said “hello” and it’s");
    expect(placed[0].find).toBe("said “hello” and it’s");
  });

  it("matches a hyphen find against an em or en dash", () => {
    const doc = docOf([text("wait—what, 1–2?")]);
    const { placed } = placeLineEdits(doc, ...whole(doc), [edit("wait-what", "x"), edit("1-2", "y")]);
    expect(placed.map((p) => p.find)).toEqual(["wait—what", "1–2"]);
  });

  it("matches a plain space against a non-breaking space", () => {
    const doc = docOf([text("ten pages and two")]);
    const { placed } = placeLineEdits(doc, ...whole(doc), [edit("ten pages", "x"), edit("and two", "y")]);
    expect(placed.map((p) => p.find)).toEqual(["ten pages", "and two"]);
  });

  it("counts uniqueness on the normalized text", () => {
    const doc = docOf([text("“hi” and \"hi\"")]);
    expect(placeLineEdits(doc, ...whole(doc), [edit("\"hi\"", "x")])).toMatchObject({ placed: [], dropped: 1 });
  });

  it("a hard break is a sentinel: a find can't span it", () => {
    const doc = docOf([text("line one"), { type: "hardBreak" }, text("line two")]);
    expect(placeLineEdits(doc, ...whole(doc), [edit("one line", "x")]).dropped).toBe(1);
    const { placed } = placeLineEdits(doc, ...whole(doc), [edit("line two", "L2")]);
    expect(doc.textBetween(placed[0].from, placed[0].to)).toBe("line two");
  });

  it("matches across a formatting boundary", () => {
    const doc = docOf([text("a "), { type: "text", text: "bold", marks: [{ type: "bold" }] }, text(" word")]);
    const { placed } = placeLineEdits(doc, ...whole(doc), [edit("a bold word", "x")]);
    expect(placed).toHaveLength(1);
    expect(doc.textBetween(placed[0].from, placed[0].to)).toBe("a bold word");
  });
});

describe("locateQuote", () => {
  it("returns the range and the document's own text for a unique quote", () => {
    const doc = docOf([text("The cat sat on the mat.")]);
    const hit = locateQuote(doc, ...whole(doc), "cat sat");
    expect(hit).not.toBeNull();
    expect(doc.textBetween(hit!.from, hit!.to)).toBe("cat sat");
    expect(hit!.text).toBe("cat sat");
  });

  it("is null for an absent, empty or ambiguous quote", () => {
    const doc = docOf([text("the cat and the cat")]);
    expect(locateQuote(doc, ...whole(doc), "bird")).toBeNull();
    expect(locateQuote(doc, ...whole(doc), "")).toBeNull();
    expect(locateQuote(doc, ...whole(doc), "the cat")).toBeNull();
  });

  it("looks only inside the given range", () => {
    const doc = docOf([text("alpha beta")], [text("gamma")]);
    expect(locateQuote(doc, 0, 8, "gamma")).toBeNull();
    expect(locateQuote(doc, ...whole(doc), "gamma")).not.toBeNull();
  });

  it("returns the document's own typography for a flattened quote", () => {
    const doc = docOf([text("She said “hi” twice")]);
    expect(locateQuote(doc, ...whole(doc), '"hi"')?.text).toBe("“hi”");
  });
});

describe("placeLineNotes", () => {
  const note = (quote: string, problem = "p", entry = "lore_1") => ({ quote, problem, entry });

  it("places a unique quote with the document's own text, problem and entry", () => {
    const doc = docOf([text("The cat sat on the mat.")]);
    const { placed, dropped } = placeLineNotes(doc, ...whole(doc), [note("cat sat", "wrong species", "lore_9")]);
    expect(dropped).toBe(0);
    expect(placed).toHaveLength(1);
    expect(doc.textBetween(placed[0].from, placed[0].to)).toBe("cat sat");
    expect(placed[0]).toMatchObject({ quote: "cat sat", problem: "wrong species", entry: "lore_9" });
  });

  it("allows overlapping notes (unlike edits) and sorts them by position", () => {
    const doc = docOf([text("quick brown fox")]);
    const { placed, dropped } = placeLineNotes(doc, ...whole(doc), [note("brown fox"), note("quick brown")]);
    expect(dropped).toBe(0);
    expect(placed.map((p) => p.quote)).toEqual(["quick brown", "brown fox"]);
    expect(placed[0].to).toBeGreaterThan(placed[1].from);
  });

  it("drops absent, empty and non-unique quotes", () => {
    const doc = docOf([text("a cat and a cat")]);
    expect(placeLineNotes(doc, ...whole(doc), [note("dog"), note(""), note("a cat")])).toEqual({ placed: [], dropped: 3 });
  });

  it("matches through typographic normalization", () => {
    const doc = docOf([text("ten pages — and “two”")]);
    const { placed } = placeLineNotes(doc, ...whole(doc), [note('pages - and "two"')]);
    expect(placed[0].quote).toBe("pages — and “two”");
  });
});
