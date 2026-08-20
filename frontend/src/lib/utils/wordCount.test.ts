import { describe, it, expect } from "vitest";
import { countWords } from "./wordCount";

// Word count feeds the live editor chip (#1237), the `word_count` metadata field,
// and the selection toolbar's count — one helper, so lock its contract.
describe("countWords", () => {
  it("is zero for empty or whitespace-only text", () => {
    expect(countWords("")).toBe(0);
    expect(countWords("   \n\t  ")).toBe(0);
  });

  it("counts space-separated words", () => {
    expect(countWords("the lighthouse had not turned")).toBe(5);
  });

  it("ignores punctuation between words", () => {
    expect(countWords("Hello, world! Really?")).toBe(3);
  });

  it("treats a single internal apostrophe or hyphen as one word", () => {
    expect(countWords("don't")).toBe(1);
    expect(countWords("well-known")).toBe(1);
  });

  it("counts numbers as words", () => {
    expect(countWords("3 blind mice")).toBe(3);
  });

  it("counts across newlines and collapses blank lines", () => {
    expect(countWords("first line\n\nsecond line")).toBe(4);
  });

  it("splits a double-hyphen run (only one internal separator is joined)", () => {
    // "mother-in-law" → "mother-in" + "law": the pattern joins a single
    // separator group, so the trailing "-law" starts a new match.
    expect(countWords("mother-in-law")).toBe(2);
  });
});
