// @vitest-environment happy-dom
// KaTeX (#542) is lazy-loaded, so these tests exercise the pre-load path:
// `containsMath` (the cheap gate that decides whether to trigger the download)
// and `renderChatContent` rendering the escaped `katex-error` placeholder when
// KaTeX hasn't resolved yet. The dynamic `import("katex")` is intentionally
// not awaited/resolved here — that's covered by exercising the app, not a unit test.
import { describe, it, expect } from "vitest";
import { renderChatContent, containsMath } from "./chatMessageRender";

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
