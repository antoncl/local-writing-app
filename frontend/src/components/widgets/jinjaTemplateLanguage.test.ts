import { describe, expect, it } from "vitest";
import { StringStream } from "@codemirror/language";
import { jinjaTemplateParser, type TemplateState } from "./jinjaTemplateLanguage";

// Tokenize a template the way CodeMirror's StreamLanguage does, line by line,
// returning [text, style] pairs (style null = unstyled prose).
function tokens(src: string): [string, string | null][] {
  const state: TemplateState = jinjaTemplateParser.startState!(2);
  const out: [string, string | null][] = [];
  for (const line of src.split("\n")) {
    const stream = new StringStream(line, 2, 2);
    while (!stream.eol()) {
      const style = jinjaTemplateParser.token(stream, state);
      out.push([stream.current(), style]);
      stream.start = stream.pos;
    }
  }
  return out.filter(([text]) => text.trim() !== "");
}

const styled = (src: string) => tokens(src).filter(([, s]) => s !== null && s !== "heading");

describe("jinjaTemplateLanguage (#2496)", () => {
  it("a # heading is prose: an apostrophe in it opens no string, and later prose is not code", () => {
    const src = [
      "# WORKING PRINCIPLES (apply McKee — don't recite him)",
      "- Every scene is a story in miniature: it must turn.",
      "**3. Desire.** The objective in this scene, now; and by level.",
    ].join("\n");
    expect(styled(src)).toEqual([]);
    expect(tokens(src)[0]).toEqual(["# WORKING PRINCIPLES (apply McKee — don't recite him)", "heading"]);
    expect(tokens(src).slice(1).every(([, s]) => s === null)).toBe(true);
  });

  it("keywords are keywords only inside a tag", () => {
    expect(styled("if this and that, by now {% if a and not b %}")).toEqual([
      ["{%", "meta"],
      ["if", "keyword"],
      ["a", "variableName"],
      ["and", "keyword"],
      ["not", "keyword"],
      ["b", "variableName"],
      ["%}", "meta"],
    ]);
  });

  it("an expression: names, strings, numbers, constants, operators, and its close", () => {
    expect(styled('{{ e.title | default("—", true) ~ 2 }}')).toEqual([
      ["{{", "meta"],
      ["e", "variableName"],
      [".", "operator"],
      ["title", "variableName"],
      ["|", "operator"],
      ["default", "variableName"],
      ["(", "operator"],
      ['"—"', "string"],
      [",", "operator"],
      ["true", "atom"],
      [")", "operator"],
      ["~", "operator"],
      ["2", "number"],
      ["}}", "meta"],
    ]);
  });

  it("a string holding }} doesn't close its tag; whitespace-control markers close it", () => {
    expect(styled('{{ "}}" }} after {%- set x = 1 -%}')).toEqual([
      ["{{", "meta"],
      ['"}}"', "string"],
      ["}}", "meta"],
      ["{%-", "meta"],
      ["set", "keyword"],
      ["x", "variableName"],
      ["=", "operator"],
      ["1", "number"],
      ["-%}", "meta"],
    ]);
  });

  it("a comment runs across lines to its #}, then prose resumes", () => {
    const t = tokens("{# one\ntwo #} and back");
    expect(t).toEqual([
      ["{#", "comment"],
      [" one", "comment"],
      ["two #}", "comment"],
      [" and back", null],
    ]);
  });

  it("a tag spanning lines stays a tag; a heading flag never leaks into it", () => {
    const t = styled("# Head {% if a\nand b %} tail");
    expect(t).toEqual([
      ["{%", "meta"],
      ["if", "keyword"],
      ["a", "variableName"],
      ["and", "keyword"],
      ["b", "variableName"],
      ["%}", "meta"],
    ]);
    expect(tokens("# Head {% if a\nand b %} tail").at(-1)).toEqual([" tail", null]);
  });
});
