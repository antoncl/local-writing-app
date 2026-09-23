// #2142: `maskEmphasisUnderscores` — mirrors the backend's masking table
// (backend/tests/test_name_matcher_masking.py) so the two ADR-0075
// implementations stay level on the underscore-italics surface.

import { describe, expect, it } from "vitest";
import { compileMatcher, maskEmphasisUnderscores } from "./implicitContextMatcher";
import type { LoreEntrySummary } from "@/lib/types";

const MASKING_CASES: [name: string, text: string, expected: string][] = [
  ["single-word italics, both delimiters blanked", "(see _The Implant_)", "(see  The Implant )"],
  ["strong (double-underscore) runs, both blanked", "a word __strong__ word", "a word   strong   word"],
  ["snake_case stays untouched", "the snake_case identifier", "the snake_case identifier"],
  ["a node id stays untouched", "ref lore_3071847c0f here", "ref lore_3071847c0f here"],
  ["a leading underscore-italic at start of text", "_x_ marks the spot", " x  marks the spot"],
  ["an isolated underscore between punctuation is left alone", "(_)", "(_)"],
  ["a trailing unmatched underscore (closing with no opener) is masked", "foo_ bar", "foo  bar"],
];

describe("maskEmphasisUnderscores", () => {
  for (const [name, text, expected] of MASKING_CASES) {
    it(name, () => {
      expect(maskEmphasisUnderscores(text)).toBe(expected);
    });
    it(`${name} — preserves length`, () => {
      expect(maskEmphasisUnderscores(text).length).toBe(text.length);
    });
  }

  it("preserves length on arbitrary text", () => {
    const text = "He heard whispers of _The Deserter's Rumour_. Meanwhile snake_case __bold__ _.";
    expect(maskEmphasisUnderscores(text).length).toBe(text.length);
  });

  it("empty string stays empty", () => {
    expect(maskEmphasisUnderscores("")).toBe("");
  });
});

function entry(id: string, title: string): LoreEntrySummary {
  return { id, title, entry_type: "", metadata: { aliases: [] }, body: "" } as LoreEntrySummary;
}

describe("compileMatcher — finds underscore-italicised names (#2142)", () => {
  it("scan() masks internally, so raw markdown with no pre-masking finds the name", () => {
    const matcher = compileMatcher([entry("rumour_1", "The Deserter's Rumour")]);
    const raw = "He heard whispers of _The Deserter's Rumour_.";
    const hits = matcher.scan(raw);
    expect(hits).toHaveLength(1);
    expect(hits[0].entryId).toBe("rumour_1");
    expect(hits[0].matchedText).toBe("The Deserter's Rumour");
    // Positions address the ORIGINAL text.
    expect(raw.slice(hits[0].start, hits[0].end)).toBe("The Deserter's Rumour");
  });
});
