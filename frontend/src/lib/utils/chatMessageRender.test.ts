// @vitest-environment happy-dom
// KaTeX (#542) is lazy-loaded, so these tests exercise the pre-load path:
// `containsMath` (the cheap gate that decides whether to trigger the download)
// and `renderChatContent` rendering the escaped `katex-error` placeholder when
// KaTeX hasn't resolved yet. The dynamic `import("katex")` is intentionally
// not awaited/resolved here — that's covered by exercising the app, not a unit test.
import { describe, it, expect } from "vitest";
import { renderChatContent, containsMath, outdentIndentedLists } from "./chatMessageRender";

describe("containsMath", () => {
  it("is true for inline math", () => {
    expect(containsMath("$x^2$")).toBe(true);
  });

  it("is true for block math", () => {
    expect(containsMath("$$a$$")).toBe(true);
  });

  it("is false for text with no math delimiters", () => {
    expect(containsMath("no math here")).toBe(false);
  });

  it("is false for an empty string", () => {
    expect(containsMath("")).toBe(false);
  });

  it("is false for null", () => {
    expect(containsMath(null)).toBe(false);
  });

  it("is false for an escaped dollar sign", () => {
    expect(containsMath("price \\$5")).toBe(false);
  });
});

describe("renderChatContent", () => {
  it("returns sanitized HTML for plain markdown and does not throw", () => {
    expect(() => renderChatContent("plain **bold** text")).not.toThrow();
    expect(renderChatContent("plain **bold** text")).toContain("<strong>");
  });

  it("falls back to the escaped katex-error placeholder when KaTeX isn't loaded", () => {
    expect(() => renderChatContent("inline $x^2$ math")).not.toThrow();
    expect(renderChatContent("inline $x^2$ math")).toContain("katex-error");
  });

  it("returns an empty string for empty input", () => {
    expect(renderChatContent("")).toBe("");
  });
});

// #2283: the shape a Gemma build on Ollama writes its thinking in — every list
// indented four spaces, groups split by blank lines. Unfixed, CommonMark reads
// the post-blank-line groups as an indented code block (a <pre> that never
// wraps, so the thinking text looks clipped).
const INDENTED_LISTS = [
  "Weighing the options for the spine.",
  "    *   *Option 1:* the first idea, stated at length.",
  "",
  "    *   *Option 2:* another idea that runs long enough to need wrapping.",
  "        *   *Nested:* a sub-point under option two.",
  "",
  "    *   *Verdict:* go with option two.",
].join("\n");

describe("outdentIndentedLists (#2283)", () => {
  it("renders a model's 4-space-indented lists as a list, not a code block", () => {
    const html = renderChatContent(INDENTED_LISTS);
    expect(html).not.toContain("<pre");
    expect(html).toContain("<li>");
    expect(html).toContain("<em>Verdict:</em>");
    // Nesting keeps its relative depth.
    expect(html).toMatch(/<ul>[\s\S]*<ul>[\s\S]*Nested[\s\S]*<\/ul>/);
  });

  it("leaves text alone when a list already starts at the margin", () => {
    const text = "* top\n    * nested four deep";
    expect(outdentIndentedLists(text)).toBe(text);
  });

  it("never touches fenced code, even indented", () => {
    const text = ["    * item", "```", "    indented code stays", "```"].join("\n");
    expect(outdentIndentedLists(text)).toBe(["* item", "```", "    indented code stays", "```"].join("\n"));
  });

  it("leaves a message with no lists alone, so a real indented code block still renders as code", () => {
    const text = "Here is code:\n\n    const x = 1;";
    expect(outdentIndentedLists(text)).toBe(text);
    expect(renderChatContent(text)).toContain("<pre");
  });
});
