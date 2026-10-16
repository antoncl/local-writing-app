// @vitest-environment happy-dom
// #2526: the blank line between paragraphs is its own choice, not a side effect
// of the first-line indent.
import { afterEach, describe, expect, it } from "vitest";
import { applyProsePresentation } from "./prose-presentation";

const root = () => document.documentElement.style;
const base = { ui_scale: 1, paragraph_align: "left" as const };

afterEach(() => {
  for (const p of ["--ui-scale", "--prose-align", "--prose-indent", "--prose-para-gap"]) root().removeProperty(p);
});

describe("applyProsePresentation", () => {
  it("indents AND spaces paragraphs when both are on", () => {
    applyProsePresentation({ ...base, paragraph_indent: true, paragraph_spacing: true });
    expect(root().getPropertyValue("--prose-indent")).toBe("1.5em");
    // Spacing on: each prose surface keeps its own gap default.
    expect(root().getPropertyValue("--prose-para-gap")).toBe("");
  });

  it("runs paragraphs together when spacing is off, indented or not", () => {
    applyProsePresentation({ ...base, paragraph_indent: false, paragraph_spacing: false });
    expect(root().getPropertyValue("--prose-para-gap")).toBe("0");
    expect(root().getPropertyValue("--prose-indent")).toBe("0");
    applyProsePresentation({ ...base, paragraph_indent: true, paragraph_spacing: false });
    expect(root().getPropertyValue("--prose-para-gap")).toBe("0");
  });

  it("turning spacing back on removes the zero gap", () => {
    applyProsePresentation({ ...base, paragraph_indent: true, paragraph_spacing: false });
    applyProsePresentation({ ...base, paragraph_indent: true, paragraph_spacing: true });
    expect(root().getPropertyValue("--prose-para-gap")).toBe("");
  });
});
