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

/** A scene's name set for one entity: its id and `[title, ...aliases]`, as the
 *  effective-names endpoint returns them. */
export type SceneNameSet = [entityId: string, names: string[]];

/** The engine's word list: every word of every lore name, plus the name sets
 *  in `sceneNames`, with possessives, deduplicated and sorted.
 *
 *  Whether a title is case-sensitive is decided by its entry's type
 *  (`properName`, ADR-0102 Amendment 4). A proper-noun type's title goes in as
 *  written: Harper accepts a capitalized entry only capitalized, so "kael" is
 *  still flagged for the entry "Kael". Any other type's title goes in lower case
 *  too (Harper accepts a lowercase entry in either case), so a concept like
 *  "Katadesis" may be written "katadesis". An alias is always any case. A scene
 *  name set whose id is not in `entries` counts as a proper name. */
export function autoDictionary(
  entries: LoreEntrySummary[],
  sceneNames: Iterable<SceneNameSet> = [],
  properName: (entryType: string) => boolean = () => true,
): string[] {
  const words = new Set<string>();
  const add = (name: string, anyCase: boolean) => {
    for (const word of nameWords(name)) {
      for (const form of withPossessives(word)) words.add(form);
      const lower = word.toLowerCase();
      if (anyCase && lower !== word) for (const form of withPossessives(lower)) words.add(form);
    }
  };
  const addNameSet = ([title, ...aliases]: string[], titleAnyCase: boolean) => {
    if (title) add(title, titleAnyCase);
    for (const alias of aliases) add(alias, true);
  };
  const typeOf = new Map<string, string>();
  for (const entry of entries) {
    typeOf.set(entry.id, entry.entry_type);
    addNameSet(loreEntryNames(entry), !properName(entry.entry_type));
  }
  for (const [id, nameSet] of sceneNames) {
    const type = typeOf.get(id);
    addNameSet(nameSet, type !== undefined && !properName(type));
  }
  return [...words].sort();
}
