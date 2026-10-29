// #2567: a separator-only name ("-") normalises to "" and once compiled into an
// empty alternative that matched at every boundary. The scan loop never
// advanced past a zero-length match, so it hung the page. Mirrors
// backend/tests/test_name_matcher_separator_only.py.

import { describe, expect, it } from "vitest";
import { compileMatcher } from "./implicitContextMatcher";
import type { LoreEntrySummary } from "@/lib/types";

function entry(id: string, title: string, aliases: string[]): LoreEntrySummary {
  return { id, title, entry_type: "", metadata: { aliases }, body: "" } as LoreEntrySummary;
}

describe("compileMatcher — separator-only names (#2567)", () => {
  it("a separator-only alias neither hangs the scan nor adds a phantom hit", () => {
    const matcher = compileMatcher([entry("honor_1", "Honor", ["-", "--", "- -"])]);
    const hits = matcher.scan("Honor met the admiral.");
    expect(hits).toEqual([{ start: 0, end: 5, entryId: "honor_1", matchedText: "Honor" }]);
  });

  it("an entry whose only names are separators compiles to an empty matcher", () => {
    const matcher = compileMatcher([entry("dash_1", "-", ["--"])]);
    expect(matcher.isEmpty).toBe(true);
    expect(matcher.scan("any text at all")).toEqual([]);
  });
});
