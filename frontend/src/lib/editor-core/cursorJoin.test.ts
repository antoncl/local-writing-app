import { describe, expect, it } from "vitest";
import { joinAtCursor } from "./cursorJoin";

// #2459: a generation inserted at the cursor is spaced from the prose around it
// exactly when a word would otherwise touch it.
describe("joinAtCursor", () => {
  it.each([
    // [before, text, after, joined]
    ["at dusk and", "the admiral", "", " the admiral"],
    ["at dusk and ", "the admiral", "", "the admiral"], // already spaced
    ["at dusk and", " the admiral", "", " the admiral"], // the model spaced it
    ["", "Night fell.", "", "Night fell."], // block start
    ["at dusk", ", and then", "", ", and then"], // punctuation joins directly
    ["He said,", "“Go.”", "", " “Go.”"],
    ["He said,", '"Go."', "", ' "Go."'],
    ['He said, "', "Go", "", "Go"], // inside an opening straight quote
    ['"Go."', "She left.", "", ' She left.'], // after a closing straight quote
    ["He said, “", "Go", "", "Go"], // inside an opening curly quote
    ["(", "aside", "", "aside"],
    ["word\ufffc", "next", "", "next"], // after a pill or a line break
    ["", "Night fell.", "The admiral", "Night fell. "],
    ["", "Night fell.", " The admiral", "Night fell."],
    ["", "Night fell", ".", "Night fell"], // punctuation after joins directly
    ["and", "the admiral\n", "waited", " the admiral\n"], // ends on a break
    ["and", "", "", ""],
  ])("%j + %j + %j → %j", (before, text, after, joined) => {
    expect(joinAtCursor(before, text, after)).toBe(joined);
  });
});
