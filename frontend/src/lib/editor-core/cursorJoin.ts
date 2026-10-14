// #2459: joining a generation inserted at the cursor onto the prose around it.
// Models rarely open with a space, so a continuation from a caret right after a
// word would glue onto it ("and|" + "the" → "andthe"). The inserted text gets a
// space at an end exactly when a word would otherwise touch the prose there.
// Selection replaces never come here: they take the place of text that was
// already spaced.

// A character a word may follow directly: letters, digits, sentence and clause
// punctuation, closing quotes and brackets.
const WORD_END = /[\p{L}\p{N}.,;:!?…)\]}”’]/u;
// A character that starts a word or a quotation.
const WORD_START = /[\p{L}\p{N}“‘([{]/u;
// Straight quotes open or close by what precedes them.
const STRAIGHT_QUOTE = /["']/;
// A straight apostrophe that ends the word before it ("Honor" + "'s").
const CONTRACTION = /^'(s|t|d|m|ll|re|ve)(?![\p{L}])/iu;

// Does the prose ending in `before` (the caret's block, up to the caret) need a
// space before `text`? `before` is "" at the start of a block.
export function needsLeadingSpace(before: string, text: string): boolean {
  const first = text.charAt(0);
  if (!first || !(WORD_START.test(first) || STRAIGHT_QUOTE.test(first))) return false;
  if (CONTRACTION.test(text)) return false;
  const last = before.charAt(before.length - 1);
  if (!last) return false;
  if (STRAIGHT_QUOTE.test(last)) {
    // A closing quote follows a word; an opening one follows a space or the
    // block start, and the text goes straight inside it.
    const prev = before.charAt(before.length - 2);
    return prev !== "" && WORD_END.test(prev);
  }
  return WORD_END.test(last);
}

// Does `text` need a space after it, before the prose `after` the caret?
export function needsTrailingSpace(text: string, after: string): boolean {
  const next = after.charAt(0);
  if (!next || !(WORD_START.test(next) || STRAIGHT_QUOTE.test(next))) return false;
  const last = text.charAt(text.length - 1);
  return last !== "" && (WORD_END.test(last) || STRAIGHT_QUOTE.test(last));
}

// `text` with the spaces the caret's surroundings need.
export function joinAtCursor(before: string, text: string, after: string): string {
  const lead = needsLeadingSpace(before, text) ? " " : "";
  const trail = needsTrailingSpace(text, after) ? " " : "";
  return lead + text + trail;
}
