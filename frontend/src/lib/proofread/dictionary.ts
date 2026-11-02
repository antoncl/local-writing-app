// Proofreading (ADR-0102 §5): the auto-dictionary. Lore names are spelled
// right by definition, so the engine is loaded with every lore entry's title
// and aliases (and, in a scene, the names entries have as of that scene). It is
// derived on every load and never saved, so a rename leaves no stale word.
//
// No context-policy filter: the implicit-context matcher skips `never` and
// `manual_only` entries because its highlight promises context, but a `never`
// entry's name is still spelled right.
import { SEPARATOR_RE, loreEntryNames } from "@/lib/editor-core/implicitContextMatcher";
import type { LoreEntrySummary } from "@/lib/types";

// A word is trimmed of the punctuation around it ("Dr." → "Dr"), since the
// engine tokenizes that punctuation apart; inner apostrophes stay ("O'Brien").
const EDGE_PUNCTUATION_RE = /^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu;
const HAS_LETTER_RE = /\p{L}/u;

/** The words of a name, as the matcher splits it. */
export function nameWords(name: string): string[] {
  return name
    .split(SEPARATOR_RE)
    .map((w) => w.replace(EDGE_PUNCTUATION_RE, ""))
    .filter((w) => HAS_LETTER_RE.test(w));
}

/** `word` and its possessives. Harper's dictionary has no inflection, so a
 *  listed name is still flagged with `'s` appended (harper #3875). Both the
 *  straight and the curly apostrophe, since prose uses either. */
export function withPossessives(word: string): string[] {
  const forms = [word, `${word}'s`, `${word}’s`];
  if (/s$/i.test(word)) forms.push(`${word}'`, `${word}’`);
  return forms;
}

/** The engine's word list: every word of every lore name plus `extraNames`,
 *  with possessives, deduplicated and sorted. */
export function autoDictionary(entries: LoreEntrySummary[], extraNames: Iterable<string> = []): string[] {
  const words = new Set<string>();
  const add = (name: string) => {
    for (const word of nameWords(name)) for (const form of withPossessives(word)) words.add(form);
  };
  for (const entry of entries) for (const name of loreEntryNames(entry)) add(name);
  for (const name of extraNames) add(name);
  return [...words].sort();
}
