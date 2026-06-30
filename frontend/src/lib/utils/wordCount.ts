// Shared word-count used by the prose editor's live counter and the AI
// suggestion controller's streamed-output metadata. Counts alphanumeric
// runs, allowing a single internal apostrophe or hyphen (don't, well-known).
const WORD_PATTERN = /[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?/g;

export function countWords(text: string): number {
  return Array.from(text.matchAll(WORD_PATTERN)).length;
}
